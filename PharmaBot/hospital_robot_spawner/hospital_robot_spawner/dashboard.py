#!/usr/bin/env python3
"""
dashboard.py — Dashboard temps réel pour PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

Affiche en temps réel :
  - File de requêtes avec countdown timers
  - État courant du robot (machine à états)
  - Statut des tâches DMA
  - Alertes watchdog
"""
import json, time, threading
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

RESET = "\033[0m"; BOLD = "\033[1m"
RED   = "\033[91m"; ORANGE = "\033[93m"; GREEN = "\033[92m"
BLUE  = "\033[94m"; CYAN  = "\033[96m"

class Dashboard(Node):
    def __init__(self):
        super().__init__("pharmabot_dashboard")
        self._etat_robot     = "IDLE"
        self._mission        = None
        self._dma_status     = {}
        self._watchdog_ok    = True
        self._derniere_alerte = None
        self._nb_updates      = 0

        self.create_subscription(String, "/pharmabot/etat_robot",  self._cb_etat,     10)
        self.create_subscription(String, "/pharmabot/dma_status",  self._cb_dma,      10)
        self.create_subscription(String, "/pharmabot/alerte_rt",   self._cb_alerte,   10)
        self.create_subscription(String, "/pharmabot/watchdog",    self._cb_watchdog, 10)

        # Rafraîchissement dashboard toutes les 2s
        self.create_timer(2.0, self._afficher_dashboard)

    def _cb_etat(self, msg: String):
        try:
            data = json.loads(msg.data)
            self._etat_robot = data.get("etat", "?")
            self._mission    = data.get("mission")
        except json.JSONDecodeError: pass

    def _cb_dma(self, msg: String):
        try:
            data = json.loads(msg.data)
            self._dma_status = data.get("taches", {})
        except json.JSONDecodeError: pass

    def _cb_alerte(self, msg: String):
        try:
            self._derniere_alerte = json.loads(msg.data)
        except json.JSONDecodeError: pass

    def _cb_watchdog(self, msg: String):
        try:
            data = json.loads(msg.data)
            self._watchdog_ok = not data.get("mode_recuperation", False)
        except json.JSONDecodeError: pass

    def _afficher_dashboard(self):
        self._nb_updates += 1
        sep = "═" * 60
        print(f"\n{BOLD}{CYAN}{sep}{RESET}")
        print(f"{BOLD}{CYAN}  PharmaBot — Dashboard Temps Réel  #{self._nb_updates}{RESET}")
        print(f"{BOLD}{CYAN}{sep}{RESET}")

        # État robot
        couleur_etat = RED if "URGENCE" in self._etat_robot or "ARRET" in self._etat_robot \
                       else GREEN if self._etat_robot in ("LIVRAISON", "NAVIGATION") \
                       else ORANGE
        print(f"\n{BOLD}  État robot :{RESET} {couleur_etat}{self._etat_robot}{RESET}")

        # Mission courante
        if self._mission:
            dept     = self._mission.get("departement", "?")
            type_rt  = self._mission.get("type_rt", "?")
            deadline = self._mission.get("deadline_sec", 0)
            ts       = self._mission.get("timestamp", time.time())
            restant  = max(0, deadline - (time.time() - ts)) if deadline else 0
            couleur_mission = RED if type_rt == "HARD_RT" else \
                              ORANGE if type_rt == "SOFT_RT" else GREEN
            print(f"  {BOLD}Mission :{RESET} {couleur_mission}{dept}{RESET} | "
                  f"{type_rt} | deadline dans {restant:.0f}s")
        else:
            print(f"  {BOLD}Mission :{RESET} Aucune")

        # Tâches DMA
        if self._dma_status:
            print(f"\n  {BOLD}Tâches DMA :{RESET}")
            for k, t in sorted(self._dma_status.items(),
                               key=lambda x: x[1].get("priorite", 9)):
                etat = t.get("etat", "?")
                ok   = t.get("nb_succes", 0)
                ko   = t.get("nb_echecs", 0)
                c    = GREEN if etat == "TERMINE" else RED if etat == "ECHOUE" else ORANGE
                print(f"    P{t.get('priorite','?')} {t.get('nom','?'):<30} "
                      f"{c}{etat}{RESET} | ✓{ok} ✗{ko}")

        # Watchdog
        wdg = f"{GREEN}OK{RESET}" if self._watchdog_ok else f"{RED}MODE RÉCUPÉRATION{RESET}"
        print(f"\n  {BOLD}Watchdog :{RESET} {wdg}")

        # Dernière alerte
        if self._derniere_alerte:
            type_al = self._derniere_alerte.get("type_alerte", "?")
            dept_al = self._derniere_alerte.get("departement", "?")
            print(f"  {BOLD}Dernière alerte :{RESET} {RED}{type_al}{RESET} — {dept_al}")

        print(f"{BOLD}{CYAN}{sep}{RESET}")


def main(args=None):
    rclpy.init(args=args)
    d = Dashboard()
    try: rclpy.spin(d)
    except KeyboardInterrupt: pass
    finally: d.destroy_node(); rclpy.shutdown()

if __name__ == "__main__": main()
