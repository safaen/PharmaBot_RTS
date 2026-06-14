#!/usr/bin/env python3
"""
dashboard.py — Dashboard temps réel PharmaBot (terminal)
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

MODIFICATIONS Phase 1+2 :
    - Ajout affichage navigation (phase, cible, position robot)
    - Ajout statut pharmacien (validation en cours, stock)
    - Ajout statistiques livraisons (delivery_detector stats)
    - Ajout logs docteurs (requêtes en cours)
    - Ajout pipeline DMA en temps réel
    - Correction du format _cb_livraison : nouveau format delivery_detector
    - Toutes les fonctionnalités existantes conservées
"""
import json
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
ORANGE = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
PURPLE = "\033[95m"

DEPT_COULEURS = {
    "reanimation":  RED,
    "urgences":     ORANGE,
    "consultation": GREEN,
    None:           CYAN,
}


class Dashboard(Node):
    def __init__(self):
        super().__init__("pharmabot_dashboard")
        self.get_logger().info("Dashboard PharmaBot démarré")

        # ── État collecté ──
        self._etat_robot       = "IDLE"
        self._mission          = None
        self._dma_status       = {}
        self._dma_pipeline     = "IDLE"
        self._watchdog_ok      = True
        self._derniere_alerte  = None
        self._nb_updates       = 0
        self._livraisons       = []          # historique des 5 dernières
        self._delivery_stats   = {}          # stats depuis delivery_detector
        self._nav_status       = {}          # depuis navigation_bridge
        self._pharmacist_log   = {}          # depuis pharmacist_node
        self._stock_total      = 0
        self._doctor_requests  = []          # dernières requêtes médecin
        self._pos_x            = 1.0
        self._pos_y            = 16.0
        self._nb_overrides     = 0

        # ── Subscriptions (existantes) ──
        self.create_subscription(
            String, "/pharmabot/etat_robot",         self._cb_etat,         10)
        self.create_subscription(
            String, "/pharmabot/dma_status",          self._cb_dma,          10)
        self.create_subscription(
            String, "/pharmabot/alerte_rt",           self._cb_alerte,       10)
        self.create_subscription(
            String, "/pharmabot/watchdog",            self._cb_watchdog,     10)
        self.create_subscription(
            String, "/pharmabot/livraison_confirmee", self._cb_livraison,    10)

        # ── Subscriptions NOUVELLES Phase 1+2 ──
        self.create_subscription(
            String, "/pharmabot/nav_status",          self._cb_nav,          10)
        self.create_subscription(
            String, "/pharmabot/dma_pipeline",        self._cb_pipeline,     10)
        self.create_subscription(
            String, "/pharmabot/pharmacist_log",      self._cb_pharmacist,   10)
        self.create_subscription(
            String, "/pharmabot/stock_status",        self._cb_stock,        10)
        self.create_subscription(
            String, "/pharmabot/doctor_log",          self._cb_doctor,       10)
        self.create_subscription(
            String, "/pharmabot/delivery_stats",      self._cb_delivery_stats, 10)
        self.create_subscription(
            String, "/pharmabot/edf_interruption",    self._cb_interruption, 10)

        self.create_timer(2.0, self._afficher_dashboard)

    # ═══════════════════════════════════════════════
    # Callbacks existants (conservés + adaptés)
    # ═══════════════════════════════════════════════

    def _cb_etat(self, msg):
        try:
            d = json.loads(msg.data)
            self._etat_robot = d.get("etat", "?")
            self._mission    = d.get("mission")
            self._pos_x      = d.get("pos_x", self._pos_x)
            self._pos_y      = d.get("pos_y", self._pos_y)
        except Exception:
            pass

    def _cb_dma(self, msg):
        try:
            self._dma_status = json.loads(msg.data).get("taches", {})
        except Exception:
            pass

    def _cb_alerte(self, msg):
        try:
            self._derniere_alerte = json.loads(msg.data)
        except Exception:
            pass

    def _cb_watchdog(self, msg):
        try:
            self._watchdog_ok = not json.loads(msg.data).get(
                "mode_recuperation", False)
        except Exception:
            pass

    def _cb_livraison(self, msg):
        """CORRECTION Phase 1 : format adapté au delivery_detector."""
        try:
            d = json.loads(msg.data)
            # Nouveau format : delivery_detector publie plus de champs
            livraison = {
                "departement": d.get("departement", "?"),
                "type_rt":     d.get("type_rt",     "?"),
                "medicament":  d.get("medicament",  "?"),
                "temps":       d.get("temps_livraison", 0),
                "deadline_ok": d.get("deadline_ok", True),
                "num":         d.get("livraison_num", 0),
            }
            self._livraisons.append(livraison)
            if len(self._livraisons) > 5:
                self._livraisons.pop(0)
        except Exception:
            pass

    # ═══════════════════════════════════════════════
    # Nouveaux callbacks Phase 1+2
    # ═══════════════════════════════════════════════

    def _cb_nav(self, msg):
        try:
            self._nav_status = json.loads(msg.data)
            self._pos_x = self._nav_status.get("pos_x", self._pos_x)
            self._pos_y = self._nav_status.get("pos_y", self._pos_y)
        except Exception:
            pass

    def _cb_pipeline(self, msg):
        try:
            d = json.loads(msg.data)
            self._dma_pipeline = d.get("etat", "IDLE")
        except Exception:
            pass

    def _cb_pharmacist(self, msg):
        try:
            self._pharmacist_log = json.loads(msg.data)
        except Exception:
            pass

    def _cb_stock(self, msg):
        try:
            d = json.loads(msg.data)
            self._stock_total = d.get("total", 0)
        except Exception:
            pass

    def _cb_doctor(self, msg):
        try:
            d = json.loads(msg.data)
            payload = d.get("payload", {})
            self._doctor_requests.append(payload)
            if len(self._doctor_requests) > 4:
                self._doctor_requests.pop(0)
        except Exception:
            pass

    def _cb_delivery_stats(self, msg):
        try:
            d = json.loads(msg.data)
            self._delivery_stats = d.get("stats", {})
        except Exception:
            pass

    def _cb_interruption(self, msg):
        try:
            data = json.loads(msg.data)
            if data.get("type") == "EDF_INTERRUPTION":
                self._nb_overrides = data.get("override_num", self._nb_overrides)
        except Exception:
            pass

    # ═══════════════════════════════════════════════
    # Affichage dashboard
    # ═══════════════════════════════════════════════

    def _afficher_dashboard(self):
        self._nb_updates += 1
        sep  = "═" * 68
        sep2 = "─" * 68

        print(f"\n{BOLD}{CYAN}{sep}{RESET}")
        print(
            f"{BOLD}{CYAN}  🤖 PharmaBot Dashboard RT  "
            f"#{self._nb_updates}  {time.strftime('%H:%M:%S')}{RESET}")
        print(f"{BOLD}{CYAN}{sep}{RESET}")

        # ── État robot ──
        c = (RED   if "URGENCE" in self._etat_robot or "ARRET" in self._etat_robot
             else GREEN if self._etat_robot in ("LIVRAISON", "NAVIGATION")
             else ORANGE if self._etat_robot == "CHARGEMENT"
             else CYAN)
        print(f"\n  {BOLD}État robot   :{RESET} {c}{BOLD}{self._etat_robot}{RESET}"
              f"   |  pos ({self._pos_x:.1f}, {self._pos_y:.1f})")

        # ── Navigation Phase 1 ──
        nav_phase = self._nav_status.get("phase", "—")
        nav_cible = self._nav_status.get("departement_cible", "—")
        c_nav = (GREEN if nav_phase == "NAVIGATION"
                 else ORANGE if nav_phase == "CHARGEMENT"
                 else CYAN)
        print(f"  {BOLD}Navigation   :{RESET} {c_nav}{nav_phase}{RESET}"
              f"   cible={nav_cible or '—'}")

        # ── Pipeline DMA ──
        c_pipe = (GREEN if self._dma_pipeline == "IDLE"
                  else ORANGE if "VALIDATION" in self._dma_pipeline
                  else CYAN)
        print(f"  {BOLD}Pipeline DMA :{RESET} {c_pipe}{self._dma_pipeline}{RESET}")

        # ── Mission courante ──
        print(f"\n  {BOLD}{sep2}{RESET}")
        if self._mission:
            dept    = self._mission.get("departement", "?")
            type_rt = self._mission.get("type_rt", "?")
            dead    = self._mission.get("deadline_sec", 0)
            ts      = self._mission.get("timestamp", time.time())
            restant = max(0, dead - (time.time() - ts)) if dead else 0
            cm = (RED    if type_rt == "HARD_RT"
                  else ORANGE if type_rt == "SOFT_RT"
                  else GREEN)
            barre = ""
            if dead:
                pct = int(restant / dead * 20)
                barre = f"[{cm}{'█' * pct}{'░' * (20 - pct)}{RESET}]"
            print(f"  {BOLD}Mission      :{RESET} "
                  f"{cm}{BOLD}{dept}{RESET} | {type_rt} | "
                  f"{self._mission.get('medicament','?')}")
            print(f"  {BOLD}Deadline     :{RESET} "
                  f"{cm}{restant:.0f}s restantes{RESET}  {barre}")
        else:
            print(f"  {BOLD}Mission      :{RESET} Aucune en cours")

        # ── Pharmacien Phase 2 ──
        print(f"\n  {BOLD}{sep2}{RESET}")
        ph_action = self._pharmacist_log.get("action", "—")
        ph_med    = self._pharmacist_log.get("med", "—")
        ph_stats  = self._pharmacist_log.get("stats", {})
        print(f"  {BOLD}Pharmacien   :{RESET} {BLUE}{ph_action}{RESET}"
              f"  méd={ph_med}  stock={self._stock_total} unités")
        if ph_stats:
            print(f"               validations "
                  f"ok={ph_stats.get('validations_ok',0)} "
                  f"échec={ph_stats.get('validations_echec',0)}  "
                  f"tps_moy={ph_stats.get('temps_moyen_validation',0):.1f}s")

        # ── Dernières requêtes médecin ──
        if self._doctor_requests:
            print(f"\n  {BOLD}Requêtes médecins :{RESET}")
            for req in self._doctor_requests[-3:]:
                dept = req.get("departement", "?")
                med  = req.get("medicament",  "?")
                src  = req.get("source",       "?")
                c    = DEPT_COULEURS.get(dept, CYAN)
                print(f"    {c}▶{RESET} {dept} | {med} | [{src}]")

        # ── Tâches DMA ──
        if self._dma_status:
            print(f"\n  {BOLD}Tâches DMA :{RESET}")
            for k, t in sorted(
                    self._dma_status.items(),
                    key=lambda x: x[1].get("priorite", 9)):
                etat = t.get("etat", "?")
                ok   = t.get("nb_succes", 0)
                ko   = t.get("nb_echecs", 0)
                rt   = t.get("type_rt", "")
                c    = (GREEN  if etat == "TERMINE"
                        else RED    if etat == "ECHOUE"
                        else ORANGE)
                print(f"    P{t.get('priorite','?')} "
                      f"{t.get('nom','?'):<28} "
                      f"{c}{etat:<10}{RESET} ✓{ok} ✗{ko}  [{rt}]")

        # ── Statistiques livraisons Phase 1 ──
        if self._delivery_stats:
            n    = self._delivery_stats.get("livraisons_total", 0)
            ok   = self._delivery_stats.get("deadlines_respectees", 0)
            ko   = self._delivery_stats.get("deadlines_manquees", 0)
            moy  = self._delivery_stats.get("temps_livraison_moyen", 0)
            rate = (ok / n * 100) if n > 0 else 0
            print(f"\n  {BOLD}Livraisons :{RESET} "
                  f"total={n}  "
                  f"{GREEN}✓{ok}{RESET}  "
                  f"{ORANGE}✗{ko}{RESET}  "
                  f"deadline_rate={rate:.0f}%  "
                  f"tps_moy={moy:.0f}s  "
                  f"overrides={self._nb_overrides}")

        # ── Historique livraisons ──
        if self._livraisons:
            print(f"\n  {BOLD}Dernières livraisons :{RESET}")
            for lv in self._livraisons[-3:]:
                dept = lv.get("departement", "?")
                rt   = lv.get("type_rt", "?")
                t    = lv.get("temps", 0)
                ok   = lv.get("deadline_ok", True)
                num  = lv.get("num", 0)
                cm   = (RED    if rt == "HARD_RT"
                        else ORANGE if rt == "SOFT_RT"
                        else GREEN)
                tick = f"{GREEN}✓{RESET}" if ok else f"{ORANGE}✗{RESET}"
                print(f"    {tick} #{num} {cm}{dept}{RESET} | {rt} | "
                      f"{t:.0f}s | {lv.get('medicament','?')}")

        # ── Watchdog ──
        wdg = (f"{GREEN}✓ OK{RESET}"
               if self._watchdog_ok
               else f"{RED}⚠ MODE RÉCUPÉRATION{RESET}")
        print(f"\n  {BOLD}Watchdog     :{RESET} {wdg}")

        # ── Alerte ──
        if self._derniere_alerte:
            al = self._derniere_alerte.get("type_alerte", "?")
            dp = self._derniere_alerte.get("departement", "?")
            print(f"  {BOLD}Alerte       :{RESET} {RED}{al}{RESET} — {dp}")

        print(f"{BOLD}{CYAN}{sep}{RESET}")


def main(args=None):
    rclpy.init(args=args)
    d = Dashboard()
    try:
        rclpy.spin(d)
    except KeyboardInterrupt:
        pass
    finally:
        d.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
