#!/usr/bin/env python3
"""
pharmacist_node.py — Nœud Pharmacien PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

NOUVEAU Phase 2 : Simule le comportement du pharmacien dans le pipeline
de livraison. Ferme la boucle entre la requête médecin et le chargement
physique du robot.

Pipeline DMA côté pharmacien :
    1. Reçoit la requête médecin (/pharmabot/requete)
    2. Valide le médicament (vérif stock + délai réaliste 2-4s)
    3. Prépare le médicament (délai 1-2s)
    4. Publie l'autorisation de chargement (/pharmabot/pharmacist_ok)
    5. Met à jour le stock (/pharmabot/stock_status)

Stock de médicaments simulé (s'épuise et se réapprovisionne).
Compatibilité DMA : toutes les opérations ont des deadlines mesurées.
"""
import json
import random
import time
import threading
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
ORANGE = "\033[93m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"

# Stock initial de médicaments
STOCK_INITIAL = {
    "Morphine 10mg IV":        5,
    "Morphine 10mg":           8,
    "Adrénaline 1mg":          3,
    "Adrénaline 1mg — URGENCE": 3,
    "Noradrénaline 4mg":       4,
    "Atropine 0.5mg":          6,
    "Furosémide 20mg":         10,
    "Insuline Rapide":         7,
    "Propofol 200mg":          4,
    "Paracétamol IV 1g":       15,
    "Paracétamol 1g":          20,
    "Ibuprofène 400mg":        12,
    "Ondansétron 4mg":         8,
    "Métoclopramide 10mg":     10,
    "Aspirine 500mg":          15,
    "Lorazépam 2mg":           5,
    "Amoxicilline 500mg":      12,
    "Oméprazole 20mg":         10,
    "Médicament standard":     50,
}

# Délais de validation par priorité (secondes)
DELAIS_VALIDATION = {
    "HARD_RT": (1.5, 2.5),
    "SOFT_RT": (2.0, 3.5),
    "FIRM_RT": (2.5, 4.0),
}

# Seuil de réapprovisionnement automatique
SEUIL_REAPPROVISIONNEMENT = 2
QUANTITE_REAPPROVISIONNEMENT = 10


