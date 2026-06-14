#!/usr/bin/env python3
"""
doctor_request_node.py — Générateur dynamique de requêtes médecin
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

NOUVEAU (Phase 1) : Ce nœud génère des requêtes de livraison de médicaments
de manière continue et aléatoire pendant toute la simulation, simulant les
demandes réelles des médecins dans chaque département.

Comportement :
    - Injecte une première salve de requêtes au démarrage (scénario visible)
    - Génère ensuite des requêtes aléatoires toutes les 30-90 secondes
    - Peut injecter une URGENCE HARD_RT à tout moment via /pharmabot/injecter_urgence
    - Publie sur /pharmabot/requete (consommé par rt_scheduler.py)

Scénario démonstration visible (démarrage) :
    1. Consultation  (FIRM_RT  300s) → robot démarre vers consultation
    2. Urgences      (SOFT_RT  120s) → robot continue ou s'adapte
    3. Réanimation   (HARD_RT   30s) → robot INTERROMPT et va en réanimation (EDF override)
"""
import json
import random
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

RESET = "\033[0m"
BOLD  = "\033[1m"
CYAN  = "\033[96m"
RED   = "\033[91m"
ORANGE= "\033[93m"
GREEN = "\033[92m"

# Catalogue de médicaments par département
MEDICAMENTS = {
    "reanimation":  [
        "Adrénaline 1mg",
        "Morphine 10mg IV",
        "Noradrénaline 4mg",
        "Atropine 0.5mg",
        "Furosémide 20mg",
        "Insuline Rapide",
        "Propofol 200mg",
    ],
    "urgences": [
        "Morphine 10mg",
        "Paracétamol IV 1g",
        "Ibuprofène 400mg",
        "Ondansétron 4mg",
        "Métoclopramide 10mg",
        "Aspirine 500mg",
        "Lorazépam 2mg",
    ],
    "consultation": [
        "Amoxicilline 500mg",
        "Paracétamol 1g",
        "Ibuprofène 400mg",
        "Oméprazole 20mg",
        "Métformine 500mg",
        "Amlodipine 5mg",
        "Atorvastatine 20mg",
    ],
}

# Intervalles de génération aléatoire par département (min_sec, max_sec)
INTERVALLES = {
    "reanimation":  (45,  90),
    "urgences":     (60, 120),
    "consultation": (90, 180),
}


