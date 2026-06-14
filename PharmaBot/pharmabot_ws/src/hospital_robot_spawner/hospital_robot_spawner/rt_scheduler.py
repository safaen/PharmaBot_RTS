#!/usr/bin/env python3
"""
rt_scheduler.py — EDF Scheduler (Earliest Deadline First) pour PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

EDF : la tâche avec la deadline la plus proche est toujours prioritaire.
      Tri dynamique — change à chaque nouvelle requête.

MODIFICATIONS Phase 1+2 :
    - Suppression des 4 requêtes codées en dur dans main() :
      les requêtes arrivent maintenant depuis doctor_request_node.py
    - Ajout de _pub_interruption : signale au mission_manager quand
      une HARD_RT doit interrompre la tâche courante
    - Ajout de _tache_en_cours_dept pour détecter les vrais overrides EDF
    - Méthode set_tache_en_cours() appelable depuis l'extérieur
    - Toutes les fonctionnalités existantes conservées intégralement
"""
import heapq
import time
import json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

PRIORITE_HARD_RT = 1
PRIORITE_SOFT_RT = 2
PRIORITE_FIRM_RT = 3

DEPARTEMENTS_INFO = {
    "reanimation": {
        "nom":         "ICU_Room",
        "priorite":    PRIORITE_HARD_RT,
        "type_rt":     "HARD_RT",
        "deadline_sec": 30,
        "couleur":     "\033[91m",
        "consequence": "FATAL — alerte + mode récupération",
    },
    "urgences": {
        "nom":         "Emergency_Room",
        "priorite":    PRIORITE_SOFT_RT,
        "type_rt":     "SOFT_RT",
        "deadline_sec": 120,
        "couleur":     "\033[93m",
        "consequence": "Délai toléré — qualité dégradée",
    },
    "consultation": {
        "nom":         "Consultation_Room",
        "priorite":    PRIORITE_FIRM_RT,
        "type_rt":     "FIRM_RT",
        "deadline_sec": 300,
        "couleur":     "\033[92m",
        "consequence": "Annulé si deadline dépassée",
    },
}
RESET = "\033[0m"
BOLD  = "\033[1m"


class RequeteLivraison:
    def __init__(self, departement: str, medicament: str = "Médicament standard"):
        if departement not in DEPARTEMENTS_INFO:
            raise ValueError(f"Département inconnu : {departement}")
        info = DEPARTEMENTS_INFO[departement]
        self.departement  = departement
        self.nom_dept     = info["nom"]
        self.priorite     = info["priorite"]
        self.type_rt      = info["type_rt"]
        self.deadline_sec = info["deadline_sec"]
        self.couleur      = info["couleur"]
        self.consequence  = info["consequence"]
        self.medicament   = medicament
        self.timestamp    = time.time()

    def temps_restant(self) -> float:
        return self.deadline_sec - (time.time() - self.timestamp)

    def deadline_depassee(self) -> bool:
        return self.temps_restant() <= 0

    def __lt__(self, other):
        return self.temps_restant() < other.temps_restant()

    def __repr__(self):
        return (
            f"{self.couleur}[{self.type_rt}]{RESET} "
            f"{self.nom_dept} | {self.medicament} | "
            f"{self.temps_restant():.0f}s restantes"
        )


