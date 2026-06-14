#!/usr/bin/env python3
"""
navigation_bridge.py — Pont EDF Scheduler ↔ Robot Navigation
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

NOUVEAU (Phase 1) : Maillon manquant critique.
Ce nœud est le pont entre le scheduler (qui décide) et le robot (qui bouge).

Avant ce nœud : le EDF scheduler prenait des décisions mais le robot ne
les recevait jamais. Le robot tournait en boucle sans but.

Après ce nœud : chaque décision EDF → commande de navigation vers la bonne salle.

Fonctionnement :
    1. Souscrit à /pharmabot/tache_courante  (décision EDF)
    2. Traduit le département en coordonnées (x, y)
    3. Calcule la direction vers la cible depuis la position actuelle
    4. Publie des commandes /demo/cmd_vel (vitesse linéaire + angulaire)
    5. Souscrit à /demo/odom pour connaître la position actuelle
    6. Publie /pharmabot/navigation_goal pour que delivery_detector sache où on va
    7. Publie /pharmabot/nav_status pour le dashboard

Navigation utilisée : contrôleur proportionnel simple (compatible avec l'agent RL
existant — on prend la main quand le scheduler change de cible, on la rend ensuite).
"""
import json
import math
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry

RESET = "\033[0m"
BOLD  = "\033[1m"
CYAN  = "\033[96m"
RED   = "\033[91m"
ORANGE= "\033[93m"
GREEN = "\033[92m"
YELLOW= "\033[93m"

# Coordonnées exactes de chaque salle (correspondant à pharmabot_env.py)
SALLES = {
    "pharmacie":   {"nom": "Pharmacy_Room",     "x":  1.0, "y":  16.0},
    "reanimation": {"nom": "ICU_Room",           "x": 11.0, "y":   5.5},
    "urgences":    {"nom": "Emergency_Room",     "x": -5.0, "y":  -6.6},
    "consultation":{"nom": "Consultation_Room",  "x": -2.0, "y": -27.0},
}

# Rayon d'arrivée : distance à la cible sous laquelle on considère la livraison faite
RAYON_ARRIVEE    = 1.5   # mètres
# Rayon de chargement : distance à la pharmacie pour considérer le chargement fait
RAYON_CHARGEMENT = 1.5   # mètres

# Gains du contrôleur proportionnel
KP_LINEAIRE  = 0.4   # gain vitesse linéaire
KP_ANGULAIRE = 1.2   # gain vitesse angulaire
VIT_MAX_LIN  = 0.6   # m/s max
VIT_MAX_ANG  = 1.0   # rad/s max


