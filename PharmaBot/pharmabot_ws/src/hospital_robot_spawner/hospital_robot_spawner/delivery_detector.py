#!/usr/bin/env python3
"""
delivery_detector.py — Détecteur automatique de livraison
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

NOUVEAU (Phase 1) : Ce nœud ferme la boucle du pipeline de livraison.
Sans lui, une livraison ne se terminait jamais — le robot arrivait mais
aucun système ne le détectait.

Fonctionnement :
    1. Souscrit à /demo/odom pour la position GPS du robot
    2. Souscrit à /pharmabot/navigation_goal pour connaître la destination
    3. Compare en continu : distance(robot, cible) < seuil d'arrivée ?
    4. Si oui → publie sur /pharmabot/livraison_confirmee
    5. Publie aussi les stats de livraison sur /pharmabot/delivery_stats

Ce nœud est indépendant du navigation_bridge pour robustesse :
même si le bridge rate la détection, le detector la capte quand même.
"""
import json
import math
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from nav_msgs.msg import Odometry

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
RED    = "\033[91m"
ORANGE = "\033[93m"

# Coordonnées des salles (identique à navigation_bridge.py)
SALLES = {
    "pharmacie":   {"nom": "Pharmacy_Room",     "x":  1.0, "y":  16.0},
    "reanimation": {"nom": "ICU_Room",           "x": 11.0, "y":   5.5},
    "urgences":    {"nom": "Emergency_Room",     "x": -5.0, "y":  -6.6},
    "consultation":{"nom": "Consultation_Room",  "x": -2.0, "y": -27.0},
}

RAYON_LIVRAISON  = 1.8   # mètres — légèrement plus grand que le bridge
DELAI_LIVRAISON  = 2.0   # secondes de présence avant confirmation
COOLDOWN_LIVRAISON = 10.0  # secondes avant d'accepter une 2e livraison au même endroit


