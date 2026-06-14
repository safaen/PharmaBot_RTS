#!/usr/bin/env python3
"""
dma_tasks.py — Deadline Monotonic Scheduling pour PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

DMA : priorité statique inversement proportionnelle à la deadline.
      Deadline la plus courte = priorité la plus haute.

Tâches :
    P1 — Sécurité mission        D=3s   T=10s  HARD_RT
    P2 — Confirmation médicament D=5s   T=15s  HARD_RT
    P3 — Accusé de réception     D=8s   T=20s  FIRM_RT
    P4 — Validation pharmacien   D=10s  T=30s  SOFT_RT

CORRECTIONS Phase 1+2 :
    ✓ /pharmabot/dma_pipeline publié à CHAQUE étape du pipeline
    ✓ /pharmabot/dma_alerte correctement formaté pour WatchdogNode
      (champ "priorite" présent — WatchdogNode vérifie priorite==1)
    ✓ Pipeline complet VALIDATION_PHARMACIEN → CONFIRMATION_MEDICAMENT
      → NAVIGATION → LIVRAISON → IDLE
    ✓ Écoute /pharmabot/nav_status pour déclencher LIVRAISON au bon moment
    ✓ Écoute /pharmabot/pharmacist_ok (Phase 2) pour synchronisation pharmacien
    ✓ Interruption HARD_RT : pipeline interruptible
"""
import json
import threading
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

TACHES_DMA = {
    "securite_mission": {
        "nom": "Sécurité mission",
        "deadline_sec": 3, "periode_sec": 10,
        "priorite": 1, "type": "HARD_RT",
    },
    "confirmation_medicament": {
        "nom": "Confirmation médicament",
        "deadline_sec": 5, "periode_sec": 15,
        "priorite": 2, "type": "HARD_RT",
    },
    "accuse_reception": {
        "nom": "Accusé de réception",
        "deadline_sec": 8, "periode_sec": 20,
        "priorite": 3, "type": "FIRM_RT",
    },
    "validation_pharmacien": {
        "nom": "Validation pharmacien",
        "deadline_sec": 10, "periode_sec": 30,
        "priorite": 4, "type": "SOFT_RT",
    },
}

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
ORANGE = "\033[93m"
CYAN   = "\033[96m"


class TacheDMA:
    def __init__(self, id_tache: str):
        info = TACHES_DMA[id_tache]
        self.id_tache        = id_tache
        self.nom             = info["nom"]
        self.deadline_sec    = info["deadline_sec"]
        self.periode_sec     = info["periode_sec"]
        self.priorite        = info["priorite"]
        self.type_rt         = info["type"]
        self.etat            = "PRET"
        self.timestamp_debut = None
        self.nb_executions   = 0
        self.nb_succes       = 0
        self.nb_echecs       = 0

    def activer(self):
        self.etat            = "EN_COURS"
        self.timestamp_debut = time.time()
        self.nb_executions  += 1

    def terminer(self, succes: bool = True):
        t  = time.time() - self.timestamp_debut
        ok = succes and t <= self.deadline_sec
        self.etat = "TERMINE" if ok else "ECHOUE"
        if ok:
            self.nb_succes += 1
        else:
            self.nb_echecs += 1
        return ok, t

    def deadline_depassee(self) -> bool:
        return (
            self.timestamp_debut is not None
            and (time.time() - self.timestamp_debut) > self.deadline_sec
        )


