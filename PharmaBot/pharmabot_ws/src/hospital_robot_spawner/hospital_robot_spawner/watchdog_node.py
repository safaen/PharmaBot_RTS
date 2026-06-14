#!/usr/bin/env python3
"""
watchdog_node.py — Watchdog temps réel pour PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

Surveille les deadlines Hard RT et déclenche la récupération si manquées.
Connexion au cours : illustre la tolérance aux fautes en systèmes critiques
                    (Apollo 11, Ariane 5).
"""
import time, json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist

class WatchdogNode(Node):
    def __init__(self):
        super().__init__("pharmabot_watchdog")
        self.get_logger().info("Watchdog PharmaBot démarré")
        self._mode_recuperation = False
        self._nb_alertes_hard   = 0
        self._nb_recuperations  = 0

        self._pub_cmd_vel   = self.create_publisher(Twist,  "/demo/cmd_vel",           10)
        self._pub_watchdog  = self.create_publisher(String, "/pharmabot/watchdog",      10)
        self._sub_alerte_rt = self.create_subscription(
            String, "/pharmabot/alerte_rt", self._cb_alerte, 10)
        self._sub_alerte_dma = self.create_subscription(
            String, "/pharmabot/dma_alerte", self._cb_alerte_dma, 10)
        self._sub_etat = self.create_subscription(
            String, "/pharmabot/etat_robot", self._cb_etat_robot, 10)

        self._timer_heartbeat = self.create_timer(5.0, self._heartbeat)

    def _cb_alerte(self, msg: String):
        try:
            alerte = json.loads(msg.data)
            type_al = alerte.get("type_alerte", "")
            if type_al == "HARD_RT_MANQUE":
                self._nb_alertes_hard += 1
                self.get_logger().error(
                    f"[WATCHDOG] HARD RT MANQUÉ — {alerte.get('departement')} | "
                    f"Conséquence : {alerte.get('consequence')}")
                self._activer_recuperation("HARD_RT_MANQUE", alerte)
            elif type_al == "HARD_RT_CRITIQUE":
                self.get_logger().warn(
                    f"[WATCHDOG] HARD RT CRITIQUE — {alerte.get('departement')} — "
                    "moins de 10s !")
        except json.JSONDecodeError: pass

    def _cb_alerte_dma(self, msg: String):
        try:
            alerte = json.loads(msg.data)
            if alerte.get("priorite") == 1:  # P1 = sécurité mission
                self.get_logger().error(
                    f"[WATCHDOG] DMA P1 ÉCHOUÉ — {alerte.get('nom')} — "
                    "ARRÊT D'URGENCE")
                self._arreter_robot()
        except json.JSONDecodeError: pass

    def _cb_etat_robot(self, msg: String):
        try:
            data = json.loads(msg.data)
            if data.get("etat") == "ARRET_URGENCE":
                self.get_logger().error("[WATCHDOG] Robot en ARRET_URGENCE détecté")
        except json.JSONDecodeError: pass

    def _activer_recuperation(self, raison: str, contexte: dict):
        if self._mode_recuperation: return
        self._mode_recuperation = True
        self._nb_recuperations += 1
        self.get_logger().error(
            f"[WATCHDOG] MODE RÉCUPÉRATION ACTIVÉ | raison={raison} | "
            f"#{self._nb_recuperations}")
        self._arreter_robot()
        msg = String()
        msg.data = json.dumps({"type": "RECUPERATION", "raison": raison,
                               "contexte": contexte, "timestamp": time.time()})
        self._pub_watchdog.publish(msg)
        # Après 5s, tenter reprise automatique
        self.create_timer(5.0, self._reprise_automatique)

    def _reprise_automatique(self):
        if self._mode_recuperation:
            self._mode_recuperation = False
            self.get_logger().info("[WATCHDOG] Reprise automatique — mode récupération levé")
            msg = String()
            msg.data = json.dumps({"type": "REPRISE", "timestamp": time.time()})
            self._pub_watchdog.publish(msg)

    def _arreter_robot(self):
        msg = Twist(); msg.linear.x = 0.0; msg.angular.z = 0.0
        self._pub_cmd_vel.publish(msg)
        self.get_logger().warn("[WATCHDOG] Commande arrêt envoyée au robot")

    def _heartbeat(self):
        msg = String()
        msg.data = json.dumps({
            "type": "HEARTBEAT", "mode_recuperation": self._mode_recuperation,
            "nb_alertes_hard": self._nb_alertes_hard,
            "nb_recuperations": self._nb_recuperations,
            "timestamp": time.time()})
        self._pub_watchdog.publish(msg)
        if not self._mode_recuperation:
            self.get_logger().info(
                f"[WATCHDOG] ♥ OK | alertes_hard={self._nb_alertes_hard} | "
                f"récupérations={self._nb_recuperations}")


def main(args=None):
    rclpy.init(args=args)
    w = WatchdogNode()
    try: rclpy.spin(w)
    except KeyboardInterrupt: pass
    finally: w.destroy_node(); rclpy.shutdown()

if __name__ == "__main__": main()