class PharmacistNode(Node):
    """
    Nœud simulant le pharmacien hospitalier.
    Valide les demandes, prépare les médicaments et autorise le chargement.
    """

    def __init__(self):
        super().__init__("pharmacist_node")
        self.get_logger().info(
            f"{BOLD}{BLUE}Pharmacist Node démarré — Pharmacie prête{RESET}")

        # ── Stock ──
        self._stock   = dict(STOCK_INITIAL)
        self._lock    = threading.Lock()
        self._stats   = {
            "validations_ok":      0,
            "validations_echec":   0,
            "reapprovisionnements": 0,
            "temps_moyen_validation": 0.0,
        }

        # ── Publishers ──
        self._pub_ok     = self.create_publisher(
            String, "/pharmabot/pharmacist_ok",  10)
        self._pub_refus  = self.create_publisher(
            String, "/pharmabot/pharmacist_nok", 10)
        self._pub_stock  = self.create_publisher(
            String, "/pharmabot/stock_status",   10)
        self._pub_log    = self.create_publisher(
            String, "/pharmabot/pharmacist_log", 10)

        # ── Subscribers ──
        # Reçoit les requêtes du doctor_request_node via le scheduler
        self._sub_requete = self.create_subscription(
            String, "/pharmabot/requete",
            self._cb_requete, 10)
        # Reçoit les confirmations de livraison pour noter le stock consommé
        self._sub_livraison = self.create_subscription(
            String, "/pharmabot/livraison_confirmee",
            self._cb_livraison_confirmee, 10)

        # ── Timers ──
        self._timer_stock = self.create_timer(15.0, self._publier_stock)
        self._timer_reapro = self.create_timer(30.0, self._verifier_reapprovisionnement)

        self.get_logger().info(
            f"{BLUE}Stock initial chargé : "
            f"{sum(self._stock.values())} unités{RESET}")
        self._afficher_stock()

    # ═══════════════════════════════════════════════
    # Traitement des requêtes
    # ═══════════════════════════════════════════════

    def _cb_requete(self, msg: String):
        """Reçoit une requête et lance la validation en thread séparé."""
        try:
            data = json.loads(msg.data)
            threading.Thread(
                target=self._traiter_requete,
                args=(data,),
                daemon=True,
            ).start()
        except json.JSONDecodeError as e:
            self.get_logger().error(f"[PHARMACIEN] Requête invalide : {e}")

    def _traiter_requete(self, data: dict):
        """
        Pipeline complet de validation pharmacien.
        Exécuté dans un thread séparé pour ne pas bloquer ROS2.
        """
        dept       = data.get("departement", "?")
        medicament = data.get("medicament",  "Médicament standard")
        type_rt    = data.get("type_rt",     "FIRM_RT")
        # Si type_rt non fourni dans la requête, déduire du département
        if not type_rt or type_rt == "FIRM_RT":
            rt_map = {
                "reanimation":  "HARD_RT",
                "urgences":     "SOFT_RT",
                "consultation": "FIRM_RT",
            }
            type_rt = rt_map.get(dept, "FIRM_RT")

        debut_validation = time.time()

        self.get_logger().info(
            f"{BLUE}[PHARMACIEN] Requête reçue : {dept} | "
            f"{medicament} | {type_rt}{RESET}")

        # ── Étape 1 : délai de validation réaliste ──
        min_d, max_d = DELAIS_VALIDATION.get(type_rt, (2.0, 4.0))
        delai        = random.uniform(min_d, max_d)
        self.get_logger().info(
            f"[PHARMACIEN] Validation en cours... ({delai:.1f}s)")
        time.sleep(delai)

        # ── Étape 2 : vérification du stock ──
        with self._lock:
            # Normaliser le nom du médicament
            med_key = medicament
            if med_key not in self._stock:
                # Cherche une correspondance partielle
                for k in self._stock:
                    if medicament.lower() in k.lower() or k.lower() in medicament.lower():
                        med_key = k
                        break
                else:
                    med_key = "Médicament standard"

            stock_dispo = self._stock.get(med_key, 0)
            temps_validation = time.time() - debut_validation

        if stock_dispo <= 0:
            # Stock épuisé
            self._stats["validations_echec"] += 1
            self.get_logger().warn(
                f"{ORANGE}[PHARMACIEN] Stock épuisé : {med_key} — "
                f"réapprovisionnement nécessaire{RESET}")
            # Publier refus
            msg_nok      = String()
            msg_nok.data = json.dumps({
                "type":      "PHARMACIST_NOK",
                "raison":    "STOCK_EPUISE",
                "medicament": medicament,
                "departement": dept,
                "timestamp": time.time(),
            })
            self._pub_refus.publish(msg_nok)
            # Réapprovisionner immédiatement pour les cas critiques HARD_RT
            if type_rt == "HARD_RT":
                self._reapprovisionner_urgence(med_key)
                # Re-tenter après réappro
                time.sleep(2.0)
                with self._lock:
                    self._stock[med_key] -= 1
                self._autoriser_chargement(
                    dept, medicament, med_key, type_rt, temps_validation)
            return

        # ── Étape 3 : décrémenter stock et préparer médicament ──
        with self._lock:
            self._stock[med_key] -= 1

        # Délai préparation (mise sous emballage stérile, étiquetage)
        prep_time = random.uniform(0.5, 1.5)
        self.get_logger().info(
            f"[PHARMACIEN] Préparation {med_key} ({prep_time:.1f}s)...")
        time.sleep(prep_time)

        # Mise à jour stats
        n = self._stats["validations_ok"] + 1
        old = self._stats["temps_moyen_validation"]
        self._stats["temps_moyen_validation"] = \
            (old * (n - 1) + temps_validation) / n
        self._stats["validations_ok"] = n

        self._autoriser_chargement(
            dept, medicament, med_key, type_rt, temps_validation)

    def _autoriser_chargement(self, dept: str, medicament_demande: str,
                               medicament_fourni: str, type_rt: str,
                               temps_validation: float):
        """Publie l'autorisation de chargement."""
        self.get_logger().info(
            f"{GREEN}{BOLD}[PHARMACIEN] ✓ AUTORISÉ{RESET} "
            f"{dept} | {medicament_fourni} | {temps_validation:.1f}s")

        msg      = String()
        msg.data = json.dumps({
            "type":               "PHARMACIST_OK",
            "departement":        dept,
            "medicament_demande": medicament_demande,
            "medicament_fourni":  medicament_fourni,
            "type_rt":            type_rt,
            "temps_validation":   round(temps_validation, 2),
            "stock_restant":      self._stock.get(medicament_fourni, 0),
            "timestamp":          time.time(),
        })
        self._pub_ok.publish(msg)

        # Log pour dashboard
        log      = String()
        log.data = json.dumps({
            "type":    "PHARMACIST_LOG",
            "action":  "VALIDATION_OK",
            "dept":    dept,
            "med":     medicament_fourni,
            "stats":   self._stats,
        })
        self._pub_log.publish(log)

    # ═══════════════════════════════════════════════
    # Suivi des livraisons
    # ═══════════════════════════════════════════════

    def _cb_livraison_confirmee(self, msg: String):
        """Enregistre les livraisons pour les statistiques du pharmacien."""
        try:
            data = json.loads(msg.data)
            dept = data.get("departement", "?")
            med  = data.get("medicament",  "?")
            self.get_logger().info(
                f"{GREEN}[PHARMACIEN] Livraison confirmée : "
                f"{dept} | {med}{RESET}")
        except json.JSONDecodeError:
            pass

    # ═══════════════════════════════════════════════
    # Gestion du stock
    # ═══════════════════════════════════════════════

    def _verifier_reapprovisionnement(self):
        """Vérifie le stock toutes les 30s et réapprovisionne si nécessaire."""
        with self._lock:
            epuises = [
                med for med, qt in self._stock.items()
                if qt <= SEUIL_REAPPROVISIONNEMENT
            ]
        for med in epuises:
            self._reapprovisionner(med)

    def _reapprovisionner(self, medicament: str):
        """Réapprovisionne un médicament en stock bas."""
        with self._lock:
            self._stock[medicament] += QUANTITE_REAPPROVISIONNEMENT
            self._stats["reapprovisionnements"] += 1
        self.get_logger().info(
            f"{CYAN}[PHARMACIEN] Réapprovisionnement : "
            f"{medicament} +{QUANTITE_REAPPROVISIONNEMENT} "
            f"(total={self._stock[medicament]}){RESET}")

    def _reapprovisionner_urgence(self, medicament: str):
        """Réapprovisionnement d'urgence immédiat pour HARD_RT."""
        with self._lock:
            self._stock[medicament] += QUANTITE_REAPPROVISIONNEMENT
            self._stats["reapprovisionnements"] += 1
        self.get_logger().warn(
            f"{ORANGE}[PHARMACIEN] RÉAPPROVISIONNEMENT URGENCE : "
            f"{medicament} +{QUANTITE_REAPPROVISIONNEMENT}{RESET}")

    def _publier_stock(self):
        """Publie l'état du stock pour le dashboard."""
        with self._lock:
            stock_copy = dict(self._stock)

        msg      = String()
        msg.data = json.dumps({
            "type":      "STOCK_STATUS",
            "stock":     stock_copy,
            "total":     sum(stock_copy.values()),
            "stats":     self._stats,
            "timestamp": time.time(),
        })
        self._pub_stock.publish(msg)

    def _afficher_stock(self):
        """Affiche le stock initial dans les logs."""
        self.get_logger().info(
            f"{'Médicament':<40} {'Stock':>6}")
        self.get_logger().info("-" * 48)
        for med, qt in sorted(self._stock.items()):
            barre = "█" * min(qt, 20)
            self.get_logger().info(
                f"  {med:<38} {qt:>4}  {barre}")


def main(args=None):
    rclpy.init(args=args)
    node = PharmacistNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
