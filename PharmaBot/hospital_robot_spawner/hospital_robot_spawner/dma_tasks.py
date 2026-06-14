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
"""
import time, threading, json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

TACHES_DMA = {
    "securite_mission":        {"nom": "Sécurité mission",        "deadline_sec": 3,  "periode_sec": 10, "priorite": 1, "type": "HARD_RT"},
    "confirmation_medicament": {"nom": "Confirmation médicament", "deadline_sec": 5,  "periode_sec": 15, "priorite": 2, "type": "HARD_RT"},
    "accuse_reception":        {"nom": "Accusé de réception",     "deadline_sec": 8,  "periode_sec": 20, "priorite": 3, "type": "FIRM_RT"},
    "validation_pharmacien":   {"nom": "Validation pharmacien",   "deadline_sec": 10, "periode_sec": 30, "priorite": 4, "type": "SOFT_RT"},
}


class TacheDMA:
    def __init__(self, id_tache: str):
        info = TACHES_DMA[id_tache]
        self.id_tache = id_tache
        self.nom = info["nom"]; self.deadline_sec = info["deadline_sec"]
        self.periode_sec = info["periode_sec"]; self.priorite = info["priorite"]
        self.type_rt = info["type"]; self.etat = "PRET"
        self.timestamp_debut = None
        self.nb_executions = self.nb_succes = self.nb_echecs = 0

    def activer(self):
        self.etat = "EN_COURS"; self.timestamp_debut = time.time()
        self.nb_executions += 1

    def terminer(self, succes=True):
        t = time.time() - self.timestamp_debut
        ok = succes and t <= self.deadline_sec
        self.etat = "TERMINE" if ok else "ECHOUE"
        if ok: self.nb_succes += 1
        else:  self.nb_echecs += 1
        return ok, t

    def deadline_depassee(self):
        return self.timestamp_debut is not None and \
               (time.time() - self.timestamp_debut) > self.deadline_sec


class DMAScheduler(Node):
    def __init__(self):
        super().__init__("dma_scheduler")
        self.get_logger().info("DMA Scheduler PharmaBot démarré")
        self._log_tableau_dma()
        self._taches = {k: TacheDMA(k) for k in TACHES_DMA}
        self._etat_pipeline = "IDLE"
        self._mission_courante = None
        self._stats = {"missions_traitees": 0, "missions_succes": 0,
                       "deadlines_manquees": 0, "arrets_securite": 0}

        self._pub_status   = self.create_publisher(String, "/pharmabot/dma_status",   10)
        self._pub_alerte   = self.create_publisher(String, "/pharmabot/dma_alerte",   10)
        self._pub_pipeline = self.create_publisher(String, "/pharmabot/dma_pipeline", 10)
        self._sub_mission  = self.create_subscription(
            String, "/pharmabot/tache_courante", self._cb_nouvelle_mission, 10)

        # Timers périodiques DMA selon leur période propre
        self.create_timer(TACHES_DMA["securite_mission"]["periode_sec"],
                          lambda: self._executer_tache("securite_mission"))
        self.create_timer(TACHES_DMA["confirmation_medicament"]["periode_sec"],
                          lambda: self._executer_tache("confirmation_medicament"))
        self.create_timer(TACHES_DMA["accuse_reception"]["periode_sec"],
                          lambda: self._executer_tache("accuse_reception"))
        self.create_timer(TACHES_DMA["validation_pharmacien"]["periode_sec"],
                          lambda: self._executer_tache("validation_pharmacien"))
        self.create_timer(3.0, self._publier_status)

    def _executer_tache(self, id_tache: str):
        t = self._taches[id_tache]
        t.activer()
        self.get_logger().info(
            f"[DMA P{t.priorite}] ▶ {t.nom} | D={t.deadline_sec}s | T={t.periode_sec}s")
        delais = {"securite_mission": 0.5, "confirmation_medicament": 1.0,
                  "accuse_reception": 2.0, "validation_pharmacien": 3.0}
        time.sleep(delais.get(id_tache, 1.0))
        ok, temps = t.terminer(True)
        if ok:
            self.get_logger().info(f"[DMA P{t.priorite}] ✓ {t.nom} en {temps:.2f}s")
        else:
            self._stats["deadlines_manquees"] += 1
            self.get_logger().warn(
                f"[DMA P{t.priorite}] ✗ DEADLINE MANQUÉE {t.nom} ({temps:.2f}s > {t.deadline_sec}s)")
            self._publier_alerte(id_tache, temps)
            if id_tache == "securite_mission":
                self._stats["arrets_securite"] += 1
                self.get_logger().error("[DMA P1] SÉCURITÉ ÉCHOUÉE — ARRÊT D'URGENCE")

    def _cb_nouvelle_mission(self, msg: String):
        try:
            data = json.loads(msg.data)
            self._mission_courante = data
            self._stats["missions_traitees"] += 1
            self.get_logger().info(
                f"[DMA PIPELINE] Mission : {data.get('departement')} | {data.get('medicament')}")
            threading.Thread(target=self._executer_pipeline, args=(data,), daemon=True).start()
        except json.JSONDecodeError as e:
            self.get_logger().error(f"Mission invalide : {e}")

    def _executer_pipeline(self, mission: dict):
        etapes = [
            ("validation_pharmacien",   "VALIDATION_PHARMACIEN",   2.0),
            ("confirmation_medicament", "CONFIRMATION_MEDICAMENT",  1.0),
            ("accuse_reception",        "LIVRAISON",                1.5),
        ]
        for id_tache, etat, delai in etapes:
            self._changer_etat(etat)
            t = self._taches[id_tache]
            t.activer()
            self.get_logger().info(f"[DMA PIPELINE] {t.nom} (D={t.deadline_sec}s)")
            time.sleep(delai)
            ok, temps = t.terminer(True)
            self.get_logger().info(f"[DMA PIPELINE] ✓ {t.nom} OK en {temps:.1f}s")
        self._stats["missions_succes"] += 1
        self._changer_etat("IDLE")
        self.get_logger().info(
            f"[DMA PIPELINE] ══ Mission complète : "
            f"{self._stats['missions_succes']}/{self._stats['missions_traitees']} ══")

    def _changer_etat(self, nouvel_etat: str):
        ancien = self._etat_pipeline
        self._etat_pipeline = nouvel_etat
        self.get_logger().info(f"[DMA PIPELINE] {ancien} → {nouvel_etat}")
        msg = String()
        msg.data = json.dumps({"etat": nouvel_etat, "ancien": ancien,
                               "timestamp": time.time(), "mission": self._mission_courante})
        self._pub_pipeline.publish(msg)

    def _publier_status(self):
        msg = String()
        msg.data = json.dumps({
            "taches": {k: {"nom": t.nom, "priorite": t.priorite,
                           "etat": t.etat, "nb_succes": t.nb_succes,
                           "nb_echecs": t.nb_echecs}
                       for k, t in self._taches.items()},
            "etat_pipeline": self._etat_pipeline,
            "stats": self._stats, "timestamp": time.time()})
        self._pub_status.publish(msg)

    def _publier_alerte(self, id_tache: str, temps: float):
        t = self._taches[id_tache]
        msg = String()
        msg.data = json.dumps({"type_alerte": "DMA_DEADLINE_MANQUEE",
                               "tache": id_tache, "nom": t.nom,
                               "priorite": t.priorite, "deadline_sec": t.deadline_sec,
                               "temps_ecoule": temps, "timestamp": time.time()})
        self._pub_alerte.publish(msg)

    def _log_tableau_dma(self):
        self.get_logger().info("Tableau DMA — Deadline Monotonic Scheduling")
        self.get_logger().info(f"{'Priorité':<10}{'Tâche':<30}{'Deadline':<12}{'Période':<10}{'Type RT'}")
        self.get_logger().info("-" * 72)
        for k, info in sorted(TACHES_DMA.items(), key=lambda x: x[1]["priorite"]):
            self.get_logger().info(
                f"P{info['priorite']:<9}{info['nom']:<30}{info['deadline_sec']}s{'':<9}"
                f"{info['periode_sec']}s{'':<6}{info['type']}")


def main(args=None):
    rclpy.init(args=args)
    s = DMAScheduler()
    try: rclpy.spin(s)
    except KeyboardInterrupt: pass
    finally: s.destroy_node(); rclpy.shutdown()

if __name__ == "__main__": main()
