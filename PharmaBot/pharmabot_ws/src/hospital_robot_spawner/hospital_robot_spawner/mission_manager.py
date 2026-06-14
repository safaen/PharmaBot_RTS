#!/usr/bin/env python3
"""
mission_manager.py — Machine à états + RMS + Interruption EDF
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

RMS : priorité inversement proportionnelle à la période.
      Tâche la plus fréquente = priorité la plus haute.

Tâches RMS :
    P1 — Sécurité obstacle    20 Hz   T=50ms
    P2 — Odométrie            10 Hz   T=100ms
    P3 — LIDAR                10 Hz   T=100ms
    P4 — Planification         1 Hz   T=1000ms
    P5 — Monitoring mission  0.5 Hz   T=2000ms

MODIFICATIONS Phase 1+2 :
    - _cb_edf_interruption : réagit au nouveau topic /pharmabot/edf_interruption
      (remplace la détection HARD_RT dans _cb_nouvelle_mission — plus robuste)
    - _cb_dma_pipeline : transitions CHARGEMENT→NAVIGATION→LIVRAISON maintenant
      correctement déclenchées (dma_tasks.py corrigé publie les bons états)
    - _cb_livraison_confirmee : reçoit la confirmation physique de delivery_detector
      et déclenche _finir_mission() → reprise automatique ou retour IDLE
    - _cb_nav_status : synchronise avec navigation_bridge (position robot)
    - Toutes les fonctionnalités RMS/EDF existantes conservées intégralement
"""
import time
import json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

ETATS_ROBOT = [
    "IDLE", "CHARGEMENT", "NAVIGATION", "EVITEMENT",
    "REPLANIFICATION", "LIVRAISON", "RETOUR_PHARMACIE",
    "URGENCE_OVERRIDE", "ARRET_URGENCE",
]

TACHES_RMS = {
    "securite_obstacle": {"nom": "Sécurité obstacle",   "periode_sec": 0.05,  "priorite": 1},
    "odometrie":         {"nom": "Odométrie",            "periode_sec": 0.1,   "priorite": 2},
    "lidar":             {"nom": "LIDAR",                "periode_sec": 0.1,   "priorite": 3},
    "planification":     {"nom": "Planification chemin", "periode_sec": 1.0,   "priorite": 4},
    "monitoring":        {"nom": "Monitoring mission",   "periode_sec": 2.0,   "priorite": 5},
}

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
ORANGE = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"