class RTScheduler(Node):
    def __init__(self):
        super().__init__("rt_scheduler")
        self.get_logger().info(f"{BOLD}EDF RT Scheduler PharmaBot démarré{RESET}")
        self._file_priorite   = []
        self._tache_courante  = None
        # PHASE 1 : mémoriser le département en cours pour détecter les overrides
        self._dept_en_cours   = None

        # ── Publishers ──
        self._pub_tache        = self.create_publisher(String, "/pharmabot/tache_courante",   10)
        self._pub_alerte       = self.create_publisher(String, "/pharmabot/alerte_rt",         10)
        # PHASE 1 : nouveau topic d'interruption EDF → mission_manager + nav_bridge
        self._pub_interruption = self.create_publisher(String, "/pharmabot/edf_interruption",  10)

        # ── Subscribers ──
        self._sub_requete = self.create_subscription(
            String, "/pharmabot/requete", self._cb_nouvelle_requete, 10)
        # PHASE 2 : écoute les confirmations de livraison pour libérer le scheduler
        self._sub_livraison = self.create_subscription(
            String, "/pharmabot/livraison_confirmee", self._cb_livraison_confirmee, 10)

        # ── Timers ──
        self._timer_check = self.create_timer(2.0,  self._verifier_deadlines)
        self._timer_pub   = self.create_timer(5.0,  self._publier_tache_courante)

        self._stats = {
            "total": 0, "hard_rt": 0, "soft_rt": 0,
            "firm_rt": 0, "deadlines_hard": 0,
            "deadlines_soft": 0, "annulations": 0,
            "overrides_edf": 0,
        }

    # ═══════════════════════════════════════════════
    # Callbacks
    # ═══════════════════════════════════════════════

    def _cb_nouvelle_requete(self, msg: String):
        """Reçoit une requête depuis doctor_request_node (ou toute autre source)."""
        try:
            data = json.loads(msg.data)
            self._ajouter_requete(RequeteLivraison(
                data.get("departement", "consultation"),
                data.get("medicament",  "Médicament standard"),
            ))
        except (json.JSONDecodeError, ValueError) as e:
            self.get_logger().error(f"Requête invalide : {e}")

    def _cb_livraison_confirmee(self, msg: String):
        """
        PHASE 2 : quand une livraison est confirmée, libère le slot courant
        et traite la prochaine tâche dans la file.
        """
        try:
            data = json.loads(msg.data)
            dept = data.get("departement")
            self.get_logger().info(
                f"[EDF] Livraison confirmée : {dept} — libération slot")
            self._dept_en_cours  = None
            self._tache_courante = None
            # Traiter immédiatement la prochaine tâche si elle existe
            if self._file_priorite:
                self._publier_tache_courante()
        except json.JSONDecodeError:
            pass

    # ═══════════════════════════════════════════════
    # Ajout et gestion de la file EDF
    # ═══════════════════════════════════════════════

    def ajouter_requete(self, departement: str, medicament: str = "Médicament standard"):
        """API publique pour ajouter une requête directement."""
        self._ajouter_requete(RequeteLivraison(departement, medicament))

    def _ajouter_requete(self, requete: RequeteLivraison):
        heapq.heappush(self._file_priorite, requete)
        self._stats["total"] += 1
        key = requete.type_rt.lower()
        if key in self._stats:
            self._stats[key] += 1

        self.get_logger().info(
            f"{BOLD}[EDF] Nouvelle requête{RESET} {requete} | "
            f"File : {len(self._file_priorite)}"
        )
        self._afficher_file()

        # PHASE 1 : détecter si cette requête HARD_RT doit interrompre
        # la tâche en cours (qui est moins prioritaire)
        if (requete.type_rt == "HARD_RT"
                and self._dept_en_cours is not None
                and self._dept_en_cours != requete.departement):
            dept_info = DEPARTEMENTS_INFO.get(self._dept_en_cours, {})
            if dept_info.get("type_rt") != "HARD_RT":
                self._signaler_interruption_edf(requete)

    def prochaine_tache(self):
        """Extrait et retourne la tâche avec la deadline la plus proche (EDF)."""
        while self._file_priorite:
            requete = heapq.heappop(self._file_priorite)
            if requete.type_rt == "FIRM_RT" and requete.deadline_depassee():
                self._stats["annulations"] += 1
                self.get_logger().info(
                    f"{requete.couleur}[FIRM RT ANNULÉ]{RESET} {requete.nom_dept}")
                self._publier_alerte("FIRM_RT_ANNULE", requete)
                continue
            self._tache_courante = requete
            self._dept_en_cours  = requete.departement
            self.get_logger().info(f"{BOLD}[EDF ASSIGNÉ]{RESET} {requete}")
            return requete
        self._tache_courante = None
        self._dept_en_cours  = None
        return None

    # ═══════════════════════════════════════════════
    # Vérification périodique des deadlines
    # ═══════════════════════════════════════════════

    def _verifier_deadlines(self):
        """Vérifie toutes les 2s les deadlines — signale HARD_RT critique."""
        for requete in self._file_priorite:
            t = requete.temps_restant()
            if requete.type_rt == "HARD_RT" and t < 10:
                self.get_logger().warn(
                    f"\033[91m[HARD RT CRITIQUE]{RESET} "
                    f"{requete.nom_dept} — {t:.0f}s !")
                self._publier_alerte("HARD_RT_CRITIQUE", requete)
            elif requete.deadline_depassee():
                if requete.type_rt == "HARD_RT":
                    self._stats["deadlines_hard"] += 1
                    self.get_logger().error(
                        f"\033[91m[HARD RT MANQUÉ]{RESET} "
                        "MODE RÉCUPÉRATION ACTIVÉ")
                    self._publier_alerte("HARD_RT_MANQUE", requete)
                elif requete.type_rt == "SOFT_RT":
                    self._stats["deadlines_soft"] += 1
                    self._publier_alerte("SOFT_RT_DEGRADE", requete)

    # ═══════════════════════════════════════════════
    # Publication
    # ═══════════════════════════════════════════════

    def _publier_tache_courante(self):
        """Publie la prochaine tâche EDF sur /pharmabot/tache_courante."""
        if self._file_priorite:
            tache = self.prochaine_tache()
            if tache:
                msg      = String()
                msg.data = json.dumps({
                    "departement":  tache.departement,
                    "type_rt":      tache.type_rt,
                    "deadline_sec": tache.deadline_sec,
                    "medicament":   tache.medicament,
                    "timestamp":    tache.timestamp,
                })
                self._pub_tache.publish(msg)

    def _publier_alerte(self, type_alerte: str, requete: RequeteLivraison):
        msg      = String()
        msg.data = json.dumps({
            "type_alerte": type_alerte,
            "departement": requete.departement,
            "type_rt":     requete.type_rt,
            "consequence": requete.consequence,
            "timestamp":   time.time(),
        })
        self._pub_alerte.publish(msg)

    def _signaler_interruption_edf(self, requete_urgente: RequeteLivraison):
        """
        PHASE 1 : publie un signal d'interruption EDF.
        Reçu par mission_manager et navigation_bridge pour arrêter
        la mission courante et basculer sur l'urgence.
        """
        self._stats["overrides_edf"] += 1
        self.get_logger().warn(
            f"\033[91m{BOLD}[EDF OVERRIDE #{self._stats['overrides_edf']}]{RESET} "
            f"Interruption {self._dept_en_cours} → {requete_urgente.departement}"
        )
        msg      = String()
        msg.data = json.dumps({
            "type":              "EDF_INTERRUPTION",
            "dept_interrompu":   self._dept_en_cours,
            "dept_urgent":       requete_urgente.departement,
            "type_rt_urgent":    requete_urgente.type_rt,
            "deadline_urgent":   requete_urgente.deadline_sec,
            "medicament_urgent": requete_urgente.medicament,
            "override_num":      self._stats["overrides_edf"],
            "timestamp":         time.time(),
        })
        self._pub_interruption.publish(msg)

    # ═══════════════════════════════════════════════
    # Affichage
    # ═══════════════════════════════════════════════

    def _afficher_file(self):
        self.get_logger().info(
            f"═══ EDF File ({len(self._file_priorite)} requête(s)) "
            "— tri par deadline restante ═══"
        )
        for i, req in enumerate(sorted(self._file_priorite)):
            self.get_logger().info(f"  [{i+1}] {req}")


def main(args=None):
    rclpy.init(args=args)
    scheduler = RTScheduler()
    # PHASE 1 : plus de requêtes codées en dur ici.
    # Les requêtes arrivent de doctor_request_node.py via /pharmabot/requete
    try:
        rclpy.spin(scheduler)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