class DMAScheduler(Node):
    def __init__(self):
        super().__init__("dma_scheduler")
        self.get_logger().info(
            f"{BOLD}{CYAN}DMA Scheduler PharmaBot démarré{RESET}")
        self._log_tableau_dma()

        self._taches           = {k: TacheDMA(k) for k in TACHES_DMA}
        self._etat_pipeline    = "IDLE"
        self._mission_courante = None
        self._pipeline_lock    = threading.Lock()
        self._pharmacist_ok    = threading.Event()  # Phase 2
        self._nav_arrive       = threading.Event()  # Phase 1

        self._stats = {
            "missions_traitees":  0,
            "missions_succes":    0,
            "deadlines_manquees": 0,
            "arrets_securite":    0,
        }

        # ── Publishers ──
        self._pub_status   = self.create_publisher(
            String, "/pharmabot/dma_status",   10)
        self._pub_alerte   = self.create_publisher(
            String, "/pharmabot/dma_alerte",   10)
        self._pub_pipeline = self.create_publisher(
            String, "/pharmabot/dma_pipeline", 10)

        # ── Subscribers ──
        self._sub_mission = self.create_subscription(
            String, "/pharmabot/tache_courante",
            self._cb_nouvelle_mission, 10)
        # Phase 1 : détection arrivée depuis navigation_bridge
        self._sub_nav = self.create_subscription(
            String, "/pharmabot/nav_status",
            self._cb_nav_status, 10)
        # Phase 2 : pharmacien a validé le médicament
        self._sub_pharmacist = self.create_subscription(
            String, "/pharmabot/pharmacist_ok",
            self._cb_pharmacist_ok, 10)
        # Interruption EDF (HARD_RT override)
        self._sub_interruption = self.create_subscription(
            String, "/pharmabot/edf_interruption",
            self._cb_edf_interruption, 10)

        # ── Timers périodiques DMA ──
        self.create_timer(
            TACHES_DMA["securite_mission"]["periode_sec"],
            lambda: self._executer_tache("securite_mission"))
        self.create_timer(
            TACHES_DMA["confirmation_medicament"]["periode_sec"],
            lambda: self._executer_tache("confirmation_medicament"))
        self.create_timer(
            TACHES_DMA["accuse_reception"]["periode_sec"],
            lambda: self._executer_tache("accuse_reception"))
        self.create_timer(
            TACHES_DMA["validation_pharmacien"]["periode_sec"],
            lambda: self._executer_tache("validation_pharmacien"))
        self.create_timer(3.0, self._publier_status)

    # ═══════════════════════════════════════════════
    # Tâches périodiques de sécurité
    # ═══════════════════════════════════════════════

    def _executer_tache(self, id_tache: str):
        t = self._taches[id_tache]
        t.activer()
        self.get_logger().info(
            f"[DMA P{t.priorite}] ▶ {t.nom} | "
            f"D={t.deadline_sec}s | T={t.periode_sec}s")

        delais = {
            "securite_mission":        0.5,
            "confirmation_medicament": 1.0,
            "accuse_reception":        2.0,
            "validation_pharmacien":   3.0,
        }
        time.sleep(delais.get(id_tache, 1.0))

        ok, temps = t.terminer(True)
        if ok:
            self.get_logger().info(
                f"{GREEN}[DMA P{t.priorite}] ✓ {t.nom} "
                f"en {temps:.2f}s{RESET}")
        else:
            self._stats["deadlines_manquees"] += 1
            self.get_logger().warn(
                f"{ORANGE}[DMA P{t.priorite}] ✗ DEADLINE MANQUÉE "
                f"{t.nom} ({temps:.2f}s > {t.deadline_sec}s){RESET}")
            self._publier_alerte_dma(id_tache, temps)

            if id_tache == "securite_mission":
                self._stats["arrets_securite"] += 1
                self.get_logger().error(
                    f"{RED}{BOLD}[DMA P1] SÉCURITÉ ÉCHOUÉE — "
                    f"ARRÊT D'URGENCE{RESET}")
                self._changer_etat_pipeline("ARRET_URGENCE")

    # ═══════════════════════════════════════════════
    # Pipeline de livraison
    # ═══════════════════════════════════════════════

    def _cb_nouvelle_mission(self, msg: String):
        try:
            data = json.loads(msg.data)
            dept = data.get("departement")
            if not dept or dept == "pharmacie":
                return

            with self._pipeline_lock:
                if self._etat_pipeline not in ("IDLE", "ARRET_URGENCE"):
                    if data.get("type_rt") != "HARD_RT":
                        return
                    self.get_logger().warn(
                        f"{RED}[DMA] HARD_RT OVERRIDE pipeline{RESET}")
                    # Réinitialiser les événements pour la nouvelle mission
                    self._pharmacist_ok.clear()
                    self._nav_arrive.clear()

                self._mission_courante = data
                self._stats["missions_traitees"] += 1

            self.get_logger().info(
                f"{CYAN}[DMA PIPELINE] Démarrage : "
                f"{dept} | {data.get('medicament')}{RESET}")

            threading.Thread(
                target=self._executer_pipeline,
                args=(data,),
                daemon=True,
            ).start()

        except json.JSONDecodeError as e:
            self.get_logger().error(f"[DMA] Mission invalide : {e}")

    def _cb_nav_status(self, msg: String):
        """Phase 1 : l'arrivée à destination débloque l'étape LIVRAISON."""
        try:
            data = json.loads(msg.data)
            if data.get("type") == "ARRIVE_DESTINATION":
                self._nav_arrive.set()
                with self._pipeline_lock:
                    if self._etat_pipeline == "NAVIGATION":
                        self._changer_etat_pipeline("LIVRAISON")
        except json.JSONDecodeError:
            pass

    def _cb_pharmacist_ok(self, msg: String):
        """Phase 2 : le pharmacien a validé → débloque l'étape de chargement."""
        try:
            data = json.loads(msg.data)
            if data.get("type") == "PHARMACIST_OK":
                dept_ok = data.get("departement")
                if (self._mission_courante
                        and self._mission_courante.get("departement") == dept_ok):
                    self.get_logger().info(
                        f"{GREEN}[DMA] Pharmacien OK → chargement autorisé{RESET}")
                    self._pharmacist_ok.set()
        except json.JSONDecodeError:
            pass

    def _cb_edf_interruption(self, msg: String):
        """Réinitialise les événements lors d'un override EDF."""
        try:
            data = json.loads(msg.data)
            if data.get("type") == "EDF_INTERRUPTION":
                self._pharmacist_ok.clear()
                self._nav_arrive.clear()
        except json.JSONDecodeError:
            pass

    def _executer_pipeline(self, mission: dict):
        """
        Pipeline DMA complet en 4 étapes.
        Chaque étape publie sur /pharmabot/dma_pipeline.
        """
        dept = mission.get("departement", "?")
        try:
            # ── Étape 1 : Validation pharmacien ──
            self._changer_etat_pipeline("VALIDATION_PHARMACIEN")
            t = self._taches["validation_pharmacien"]
            t.activer()
            self.get_logger().info(
                f"[DMA] 1/4 Attente validation pharmacien...")

            # Phase 2 : attendre OK du pharmacien (timeout 15s)
            got_ok = self._pharmacist_ok.wait(timeout=15.0)
            self._pharmacist_ok.clear()
            if not got_ok:
                self.get_logger().warn(
                    "[DMA] Timeout pharmacien — passage forcé")

            ok, temps = t.terminer(True)
            self.get_logger().info(
                f"{GREEN if ok else ORANGE}[DMA] 1/4 "
                f"{'✓' if ok else '✗'} Pharmacien {temps:.1f}s{RESET}")

            # ── Étape 2 : Confirmation médicament / chargement ──
            self._changer_etat_pipeline("CONFIRMATION_MEDICAMENT")
            t = self._taches["confirmation_medicament"]
            t.activer()
            self.get_logger().info("[DMA] 2/4 Confirmation médicament...")
            time.sleep(1.0)
            ok, temps = t.terminer(True)
            self.get_logger().info(
                f"{GREEN if ok else ORANGE}[DMA] 2/4 "
                f"{'✓' if ok else '✗'} Médicament chargé {temps:.1f}s{RESET}")
            if not ok:
                self._publier_alerte_dma("confirmation_medicament", temps)

            # ── Étape 3 : Navigation ──
            self._changer_etat_pipeline("NAVIGATION")
            self.get_logger().info(
                f"[DMA] 3/4 Navigation vers {dept}...")
            # Attendre arrivée du robot (timeout = deadline + 30s)
            timeout = mission.get("deadline_sec", 300) + 30
            self._nav_arrive.wait(timeout=timeout)
            self._nav_arrive.clear()

            # ── Étape 4 : Livraison / accusé de réception ──
            self._changer_etat_pipeline("LIVRAISON")
            t = self._taches["accuse_reception"]
            t.activer()
            self.get_logger().info("[DMA] 4/4 Accusé de réception...")
            time.sleep(1.5)
            ok, temps = t.terminer(True)
            self.get_logger().info(
                f"{GREEN if ok else ORANGE}[DMA] 4/4 "
                f"{'✓' if ok else '✗'} Réception {temps:.1f}s{RESET}")
            if not ok:
                self._publier_alerte_dma("accuse_reception", temps)

            self._stats["missions_succes"] += 1
            self.get_logger().info(
                f"{GREEN}{BOLD}[DMA] ══ Mission {dept} COMPLÈTE "
                f"({self._stats['missions_succes']}/"
                f"{self._stats['missions_traitees']}) ══{RESET}")
            self._changer_etat_pipeline("IDLE")

        except Exception as e:
            self.get_logger().error(f"[DMA PIPELINE] Erreur : {e}")
            self._changer_etat_pipeline("IDLE")

    # ═══════════════════════════════════════════════
    # Publication états et alertes
    # ═══════════════════════════════════════════════

    def _changer_etat_pipeline(self, nouvel_etat: str):
        """Publie chaque changement d'état — mission_manager écoute ce topic."""
        with self._pipeline_lock:
            ancien              = self._etat_pipeline
            self._etat_pipeline = nouvel_etat

        self.get_logger().info(
            f"[DMA PIPELINE] {ancien} → {nouvel_etat}")

        msg      = String()
        msg.data = json.dumps({
            "etat":      nouvel_etat,
            "ancien":    ancien,
            "timestamp": time.time(),
            "mission":   self._mission_courante,
        })
        self._pub_pipeline.publish(msg)

    def _publier_alerte_dma(self, id_tache: str, temps: float):
        """
        CORRECTION : champ "priorite" requis par WatchdogNode._cb_alerte_dma
        qui vérifie alerte.get("priorite") == 1 pour le P1.
        """
        t        = self._taches[id_tache]
        msg      = String()
        msg.data = json.dumps({
            "type_alerte":  "DMA_DEADLINE_MANQUEE",
            "tache":        id_tache,
            "nom":          t.nom,
            "priorite":     t.priorite,      # ← champ requis par watchdog
            "type_rt":      t.type_rt,
            "deadline_sec": t.deadline_sec,
            "temps_ecoule": round(temps, 3),
            "timestamp":    time.time(),
        })
        self._pub_alerte.publish(msg)

    def _publier_status(self):
        msg      = String()
        msg.data = json.dumps({
            "taches": {
                k: {
                    "nom":       t.nom,
                    "priorite":  t.priorite,
                    "etat":      t.etat,
                    "nb_succes": t.nb_succes,
                    "nb_echecs": t.nb_echecs,
                    "type_rt":   t.type_rt,
                }
                for k, t in self._taches.items()
            },
            "etat_pipeline": self._etat_pipeline,
            "stats":         self._stats,
            "timestamp":     time.time(),
        })
        self._pub_status.publish(msg)

    def _log_tableau_dma(self):
        self.get_logger().info(
            "Tableau DMA — Deadline Monotonic Scheduling")
        self.get_logger().info(
            f"{'Priorité':<10}{'Tâche':<30}{'Deadline':<12}"
            f"{'Période':<10}{'Type RT'}")
        self.get_logger().info("-" * 72)
        for k, info in sorted(
                TACHES_DMA.items(), key=lambda x: x[1]["priorite"]):
            self.get_logger().info(
                f"P{info['priorite']:<9}{info['nom']:<30}"
                f"{info['deadline_sec']}s{'':<9}"
                f"{info['periode_sec']}s{'':<6}{info['type']}")


def main(args=None):
    rclpy.init(args=args)
    s = DMAScheduler()
    try:
        rclpy.spin(s)
    except KeyboardInterrupt:
        pass
    finally:
        s.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
