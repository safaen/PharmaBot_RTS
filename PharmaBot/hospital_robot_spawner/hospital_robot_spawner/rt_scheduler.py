#!/usr/bin/env python3
"""
rt_scheduler.py — EDF Scheduler (Earliest Deadline First) pour PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

EDF : la tâche avec la deadline la plus proche est toujours prioritaire.
      Tri dynamique — change à chaque nouvelle requête.
"""
import heapq, time, json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

PRIORITE_HARD_RT = 1
PRIORITE_SOFT_RT = 2
PRIORITE_FIRM_RT = 3

DEPARTEMENTS_INFO = {
    "reanimation": {
        "nom": "ICU_Room", "priorite": PRIORITE_HARD_RT,
        "type_rt": "HARD_RT", "deadline_sec": 30,
        "couleur": "\033[91m", "consequence": "FATAL — alerte + mode récupération",
    },
    "urgences": {
        "nom": "Emergency_Room", "priorite": PRIORITE_SOFT_RT,
        "type_rt": "SOFT_RT", "deadline_sec": 120,
        "couleur": "\033[93m", "consequence": "Délai toléré — qualité dégradée",
    },
    "consultation": {
        "nom": "Consultation_Room", "priorite": PRIORITE_FIRM_RT,
        "type_rt": "FIRM_RT", "deadline_sec": 300,
        "couleur": "\033[92m", "consequence": "Annulé si deadline dépassée",
    },
}
RESET = "\033[0m"; BOLD = "\033[1m"


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
        # EDF : tri par deadline restante (dynamique)
        return self.temps_restant() < other.temps_restant()

    def __repr__(self):
        return (f"{self.couleur}[{self.type_rt}]{RESET} "
                f"{self.nom_dept} | {self.medicament} | "
                f"{self.temps_restant():.0f}s restantes")


class RTScheduler(Node):
    def __init__(self):
        super().__init__("rt_scheduler")
        self.get_logger().info(f"{BOLD}EDF RT Scheduler PharmaBot démarré{RESET}")
        self._file_priorite = []
        self._tache_courante = None

        self._pub_tache  = self.create_publisher(String, "/pharmabot/tache_courante", 10)
        self._pub_alerte = self.create_publisher(String, "/pharmabot/alerte_rt",      10)
        self._sub_requete = self.create_subscription(
            String, "/pharmabot/requete", self._cb_nouvelle_requete, 10)
        self._timer_check = self.create_timer(2.0, self._verifier_deadlines)
        self._timer_pub   = self.create_timer(5.0, self._publier_tache_courante)

        self._stats = {"total": 0, "hard_rt": 0, "soft_rt": 0,
                       "firm_rt": 0, "deadlines_hard": 0,
                       "deadlines_soft": 0, "annulations": 0}

    def _cb_nouvelle_requete(self, msg: String):
        try:
            data = json.loads(msg.data)
            self._ajouter_requete(RequeteLivraison(
                data.get("departement", "consultation"),
                data.get("medicament", "Médicament standard")))
        except (json.JSONDecodeError, ValueError) as e:
            self.get_logger().error(f"Requête invalide : {e}")

    def ajouter_requete(self, departement: str, medicament: str = "Médicament standard"):
        self._ajouter_requete(RequeteLivraison(departement, medicament))

    def _ajouter_requete(self, requete: RequeteLivraison):
        heapq.heappush(self._file_priorite, requete)
        self._stats["total"] += 1
        key = requete.type_rt.lower().replace("_rt", "_rt")
        if key in self._stats: self._stats[key] += 1
        self.get_logger().info(
            f"{BOLD}[EDF] Nouvelle requête{RESET} {requete} | "
            f"File : {len(self._file_priorite)}")
        self._afficher_file()

    def prochaine_tache(self):
        while self._file_priorite:
            requete = heapq.heappop(self._file_priorite)
            if requete.type_rt == "FIRM_RT" and requete.deadline_depassee():
                self._stats["annulations"] += 1
                self.get_logger().info(
                    f"{requete.couleur}[FIRM RT ANNULÉ]{RESET} {requete.nom_dept}")
                self._publier_alerte("FIRM_RT_ANNULE", requete)
                continue
            self._tache_courante = requete
            self.get_logger().info(f"{BOLD}[EDF ASSIGNÉ]{RESET} {requete}")
            return requete
        self._tache_courante = None
        return None

    def _verifier_deadlines(self):
        for requete in self._file_priorite:
            t = requete.temps_restant()
            if requete.type_rt == "HARD_RT" and t < 10:
                self.get_logger().warn(
                    f"\033[91m[HARD RT CRITIQUE]{RESET} {requete.nom_dept} — {t:.0f}s !")
                self._publier_alerte("HARD_RT_CRITIQUE", requete)
            elif requete.deadline_depassee():
                if requete.type_rt == "HARD_RT":
                    self._stats["deadlines_hard"] += 1
                    self.get_logger().error(
                        f"\033[91m[HARD RT MANQUÉ]{RESET} MODE RÉCUPÉRATION ACTIVÉ")
                    self._publier_alerte("HARD_RT_MANQUE", requete)
                elif requete.type_rt == "SOFT_RT":
                    self._stats["deadlines_soft"] += 1
                    self._publier_alerte("SOFT_RT_DEGRADE", requete)

    def _publier_tache_courante(self):
        if self._file_priorite:
            tache = self.prochaine_tache()
            if tache:
                msg = String()
                msg.data = json.dumps({
                    "departement": tache.departement,
                    "type_rt": tache.type_rt,
                    "deadline_sec": tache.deadline_sec,
                    "medicament": tache.medicament,
                    "timestamp": tache.timestamp,
                })
                self._pub_tache.publish(msg)

    def _publier_alerte(self, type_alerte: str, requete: RequeteLivraison):
        msg = String()
        msg.data = json.dumps({
            "type_alerte": type_alerte,
            "departement": requete.departement,
            "type_rt": requete.type_rt,
            "consequence": requete.consequence,
            "timestamp": time.time(),
        })
        self._pub_alerte.publish(msg)

    def _afficher_file(self):
        self.get_logger().info(
            f"═══ EDF File ({len(self._file_priorite)} requête(s)) — tri par deadline restante ═══")
        for i, req in enumerate(sorted(self._file_priorite)):
            self.get_logger().info(f"  [{i+1}] {req}")


def main(args=None):
    rclpy.init(args=args)
    scheduler = RTScheduler()
    scheduler.ajouter_requete("urgences",    "Morphine 10mg")
    scheduler.ajouter_requete("consultation","Amoxicilline 500mg")
    scheduler.ajouter_requete("reanimation", "Adrénaline 1mg — URGENCE")
    scheduler.ajouter_requete("urgences",    "Paracétamol IV 1g")
    try:
        rclpy.spin(scheduler)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