class DoctorRequestNode(Node):
    """
    Nœud simulant les médecins des 3 départements.
    Génère des requêtes aléatoires continues et publie le scénario
    de démonstration EDF au démarrage.
    """

    def __init__(self):
        super().__init__("doctor_request_node")
        self.get_logger().info(f"{BOLD}{CYAN}Docteur Request Node démarré{RESET}")

        self._pub_requete = self.create_publisher(
            String, "/pharmabot/requete", 10)
        self._pub_log = self.create_publisher(
            String, "/pharmabot/doctor_log", 10)

        # Souscription pour injection manuelle d'urgence depuis le terminal
        self._sub_urgence = self.create_subscription(
            String, "/pharmabot/injecter_urgence",
            self._cb_injecter_urgence, 10)

        self._nb_requetes = 0
        self._prochaine_requete = {dept: 0.0 for dept in INTERVALLES}

        # Scénario de démo — injecté avec délais pour que le comportement
        # EDF soit clairement visible dès le démarrage
        self._scenario_demarre = False
        self.create_timer(2.0, self._lancer_scenario_demo)

        # Timer principal de génération continue (vérifie toutes les 5s)
        self.create_timer(5.0, self._generer_requetes_periodiques)

        self.get_logger().info(
            f"{CYAN}Scénario démo EDF en attente (démarre dans 2s)...{RESET}")

    # ─────────────────────────────────────────────────
    # Scénario démonstration au démarrage
    # ─────────────────────────────────────────────────

    def _lancer_scenario_demo(self):
        """
        Injecte la séquence de démonstration une seule fois au démarrage.
        Ordre calculé pour montrer l'override EDF de manière visible :
          t+0s  : consultation (FIRM RT 300s)  → robot part vers consultation
          t+8s  : urgences     (SOFT RT 120s)  → scheduler réévalue la file
          t+18s : reanimation  (HARD RT  30s)  → EDF OVERRIDE immédiat
        """
        if self._scenario_demarre:
            return
        self._scenario_demarre = True

        self.get_logger().info(
            f"{BOLD}═══ SCÉNARIO DÉMONSTRATION EDF ═══{RESET}")
        self.get_logger().info(
            "t+0s  → Consultation  (FIRM RT  300s)")
        self.get_logger().info(
            "t+8s  → Urgences      (SOFT RT  120s)")
        self.get_logger().info(
            "t+18s → Réanimation   (HARD RT   30s) ← EDF OVERRIDE attendu")

        # Requête 1 : consultation immédiate
        self._publier_requete("consultation", "Amoxicilline 500mg", source="DEMO")

        # Requête 2 : urgences après 8s
        self.create_timer(8.0,  lambda: self._publier_requete(
            "urgences",     "Morphine 10mg",          source="DEMO"))

        # Requête 3 : réanimation après 18s → déclenche l'override EDF
        self.create_timer(18.0, lambda: self._publier_requete(
            "reanimation",  "Adrénaline 1mg — URGENCE", source="DEMO"))

        # Initialiser les prochaines générations aléatoires
        # après la fin du scénario (à partir de t+60s)
        for dept in INTERVALLES:
            min_i, max_i = INTERVALLES[dept]
            self._prochaine_requete[dept] = time.time() + 60.0 + random.uniform(0, 30)

    # ─────────────────────────────────────────────────
    # Génération continue aléatoire
    # ─────────────────────────────────────────────────

    def _generer_requetes_periodiques(self):
        """Vérifie si un département doit envoyer une nouvelle requête."""
        now = time.time()
        for dept, prochain in self._prochaine_requete.items():
            if now >= prochain:
                medicament = random.choice(MEDICAMENTS[dept])
                self._publier_requete(dept, medicament, source="AUTO")
                min_i, max_i = INTERVALLES[dept]
                self._prochaine_requete[dept] = now + random.uniform(min_i, max_i)

    # ─────────────────────────────────────────────────
    # Injection manuelle d'urgence (via terminal)
    # ─────────────────────────────────────────────────

    def _cb_injecter_urgence(self, msg: String):
        """
        Permet d'injecter une urgence manuellement depuis le terminal :
            ros2 topic pub --once /pharmabot/injecter_urgence \
              std_msgs/String '{data: "reanimation"}'
        """
        try:
            dept = msg.data.strip().lower()
            if dept not in MEDICAMENTS:
                self.get_logger().error(
                    f"[INJECT] Département inconnu : {dept}")
                return
            medicament = random.choice(MEDICAMENTS[dept])
            self.get_logger().warn(
                f"{RED}{BOLD}[INJECT MANUEL] URGENCE {dept.upper()} — {medicament}{RESET}")
            self._publier_requete(dept, medicament, source="MANUEL")
        except Exception as e:
            self.get_logger().error(f"[INJECT] Erreur : {e}")

    # ─────────────────────────────────────────────────
    # Publication d'une requête
    # ─────────────────────────────────────────────────

    def _publier_requete(self, departement: str, medicament: str,
                         source: str = "AUTO"):
        """Publie une requête formatée sur /pharmabot/requete."""
        self._nb_requetes += 1
        couleurs = {
            "reanimation":  RED,
            "urgences":     ORANGE,
            "consultation": GREEN,
        }
        c = couleurs.get(departement, CYAN)

        payload = {
            "departement": departement,
            "medicament":  medicament,
            "source":      source,
            "timestamp":   time.time(),
            "requete_id":  self._nb_requetes,
        }
        msg = String()
        msg.data = json.dumps(payload)
        self._pub_requete.publish(msg)

        self.get_logger().info(
            f"{c}{BOLD}[DOCTEUR #{self._nb_requetes}]{RESET} "
            f"dept={departement} | {medicament} | source={source}")

        # Log structuré pour le dashboard
        log_msg = String()
        log_msg.data = json.dumps({
            "type": "DOCTOR_REQUEST",
            "payload": payload,
        })
        self._pub_log.publish(log_msg)


def main(args=None):
    rclpy.init(args=args)
    node = DoctorRequestNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