class MissionManager(Node):
    def __init__(self):
        super().__init__("mission_manager")
        self.get_logger().info(
            f"{BOLD}{CYAN}Mission Manager PharmaBot démarré{RESET}")
        self._log_tableau_rms()

        self._etat             = "IDLE"
        self._etat_precedent   = "IDLE"
        self._mission_courante    = None
        self._mission_interrompue = None
        self._pos_x = 1.0
        self._pos_y = 16.0
        self._stats_rms = {k: {"executions": 0} for k in TACHES_RMS}
        self._nb_overrides = 0
        self._nb_reprises  = 0

        # ── Publishers ──
        self._pub_etat    = self.create_publisher(String, "/pharmabot/etat_robot",  10)
        self._pub_log     = self.create_publisher(String, "/pharmabot/mission_log", 10)
        self._pub_cmd_vel = self.create_publisher(Twist,  "/demo/cmd_vel",          10)

        # ── Subscribers ──
        # Nouvelle mission du EDF scheduler
        self._sub_mission = self.create_subscription(
            String, "/pharmabot/tache_courante",
            self._cb_nouvelle_mission, 10)
        # PHASE 1 : interruption EDF explicite (nouveau topic)
        self._sub_interruption = self.create_subscription(
            String, "/pharmabot/edf_interruption",
            self._cb_edf_interruption, 10)
        # Alerte RT du scheduler (HARD_RT_MANQUE etc.)
        self._sub_alerte = self.create_subscription(
            String, "/pharmabot/alerte_rt",
            self._cb_alerte_urgence, 10)
        # PHASE 1 : états du pipeline DMA (maintenant correctement publiés)
        self._sub_dma = self.create_subscription(
            String, "/pharmabot/dma_pipeline",
            self._cb_dma_pipeline, 10)
        # PHASE 1 : confirmation physique de livraison depuis delivery_detector
        self._sub_livraison = self.create_subscription(
            String, "/pharmabot/livraison_confirmee",
            self._cb_livraison_confirmee, 10)
        # PHASE 1 : statut navigation depuis navigation_bridge
        self._sub_nav = self.create_subscription(
            String, "/pharmabot/nav_status",
            self._cb_nav_status, 10)
        # Watchdog
        self._sub_watchdog = self.create_subscription(
            String, "/pharmabot/watchdog",
            self._cb_watchdog, 10)
        # Odométrie (pour logging position)
        self._sub_odom = self.create_subscription(
            Odometry, "/demo/odom",
            self._cb_odom, 1)

        # ── Timers RMS ──
        self.create_timer(
            TACHES_RMS["securite_obstacle"]["periode_sec"],
            lambda: self._tache_rms("securite_obstacle"))
        self.create_timer(
            TACHES_RMS["odometrie"]["periode_sec"],
            lambda: self._tache_rms("odometrie"))
        self.create_timer(
            TACHES_RMS["lidar"]["periode_sec"],
            lambda: self._tache_rms("lidar"))
        self.create_timer(
            TACHES_RMS["planification"]["periode_sec"],
            lambda: self._tache_rms("planification"))
        self.create_timer(
            TACHES_RMS["monitoring"]["periode_sec"],
            self._monitorer_mission)
        self.create_timer(1.0, self._publier_etat)

    # ═══════════════════════════════════════════════
    # Gestion des états
    # ═══════════════════════════════════════════════

    def _changer_etat(self, nouvel_etat: str):
        if nouvel_etat not in ETATS_ROBOT:
            return
        self._etat_precedent = self._etat
        self._etat           = nouvel_etat
        self.get_logger().info(
            f"[ÉTAT] {self._etat_precedent} → {self._etat}")
        self._publier_etat()

    def _publier_etat(self):
        msg      = String()
        msg.data = json.dumps({
            "etat":          self._etat,
            "etat_precedent": self._etat_precedent,
            "mission":       self._mission_courante,
            "pos_x":         round(self._pos_x, 2),
            "pos_y":         round(self._pos_y, 2),
            "timestamp":     time.time(),
        })
        self._pub_etat.publish(msg)

    # ═══════════════════════════════════════════════
    # Callbacks principales
    # ═══════════════════════════════════════════════

    def _cb_nouvelle_mission(self, msg: String):
        """Reçoit une mission du EDF scheduler et décide de la démarrer."""
        try:
            mission = json.loads(msg.data)
            type_rt = mission.get("type_rt", "")
            dept    = mission.get("departement", "?")
            self.get_logger().info(
                f"[MISSION] {dept} | {type_rt} | "
                f"{mission.get('medicament')}")

            # Si robot IDLE → démarrer directement
            if self._etat == "IDLE":
                self._demarrer_mission(mission)
            # Si même département déjà en cours → ignorer doublon
            elif (self._mission_courante
                  and self._mission_courante.get("departement") == dept):
                pass
            # Sinon noter pour éventuelle interruption via _cb_edf_interruption
        except json.JSONDecodeError as e:
            self.get_logger().error(f"Mission invalide : {e}")

    def _cb_edf_interruption(self, msg: String):
        """
        PHASE 1 : reçoit un signal d'interruption EDF explicite depuis rt_scheduler.
        Ce callback est plus fiable que l'ancienne détection HARD_RT dans
        _cb_nouvelle_mission car il arrive APRÈS l'ajout dans la file EDF.
        """
        try:
            data           = json.loads(msg.data)
            dept_urgent    = data.get("dept_urgent")
            dept_interrompu = data.get("dept_interrompu")
            medicament     = data.get("medicament_urgent", "Médicament urgent")
            deadline       = data.get("deadline_urgent", 30)
            type_rt        = data.get("type_rt_urgent",  "HARD_RT")
            override_num   = data.get("override_num",    0)

            self.get_logger().warn(
                f"{RED}{BOLD}[EDF OVERRIDE #{override_num}]{RESET} "
                f"Interruption {dept_interrompu} → {dept_urgent}")

            if self._etat not in ("ARRET_URGENCE", "URGENCE_OVERRIDE"):
                mission_urgente = {
                    "departement":  dept_urgent,
                    "type_rt":      type_rt,
                    "deadline_sec": deadline,
                    "medicament":   medicament,
                    "timestamp":    time.time(),
                }
                self._interrompre_mission(mission_urgente)
        except json.JSONDecodeError:
            pass

    def _cb_alerte_urgence(self, msg: String):
        """Réagit aux alertes HARD_RT du scheduler."""
        try:
            alerte = json.loads(msg.data)
            if alerte.get("type_alerte") in ("HARD_RT_CRITIQUE", "HARD_RT_MANQUE"):
                self.get_logger().error(
                    f"[URGENCE] {alerte['type_alerte']} — "
                    f"{alerte.get('departement')}")
                if self._etat not in ("ARRET_URGENCE", "URGENCE_OVERRIDE"):
                    self._changer_etat("URGENCE_OVERRIDE")
        except json.JSONDecodeError:
            pass

    def _cb_dma_pipeline(self, msg: String):
        """
        PHASE 1 : transitions d'état déclenchées par dma_tasks.py
        (maintenant correctement publié à chaque étape du pipeline).
        """
        try:
            data     = json.loads(msg.data)
            etat_dma = data.get("etat", "")

            if etat_dma in ("VALIDATION_PHARMACIEN", "CONFIRMATION_MEDICAMENT"):
                if self._etat == "IDLE":
                    self._changer_etat("CHARGEMENT")

            elif etat_dma == "NAVIGATION":
                if self._etat == "CHARGEMENT":
                    self._changer_etat("NAVIGATION")

            elif etat_dma == "LIVRAISON":
                if self._etat == "NAVIGATION":
                    self._changer_etat("LIVRAISON")

            elif etat_dma == "IDLE":
                # Pipeline terminé selon DMA — mais on attend
                # la confirmation physique de delivery_detector
                pass

            elif etat_dma == "ARRET_URGENCE":
                self._arreter_urgence()

        except json.JSONDecodeError:
            pass

    def _cb_livraison_confirmee(self, msg: String):
        """
        PHASE 1 : confirmation physique de livraison depuis delivery_detector.
        C'est ce callback qui déclenche _finir_mission() de manière fiable.
        """
        try:
            data = json.loads(msg.data)
            dept = data.get("departement")
            ok   = data.get("deadline_ok", True)
            t    = data.get("temps_livraison", 0)
            num  = data.get("livraison_num", 0)

            if self._mission_courante and \
                    self._mission_courante.get("departement") == dept:
                c = GREEN if ok else ORANGE
                self.get_logger().info(
                    f"{c}{BOLD}[LIVRAISON #{num} CONFIRMÉE]{RESET} "
                    f"{dept} | {t:.0f}s | "
                    f"{'✓ deadline OK' if ok else '✗ deadline dépassée'}")
                self._changer_etat("RETOUR_PHARMACIE")
                self._finir_mission()
        except json.JSONDecodeError:
            pass

    def _cb_nav_status(self, msg: String):
        """Synchronise l'état EVITEMENT/REPLANIFICATION depuis le bridge."""
        try:
            data  = json.loads(msg.data)
            phase = data.get("phase", "")
            if phase == "NAVIGATION" and self._etat == "CHARGEMENT":
                self._changer_etat("NAVIGATION")
        except json.JSONDecodeError:
            pass

    def _cb_watchdog(self, msg: String):
        """Réagit aux commandes du watchdog."""
        try:
            data = json.loads(msg.data)
            if data.get("type") == "RECUPERATION":
                self._arreter_robot()
                if self._etat != "ARRET_URGENCE":
                    self._changer_etat("ARRET_URGENCE")
            elif data.get("type") == "REPRISE":
                if self._etat == "ARRET_URGENCE":
                    self._changer_etat("IDLE")
        except json.JSONDecodeError:
            pass

    def _cb_odom(self, msg: Odometry):
        """Met à jour la position pour le monitoring."""
        self._pos_x = msg.pose.pose.position.x
        self._pos_y = msg.pose.pose.position.y

    # ═══════════════════════════════════════════════
    # Gestion des missions
    # ═══════════════════════════════════════════════

    def _demarrer_mission(self, mission: dict):
        self._mission_courante = mission
        self._changer_etat("CHARGEMENT")
        dept     = mission.get("departement", "?")
        deadline = mission.get("deadline_sec", 0)
        type_rt  = mission.get("type_rt", "?")
        self.get_logger().info(
            f"{CYAN}[MISSION DÉMARRÉE]{RESET} → {dept} | "
            f"{type_rt} | D={deadline}s | "
            f"{mission.get('medicament', '?')}")

    def _interrompre_mission(self, mission_urgente: dict):
        """
        Sauvegarde la mission courante, arrête le robot,
        bascule en URGENCE_OVERRIDE et démarre la mission urgente.
        """
        self._nb_overrides += 1
        if self._mission_courante:
            self.get_logger().warn(
                f"{RED}[EDF OVERRIDE #{self._nb_overrides}]{RESET} "
                f"Sauvegarde : {self._mission_courante.get('departement')} "
                f"→ Urgence : {mission_urgente.get('departement')}")
            self._mission_interrompue = self._mission_courante

        self._arreter_robot()
        self._changer_etat("URGENCE_OVERRIDE")
        self._demarrer_mission(mission_urgente)

    def _finir_mission(self):
        """
        Termine la mission courante.
        Si une mission avait été interrompue, la reprendre automatiquement.
        """
        dept = self._mission_courante.get("departement", "?") \
               if self._mission_courante else "?"
        self.get_logger().info(
            f"{GREEN}[MISSION TERMINÉE]{RESET} : {dept}")

        if self._mission_interrompue:
            self._nb_reprises += 1
            self.get_logger().info(
                f"{CYAN}[EDF REPRISE #{self._nb_reprises}]{RESET} "
                f"→ {self._mission_interrompue.get('departement')}")
            m = self._mission_interrompue
            self._mission_interrompue = None
            self._mission_courante    = None
            self._demarrer_mission(m)
        else:
            self._mission_courante = None
            self._changer_etat("IDLE")

    def _arreter_urgence(self):
        self._arreter_robot()
        self._changer_etat("ARRET_URGENCE")
        self.get_logger().error(
            f"{RED}{BOLD}[ARRET URGENCE]{RESET} Robot stoppé")

    def _arreter_robot(self):
        cmd = Twist()
        cmd.linear.x  = 0.0
        cmd.angular.z = 0.0
        self._pub_cmd_vel.publish(cmd)

    # ═══════════════════════════════════════════════
    # Tâches RMS
    # ═══════════════════════════════════════════════

    def _tache_rms(self, id_tache: str):
        """Exécute une tâche périodique RMS (comptage + logique sécurité P1)."""
        self._stats_rms[id_tache]["executions"] += 1
        # P1 sécurité obstacle : en production → vérification laser
        # P2 odométrie         : en production → mise à jour position
        # P3 LIDAR             : en production → traitement nuage de points
        # P4 planification     : en production → mise à jour du chemin

    def _monitorer_mission(self):
        """Monitoring RMS P5 (0.5 Hz) — alerte si deadline proche."""
        if not self._mission_courante:
            return
        dept     = self._mission_courante.get("departement", "?")
        deadline = self._mission_courante.get("deadline_sec", 0)
        ts       = self._mission_courante.get("timestamp", time.time())
        restant  = deadline - (time.time() - ts) if deadline else 0

        if 0 < restant < 10:
            self.get_logger().warn(
                f"[MONITORING] {dept} — deadline dans {restant:.0f}s !")
        elif restant <= 0 and deadline > 0:
            self.get_logger().error(
                f"[MONITORING] {dept} — DEADLINE DÉPASSÉE")

    # ═══════════════════════════════════════════════
    # Affichage tableau RMS
    # ═══════════════════════════════════════════════

    def _log_tableau_rms(self):
        self.get_logger().info(
            "Tableau RMS — Rate Monotonic Scheduling")
        self.get_logger().info(
            f"{'Priorité':<10}{'Tâche':<28}{'Fréquence':<12}{'Période'}")
        self.get_logger().info("-" * 60)
        for k, info in sorted(TACHES_RMS.items(),
                               key=lambda x: x[1]["priorite"]):
            hz = 1.0 / info["periode_sec"]
            self.get_logger().info(
                f"P{info['priorite']:<9}{info['nom']:<28}"
                f"{hz:.0f} Hz{'':8}T={info['periode_sec']*1000:.0f}ms")


def main(args=None):
    rclpy.init(args=args)
    m = MissionManager()
    try:
        rclpy.spin(m)
    except KeyboardInterrupt:
        pass
    finally:
        m.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
