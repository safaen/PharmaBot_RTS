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
"""
import time, json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist

ETATS_ROBOT = ["IDLE","CHARGEMENT","NAVIGATION","EVITEMENT",
               "REPLANIFICATION","LIVRAISON","RETOUR_PHARMACIE",
               "URGENCE_OVERRIDE","ARRET_URGENCE"]

TACHES_RMS = {
    "securite_obstacle": {"nom": "Sécurité obstacle",   "periode_sec": 0.05,  "priorite": 1},
    "odometrie":         {"nom": "Odométrie",            "periode_sec": 0.1,   "priorite": 2},
    "lidar":             {"nom": "LIDAR",                "periode_sec": 0.1,   "priorite": 3},
    "planification":     {"nom": "Planification chemin", "periode_sec": 1.0,   "priorite": 4},
    "monitoring":        {"nom": "Monitoring mission",   "periode_sec": 2.0,   "priorite": 5},
}


class MissionManager(Node):
    def __init__(self):
        super().__init__("mission_manager")
        self.get_logger().info("Mission Manager PharmaBot démarré")
        self._log_tableau_rms()

        self._etat = "IDLE"; self._etat_precedent = "IDLE"
        self._mission_courante = None; self._mission_interrompue = None
        self._stats_rms = {k: {"executions": 0} for k in TACHES_RMS}

        self._pub_etat    = self.create_publisher(String, "/pharmabot/etat_robot",  10)
        self._pub_log     = self.create_publisher(String, "/pharmabot/mission_log", 10)
        self._pub_cmd_vel = self.create_publisher(Twist,  "/demo/cmd_vel",          10)

        self._sub_mission = self.create_subscription(
            String, "/pharmabot/tache_courante", self._cb_nouvelle_mission, 10)
        self._sub_alerte  = self.create_subscription(
            String, "/pharmabot/alerte_rt", self._cb_alerte_urgence, 10)
        self._sub_dma     = self.create_subscription(
            String, "/pharmabot/dma_pipeline", self._cb_dma_pipeline, 10)

        # Timers RMS — un par tâche périodique
        self.create_timer(TACHES_RMS["securite_obstacle"]["periode_sec"],
                          lambda: self._tache_rms("securite_obstacle"))
        self.create_timer(TACHES_RMS["odometrie"]["periode_sec"],
                          lambda: self._tache_rms("odometrie"))
        self.create_timer(TACHES_RMS["lidar"]["periode_sec"],
                          lambda: self._tache_rms("lidar"))
        self.create_timer(TACHES_RMS["planification"]["periode_sec"],
                          lambda: self._tache_rms("planification"))
        self.create_timer(TACHES_RMS["monitoring"]["periode_sec"],
                          self._monitorer_mission)
        self.create_timer(1.0, self._publier_etat)

    def _changer_etat(self, nouvel_etat: str):
        if nouvel_etat not in ETATS_ROBOT: return
        self._etat_precedent = self._etat
        self._etat = nouvel_etat
        self.get_logger().info(f"[ÉTAT] {self._etat_precedent} → {self._etat}")
        self._publier_etat()

    def _publier_etat(self):
        msg = String()
        msg.data = json.dumps({"etat": self._etat, "etat_precedent": self._etat_precedent,
                               "mission": self._mission_courante, "timestamp": time.time()})
        self._pub_etat.publish(msg)

    def _cb_nouvelle_mission(self, msg: String):
        try:
            mission = json.loads(msg.data)
            type_rt = mission.get("type_rt", "")
            self.get_logger().info(
                f"[MISSION] {mission.get('departement')} | {type_rt} | {mission.get('medicament')}")
            if self._mission_courante and type_rt == "HARD_RT":
                self._interrompre_mission(mission)
            else:
                self._demarrer_mission(mission)
        except json.JSONDecodeError as e:
            self.get_logger().error(f"Mission invalide : {e}")

    def _cb_alerte_urgence(self, msg: String):
        try:
            alerte = json.loads(msg.data)
            if alerte.get("type_alerte") in ("HARD_RT_CRITIQUE", "HARD_RT_MANQUE"):
                self.get_logger().error(
                    f"[URGENCE] {alerte['type_alerte']} — {alerte.get('departement')}")
                if self._etat not in ("ARRET_URGENCE", "URGENCE_OVERRIDE"):
                    self._changer_etat("URGENCE_OVERRIDE")
        except json.JSONDecodeError: pass

    def _cb_dma_pipeline(self, msg: String):
        try:
            data = json.loads(msg.data)
            etat_dma = data.get("etat", "")
            if etat_dma == "NAVIGATION" and self._etat == "CHARGEMENT":
                self._changer_etat("NAVIGATION")
            elif etat_dma == "LIVRAISON" and self._etat == "NAVIGATION":
                self._changer_etat("LIVRAISON")
            elif etat_dma == "IDLE" and self._etat == "LIVRAISON":
                self._changer_etat("RETOUR_PHARMACIE")
                self._finir_mission()
            elif etat_dma == "ARRET_URGENCE":
                self._arreter_urgence()
        except json.JSONDecodeError: pass

    def _demarrer_mission(self, mission: dict):
        self._mission_courante = mission
        self._changer_etat("CHARGEMENT")
        self.get_logger().info(
            f"[MISSION] Démarrage → {mission.get('departement')} | "
            f"D={mission.get('deadline_sec')}s")

    def _interrompre_mission(self, mission_urgente: dict):
        self.get_logger().warn(
            f"[EDF OVERRIDE] {self._mission_courante.get('departement')} "
            f"→ URGENCE {mission_urgente.get('departement')}")
        self._mission_interrompue = self._mission_courante
        self._arreter_robot()
        self._changer_etat("URGENCE_OVERRIDE")
        self._demarrer_mission(mission_urgente)

    def _finir_mission(self):
        self.get_logger().info(
            f"[MISSION] Terminée : {self._mission_courante.get('departement')}")
        if self._mission_interrompue:
            self.get_logger().info(
                f"[EDF REPRISE] → {self._mission_interrompue.get('departement')}")
            m = self._mission_interrompue
            self._mission_interrompue = None
            self._demarrer_mission(m)
        else:
            self._mission_courante = None
            self._changer_etat("IDLE")

    def _arreter_urgence(self):
        self._arreter_robot()
        self._changer_etat("ARRET_URGENCE")
        self.get_logger().error("[ARRET URGENCE] Robot arrêté")

    def _arreter_robot(self):
        msg = Twist(); msg.linear.x = 0.0; msg.angular.z = 0.0
        self._pub_cmd_vel.publish(msg)

    def _tache_rms(self, id_tache: str):
        self._stats_rms[id_tache]["executions"] += 1
        # P1 — vérif sécurité, P2 — odométrie, P3 — LIDAR, P4 — planification
        # En production : appels aux topics ROS2 correspondants

    def _monitorer_mission(self):
        if not self._mission_courante: return
        dept     = self._mission_courante.get("departement", "?")
        deadline = self._mission_courante.get("deadline_sec", 0)
        ts       = self._mission_courante.get("timestamp", time.time())
        restant  = deadline - (time.time() - ts) if deadline else 0
        if 0 < restant < 10:
            self.get_logger().warn(f"[MONITORING] {dept} — deadline dans {restant:.0f}s !")
        elif restant <= 0 and deadline > 0:
            self.get_logger().error(f"[MONITORING] {dept} — DEADLINE DÉPASSÉE")

    def _log_tableau_rms(self):
        self.get_logger().info("Tableau RMS — Rate Monotonic Scheduling")
        self.get_logger().info(f"{'Priorité':<10}{'Tâche':<28}{'Fréquence':<12}{'Période'}")
        self.get_logger().info("-" * 60)
        for k, info in sorted(TACHES_RMS.items(), key=lambda x: x[1]["priorite"]):
            hz = 1.0 / info["periode_sec"]
            self.get_logger().info(
                f"P{info['priorite']:<9}{info['nom']:<28}"
                f"{hz:.0f} Hz{'':<8}T={info['periode_sec']*1000:.0f}ms")


def main(args=None):
    rclpy.init(args=args)
    m = MissionManager()
    try: rclpy.spin(m)
    except KeyboardInterrupt: pass
    finally: m.destroy_node(); rclpy.shutdown()

if __name__ == "__main__": main()