class NavigationBridge(Node):
    """
    Pont entre le EDF Scheduler et la navigation physique du robot.
    Transforme une décision de scheduling en commandes de mouvement.
    """

    def __init__(self):
        super().__init__("navigation_bridge")
        self.get_logger().info(
            f"{BOLD}{CYAN}Navigation Bridge démarré — Pont EDF↔Robot{RESET}")

        # ── État interne ──
        self._mission_courante   = None   # dict de la mission active
        self._departement_cible  = None   # clé du département cible
        self._phase              = "IDLE" # IDLE / RETOUR_PHARMACIE / CHARGEMENT / NAVIGATION / ARRIVE
        self._pos_x              = 1.0
        self._pos_y              = 16.0
        self._orientation        = 0.0
        self._chargement_en_cours = False
        self._dernier_dept_publie = None  # évite de republier le même goal

        # ── Publishers ──
        self._pub_cmd_vel   = self.create_publisher(Twist,  "/demo/cmd_vel",              10)
        self._pub_goal      = self.create_publisher(String, "/pharmabot/navigation_goal",  10)
        self._pub_nav_status= self.create_publisher(String, "/pharmabot/nav_status",       10)

        # ── Subscribers ──
        self._sub_mission = self.create_subscription(
            String, "/pharmabot/tache_courante", self._cb_mission, 10)
        self._sub_odom = self.create_subscription(
            Odometry, "/demo/odom", self._cb_odom, 1)
        self._sub_etat = self.create_subscription(
            String, "/pharmabot/etat_robot", self._cb_etat_robot, 10)
        self._sub_watchdog = self.create_subscription(
            String, "/pharmabot/watchdog", self._cb_watchdog, 10)

        # ── Timers ──
        # Boucle de navigation à 10 Hz
        self._timer_nav     = self.create_timer(0.1,  self._boucle_navigation)
        # Publication du statut à 1 Hz
        self._timer_status  = self.create_timer(1.0,  self._publier_status)

        self._urgence_active   = False
        self._arret_watchdog   = False

        self.get_logger().info(
            f"{GREEN}Navigation Bridge prêt — en attente de missions EDF{RESET}")

    # ═══════════════════════════════════════════════
    # Callbacks
    # ═══════════════════════════════════════════════

    def _cb_mission(self, msg: String):
        """Reçoit une nouvelle mission depuis le EDF scheduler."""
        try:
            mission = json.loads(msg.data)
            dept    = mission.get("departement")
            type_rt = mission.get("type_rt", "")

            if dept not in SALLES or dept == "pharmacie":
                return

            # Si même mission déjà active → ignorer
            if self._departement_cible == dept and self._phase == "NAVIGATION":
                return

            # Interruption EDF : nouvelle mission HARD_RT pendant navigation
            if self._phase == "NAVIGATION" and type_rt == "HARD_RT" \
                    and dept != self._departement_cible:
                self.get_logger().warn(
                    f"{RED}{BOLD}[NAV BRIDGE] EDF OVERRIDE : "
                    f"{self._departement_cible} → {dept}{RESET}")

            self._mission_courante  = mission
            self._departement_cible = dept
            self._phase             = "RETOUR_PHARMACIE"
            self._chargement_en_cours = False

            salle = SALLES[dept]
            self.get_logger().info(
                f"{CYAN}[NAV BRIDGE] Nouvelle cible : {salle['nom']} "
                f"({salle['x']:.1f}, {salle['y']:.1f}) | {type_rt}{RESET}")

            self._publier_goal(dept)

        except (json.JSONDecodeError, KeyError) as e:
            self.get_logger().error(f"[NAV BRIDGE] Mission invalide : {e}")

    def _cb_odom(self, msg: Odometry):
        """Met à jour la position du robot depuis l'odométrie."""
        self._pos_x = msg.pose.pose.position.x
        self._pos_y = msg.pose.pose.position.y
        # Extraire l'orientation (yaw) depuis le quaternion
        qz = msg.pose.pose.orientation.z
        qw = msg.pose.pose.orientation.w
        self._orientation = 2.0 * math.atan2(qz, qw)

    def _cb_etat_robot(self, msg: String):
        """Synchronise avec la machine à états du mission_manager."""
        try:
            data = json.loads(msg.data)
            etat = data.get("etat", "")
            if etat == "ARRET_URGENCE":
                self._phase = "IDLE"
                self._arreter_robot()
        except json.JSONDecodeError:
            pass

    def _cb_watchdog(self, msg: String):
        """Arrête la navigation si le watchdog passe en mode récupération."""
        try:
            data = json.loads(msg.data)
            if data.get("type") == "RECUPERATION":
                self._arret_watchdog = True
                self._arreter_robot()
                self.get_logger().error(
                    "[NAV BRIDGE] Arrêt watchdog — navigation suspendue")
            elif data.get("type") == "REPRISE":
                self._arret_watchdog = False
                self.get_logger().info(
                    "[NAV BRIDGE] Reprise watchdog — navigation autorisée")
        except json.JSONDecodeError:
            pass

    # ═══════════════════════════════════════════════
    # Boucle de navigation principale
    # ═══════════════════════════════════════════════

    def _boucle_navigation(self):
        """Appelée à 10 Hz. Calcule et publie la commande de vitesse."""

        if self._arret_watchdog or self._phase == "IDLE":
            return
        if self._departement_cible is None:
            return

        # Phase 1 : retour à la pharmacie pour charger
        if self._phase == "RETOUR_PHARMACIE":
            self._naviguer_vers("pharmacie", prochaine_phase="CHARGEMENT")

        # Phase 2 : chargement à la pharmacie (simulation 3 secondes)
        elif self._phase == "CHARGEMENT":
            if not self._chargement_en_cours:
                self._chargement_en_cours = True
                self._chargement_debut    = time.time()
                self._arreter_robot()
                self.get_logger().info(
                    f"{ORANGE}[NAV BRIDGE] Chargement médicament à la pharmacie...{RESET}")

                # Notifie le DMA pipeline → déclenche VALIDATION_PHARMACIEN
                msg = String()
                msg.data = json.dumps({
                    "etat": "VALIDATION_PHARMACIEN",
                    "ancien": "RETOUR_PHARMACIE",
                    "timestamp": time.time(),
                    "mission": self._mission_courante,
                })
                self._pub_goal.publish(msg)  # réutilisé pour déclencher DMA

            elif time.time() - self._chargement_debut >= 3.0:
                self._chargement_en_cours = False
                self._phase = "NAVIGATION"
                self.get_logger().info(
                    f"{GREEN}[NAV BRIDGE] Chargement terminé — "
                    f"départ vers {SALLES[self._departement_cible]['nom']}{RESET}")

                # Notifie le DMA pipeline → NAVIGATION
                self._publier_changement_pipeline("NAVIGATION")

        # Phase 3 : navigation vers la salle cible
        elif self._phase == "NAVIGATION":
            self._naviguer_vers(self._departement_cible, prochaine_phase="ARRIVE")

        # Phase 4 : arrivée — livraison confirmée
        elif self._phase == "ARRIVE":
            self._arreter_robot()
            dept = self._departement_cible
            self.get_logger().info(
                f"{GREEN}{BOLD}[NAV BRIDGE] Arrivé à {SALLES[dept]['nom']} — "
                f"livraison en cours...{RESET}")
            self._phase = "IDLE"
            self._departement_cible = None

            # Notifie livraison → déclenche delivery_detector
            pub_msg = String()
            pub_msg.data = json.dumps({
                "type": "ARRIVE_DESTINATION",
                "departement": dept,
                "timestamp": time.time(),
                "mission": self._mission_courante,
            })
            self._pub_nav_status.publish(pub_msg)

            # Notifie le DMA pipeline → LIVRAISON
            self._publier_changement_pipeline("LIVRAISON")

    # ═══════════════════════════════════════════════
    # Contrôleur de navigation proportionnel
    # ═══════════════════════════════════════════════

    def _naviguer_vers(self, departement: str, prochaine_phase: str):
        """
        Calcule et publie la commande de vitesse vers un département.
        Contrôleur proportionnel : tourne d'abord, puis avance.
        """
        salle  = SALLES[departement]
        cible_x = salle["x"]
        cible_y = salle["y"]

        dx = cible_x - self._pos_x
        dy = cible_y - self._pos_y
        distance = math.sqrt(dx * dx + dy * dy)

        # Arrivée détectée
        if distance < RAYON_ARRIVEE:
            self._arreter_robot()
            self._phase = prochaine_phase
            self.get_logger().info(
                f"{GREEN}[NAV BRIDGE] Atteint {salle['nom']} "
                f"(distance={distance:.2f}m){RESET}")
            return

        # Angle vers la cible
        angle_cible  = math.atan2(dy, dx)
        erreur_angle = angle_cible - self._orientation

        # Normaliser l'erreur d'angle entre -π et +π
        while erreur_angle >  math.pi: erreur_angle -= 2 * math.pi
        while erreur_angle < -math.pi: erreur_angle += 2 * math.pi

        cmd = Twist()

        # Si l'angle est trop grand, tourner d'abord avant d'avancer
        if abs(erreur_angle) > 0.3:
            cmd.linear.x  = 0.1  # avance lentement pendant la rotation
            cmd.angular.z = max(-VIT_MAX_ANG,
                                min(VIT_MAX_ANG, KP_ANGULAIRE * erreur_angle))
        else:
            # Avancer proportionnellement à la distance, limité
            vit_lin = min(VIT_MAX_LIN, KP_LINEAIRE * distance)
            cmd.linear.x  = vit_lin
            cmd.angular.z = max(-VIT_MAX_ANG * 0.5,
                                min(VIT_MAX_ANG * 0.5, KP_ANGULAIRE * erreur_angle))

        self._pub_cmd_vel.publish(cmd)

    # ═══════════════════════════════════════════════
    # Utilitaires
    # ═══════════════════════════════════════════════

    def _arreter_robot(self):
        """Publie une commande d'arrêt."""
        cmd = Twist()
        cmd.linear.x  = 0.0
        cmd.angular.z = 0.0
        self._pub_cmd_vel.publish(cmd)

    def _publier_goal(self, departement: str):
        """Publie le goal courant pour delivery_detector et dashboard."""
        if departement == self._dernier_dept_publie:
            return
        self._dernier_dept_publie = departement
        salle = SALLES[departement]
        msg   = String()
        msg.data = json.dumps({
            "departement": departement,
            "nom":         salle["nom"],
            "x":           salle["x"],
            "y":           salle["y"],
            "timestamp":   time.time(),
            "mission":     self._mission_courante,
        })
        self._pub_goal.publish(msg)

    def _publier_changement_pipeline(self, nouvel_etat: str):
        """Notifie le DMA pipeline d'un changement d'état."""
        msg = String()
        msg.data = json.dumps({
            "etat": nouvel_etat,
            "ancien": self._phase,
            "timestamp": time.time(),
            "mission": self._mission_courante,
        })
        # Publié sur dma_pipeline pour que mission_manager change d'état
        self.create_publisher(
            String, "/pharmabot/dma_pipeline", 10).publish(msg)

    def _publier_status(self):
        """Publie le statut de navigation pour le dashboard."""
        msg = String()
        msg.data = json.dumps({
            "type":              "NAV_STATUS",
            "phase":             self._phase,
            "departement_cible": self._departement_cible,
            "pos_x":             round(self._pos_x, 2),
            "pos_y":             round(self._pos_y, 2),
            "arret_watchdog":    self._arret_watchdog,
            "timestamp":         time.time(),
        })
        self._pub_nav_status.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = NavigationBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