class DeliveryDetector(Node):
    """
    Surveille en continu la position du robot et confirme les livraisons
    quand le robot reste suffisamment longtemps près de la destination.
    """

    def __init__(self):
        super().__init__("delivery_detector")
        self.get_logger().info(
            f"{BOLD}{CYAN}Delivery Detector démarré — surveillance position{RESET}")

        # ── État interne ──
        self._pos_x          = 1.0
        self._pos_y          = 16.0
        self._goal_courant   = None   # dict du goal actuel depuis navigation_bridge
        self._dept_cible     = None
        self._mission_active = None

        # Pour éviter les faux positifs : on exige une présence continue
        self._arrive_depuis  = None   # timestamp d'arrivée dans la zone
        self._derniere_livraison = {}  # dept → timestamp dernière livraison

        self._stats = {
            "livraisons_total":       0,
            "livraisons_reanimation": 0,
            "livraisons_urgences":    0,
            "livraisons_consultation": 0,
            "temps_livraison_moyen":  0.0,
            "deadlines_respectees":   0,
            "deadlines_manquees":     0,
        }
        self._temps_debut_mission = None

        # ── Publishers ──
        self._pub_livraison = self.create_publisher(
            String, "/pharmabot/livraison_confirmee", 10)
        self._pub_stats     = self.create_publisher(
            String, "/pharmabot/delivery_stats",      10)

        # ── Subscribers ──
        self._sub_odom = self.create_subscription(
            Odometry, "/demo/odom", self._cb_odom, 1)
        self._sub_goal = self.create_subscription(
            String, "/pharmabot/navigation_goal", self._cb_goal, 10)
        self._sub_nav_status = self.create_subscription(
            String, "/pharmabot/nav_status", self._cb_nav_status, 10)
        self._sub_mission = self.create_subscription(
            String, "/pharmabot/tache_courante", self._cb_mission, 10)

        # ── Timers ──
        self._timer_detection = self.create_timer(0.5,  self._verifier_arrivee)
        self._timer_stats     = self.create_timer(10.0, self._publier_stats)

        self.get_logger().info(
            f"{GREEN}Delivery Detector prêt — rayon={RAYON_LIVRAISON}m "
            f"délai={DELAI_LIVRAISON}s{RESET}")

    # ═══════════════════════════════════════════════
    # Callbacks
    # ═══════════════════════════════════════════════

    def _cb_odom(self, msg: Odometry):
        """Met à jour la position du robot."""
        self._pos_x = msg.pose.pose.position.x
        self._pos_y = msg.pose.pose.position.y

    def _cb_goal(self, msg: String):
        """Reçoit le goal depuis navigation_bridge."""
        try:
            data = json.loads(msg.data)
            dept = data.get("departement")
            if dept and dept in SALLES and dept != "pharmacie":
                self._goal_courant  = data
                self._dept_cible    = dept
                self._arrive_depuis = None  # reset détection à chaque nouveau goal
                self.get_logger().info(
                    f"[DETECTOR] Nouvelle cible : {SALLES[dept]['nom']} "
                    f"({SALLES[dept]['x']:.1f}, {SALLES[dept]['y']:.1f})")
        except json.JSONDecodeError:
            pass

    def _cb_nav_status(self, msg: String):
        """Reçoit les notifications d'arrivée depuis navigation_bridge."""
        try:
            data = json.loads(msg.data)
            if data.get("type") == "ARRIVE_DESTINATION":
                dept = data.get("departement")
                if dept and dept == self._dept_cible:
                    # Le bridge a déjà détecté l'arrivée — on confirme aussi
                    self._confirmer_livraison(dept, data.get("mission"))
        except json.JSONDecodeError:
            pass

    def _cb_mission(self, msg: String):
        """Enregistre le début d'une mission pour calculer le temps de livraison."""
        try:
            data = json.loads(msg.data)
            if data.get("departement") != "pharmacie":
                self._mission_active    = data
                self._temps_debut_mission = time.time()
        except json.JSONDecodeError:
            pass

    # ═══════════════════════════════════════════════
    # Détection d'arrivée
    # ═══════════════════════════════════════════════

    def _verifier_arrivee(self):
        """Vérifie toutes les 0.5s si le robot est arrivé à destination."""
        if self._dept_cible is None:
            return

        salle    = SALLES[self._dept_cible]
        dx       = salle["x"] - self._pos_x
        dy       = salle["y"] - self._pos_y
        distance = math.sqrt(dx * dx + dy * dy)

        if distance < RAYON_LIVRAISON:
            # Robot dans la zone de livraison
            if self._arrive_depuis is None:
                self._arrive_depuis = time.time()
                self.get_logger().info(
                    f"[DETECTOR] Robot dans zone {salle['nom']} "
                    f"(d={distance:.2f}m) — attente {DELAI_LIVRAISON}s...")

            elif time.time() - self._arrive_depuis >= DELAI_LIVRAISON:
                # Présence suffisamment longue → confirmer livraison
                # Vérifier le cooldown (évite doublons)
                derniere = self._derniere_livraison.get(self._dept_cible, 0)
                if time.time() - derniere >= COOLDOWN_LIVRAISON:
                    self._confirmer_livraison(
                        self._dept_cible, self._mission_active)
        else:
            # Robot sorti de la zone — reset timer de présence
            if self._arrive_depuis is not None:
                self._arrive_depuis = None

    def _confirmer_livraison(self, departement: str, mission: dict):
        """Publie la confirmation de livraison et met à jour les stats."""
        salle = SALLES[departement]

        # Calculer le temps de livraison et vérifier la deadline
        temps_livraison = 0.0
        deadline_ok     = True
        if self._temps_debut_mission:
            temps_livraison = time.time() - self._temps_debut_mission
            if mission:
                deadline = mission.get("deadline_sec", 9999)
                deadline_ok = temps_livraison <= deadline

        # Mettre à jour le cooldown
        self._derniere_livraison[departement] = time.time()

        # Mettre à jour les stats
        self._stats["livraisons_total"] += 1
        key = f"livraisons_{departement}"
        if key in self._stats:
            self._stats[key] += 1
        if deadline_ok:
            self._stats["deadlines_respectees"] += 1
        else:
            self._stats["deadlines_manquees"] += 1

        # Mise à jour de la moyenne
        n = self._stats["livraisons_total"]
        old_moy = self._stats["temps_livraison_moyen"]
        self._stats["temps_livraison_moyen"] = \
            (old_moy * (n - 1) + temps_livraison) / n

        # Couleur selon succès deadline
        couleur = GREEN if deadline_ok else ORANGE
        deadline_str = f"{temps_livraison:.0f}s / {mission.get('deadline_sec', '?')}s" \
                       if mission else f"{temps_livraison:.0f}s"

        self.get_logger().info(
            f"{couleur}{BOLD}[LIVRAISON CONFIRMÉE #{self._stats['livraisons_total']}] "
            f"{salle['nom']} | {deadline_str} | "
            f"{'✓ DEADLINE OK' if deadline_ok else '✗ DEADLINE DÉPASSÉE'}{RESET}")

        # Publication de la confirmation
        msg = String()
        msg.data = json.dumps({
            "type":             "LIVRAISON_CONFIRMEE",
            "departement":      departement,
            "nom_salle":        salle["nom"],
            "medicament":       mission.get("medicament", "?") if mission else "?",
            "type_rt":          mission.get("type_rt", "?")    if mission else "?",
            "temps_livraison":  round(temps_livraison, 1),
            "deadline_sec":     mission.get("deadline_sec", 0) if mission else 0,
            "deadline_ok":      deadline_ok,
            "livraison_num":    self._stats["livraisons_total"],
            "timestamp":        time.time(),
        })
        self._pub_livraison.publish(msg)

        # Reset pour la prochaine mission
        self._dept_cible    = None
        self._goal_courant  = None
        self._arrive_depuis = None
        self._temps_debut_mission = None

    # ═══════════════════════════════════════════════
    # Stats
    # ═══════════════════════════════════════════════

    def _publier_stats(self):
        """Publie les statistiques de livraison toutes les 10s."""
        msg = String()
        msg.data = json.dumps({
            "type":      "DELIVERY_STATS",
            "stats":     self._stats,
            "timestamp": time.time(),
        })
        self._pub_stats.publish(msg)

        n     = self._stats["livraisons_total"]
        ok    = self._stats["deadlines_respectees"]
        rate  = (ok / n * 100) if n > 0 else 0
        self.get_logger().info(
            f"[DETECTOR] Stats : {n} livraisons | "
            f"{rate:.0f}% deadlines OK | "
            f"moy={self._stats['temps_livraison_moyen']:.0f}s")


def main(args=None):
    rclpy.init(args=args)
    node = DeliveryDetector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
