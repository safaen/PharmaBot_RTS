#!/usr/bin/env python3
"""
pharmabot_env.py — Environnement Gymnasium pour PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
Prof. Khaoula Boukir — Ibn Tofaïl University

Modifications par rapport à hospitalbot_env.py (original) :
    - Renommage complet : HospitalBotEnv → PharmaBotEnv
    - 4 départements nommés avec coordonnées et couleurs
    - Méthode de récompense RT-aware (méthode 3) — nouvelle
    - Sélection automatique du département selon priorité RT
    - Statistiques par département et par niveau RT
"""

import rclpy
from gymnasium import Env
from gymnasium.spaces import Dict, Box
import numpy as np
from hospital_robot_spawner.robot_controller import RobotController
import math
import time

# ═══════════════════════════════════════════════════════════════════════════════
# DÉPARTEMENTS DE L'HÔPITAL
# ═══════════════════════════════════════════════════════════════════════════════

DEPARTEMENTS = {
    "pharmacie": {
        "nom":          "Pharmacy_Room",
        "x": 1.0, "y": 16.0,
        "couleur":      "BLEU",
        "priorite":     None,
        "deadline_sec": None,
    },
    "reanimation": {
        "nom":          "ICU_Room",
        "x": -5.0, "y": 14.1,
        "couleur":      "ROUGE",
        "priorite":     "HARD_RT",
        "deadline_sec": 30,
    },
    "urgences": {
        "nom":          "Emergency_Room",
        "x": 12.5, "y": 8.2,
        "couleur":      "ORANGE",
        "priorite":     "SOFT_RT",
        "deadline_sec": 120,
    },
    "consultation": {
        "nom":          "Consultation_Room",
        "x": 18.0, "y": -6.0,
        "couleur":      "VERT",
        "priorite":     "FIRM_RT",
        "deadline_sec": 300,
    },
}


class PharmaBotEnv(RobotController, Env):
    """Environnement Gymnasium PharmaBot — livraison médicaments temps réel."""

    def __init__(self):
        super().__init__()
        self.get_logger().info("PharmaBot — Initialisation environnement")

        self.robot_name = "PharmaBot"

        self._initial_agent_location = np.array([
            DEPARTEMENTS["pharmacie"]["x"],
            DEPARTEMENTS["pharmacie"]["y"], -90
        ], dtype=np.float32)

        self._departement_cible  = "reanimation"
        self._target_location    = np.array([
            DEPARTEMENTS[self._departement_cible]["x"],
            DEPARTEMENTS[self._departement_cible]["y"]
        ], dtype=np.float32)

        self._priorite_courante  = DEPARTEMENTS[self._departement_cible]["priorite"]
        self._deadline_sec       = DEPARTEMENTS[self._departement_cible]["deadline_sec"]
        self._temps_debut        = time.time()

        # Paramètres
        self._randomize_env_level         = 5
        self._normalize_obs               = True
        self._normalize_act               = True
        self._visualize_target            = True
        self._reward_method               = 3   # RT-aware (nouveau)
        self._max_linear_velocity         = 1.0
        self._min_linear_velocity         = 0.0
        self._angular_velocity            = 1.0
        self._minimum_dist_from_target    = 0.42
        self._minimum_dist_from_obstacles = 0.26
        self._attraction_threshold        = 3.0
        self._attraction_factor           = 1.0
        self._repulsion_threshold         = 1.0
        self._repulsion_factor            = 0.1
        self._distance_penalty_factor     = 1.0

        self._num_steps    = 0
        self._num_episodes = 0

        self._stats = {
            "succes": 0, "echecs": 0,
            "deadlines_hard": 0, "deadlines_soft": 0, "deadlines_firm": 0,
            "livraisons_par_dept": {k: 0 for k in DEPARTEMENTS if k != "pharmacie"},
        }

        if self._randomize_env_level >= 6:
            np.random.seed(4)

        if self._normalize_act:
            self.action_space = Box(
                low=np.array([-1, -1]), high=np.array([1, 1]), dtype=np.float32)
        else:
            self.action_space = Box(
                low=np.array([self._min_linear_velocity, -self._angular_velocity]),
                high=np.array([self._max_linear_velocity,  self._angular_velocity]),
                dtype=np.float32)

        if self._normalize_obs:
            self.observation_space = Dict({
                "agent": Box(low=np.array([0, 0]),  high=np.array([6, 1]),   dtype=np.float32),
                "laser": Box(low=0, high=1, shape=(61,), dtype=np.float32),
            })
        else:
            self.observation_space = Dict({
                "agent": Box(low=np.array([0, -math.pi]), high=np.array([60, math.pi]), dtype=np.float32),
                "laser": Box(low=0, high=np.inf, shape=(61,), dtype=np.float32),
            })

        self.robot_locations = [
            [1, 16, -90, -1, 1, -0.5, 0.5, -30, 30],
            [1, 10, 90, -3, 3, -1, 1, -30, 30],
            [11, 13, 180, -1, 1, -0.25, 0.25, -30, 30],
            [6.7, 13, 45, -0.1, 0.1, -0.1, 0.5, -15, 15],
            [11.5, 5.7, 180, -0.2, 0.2, -0.1, 0.1, 0, 30],
            [7.5, 4.8, 0, -1, 0.5, -0.1, 0.1, -15, 15],
            [7.7, -8, 90, -0.5, 0.5, -1.5, 1.5, -30, 30],
            [10, -2.1, 180, -0.5, 0.5, 0, 0, -10, 10],
            [-2.3, -30.5, 90, -0.2, 0.5, -0.5, 1.5, -20, 45],
            [4, -27.4, 180, -2, 2, -1, 0.7, -30, 30],
            [-7.7, -30.8, 90, -0.2, 0.2, -0.5, 1, -20, 20],
            [-9.7, -26, -30, -1, 0.2, -0.5, 0.5, -20, 20],
            [-2.1, -24.6, 180, -1, 1, -0.3, 0.3, -45, 30],
            [-5, -21, -90, -1, 1, -0.5, 2, -30, 30],
            [-5, -6.6, 90, -0.5, 0.5, -1, 1, -30, 30],
            [-3.2, -2.9, 180, -0.5, 0, -1, 0.2, -20, 20],
            [-5, 4, -90, -0.5, 0.5, -1, 1, -30, 30],
            [-2.2, 1, 180, -0.5, 2, -0.2, 0.5, -30, 30],
            [-3.6, 10.9, 180, -1, 1.5, -1, 1, -15, 45],
            [-7.4, 10.4, 0, -0.1, 1, -0.7, 0.7, -30, 30],
            [-1.6, -8.5, 0, -1, 1, -0.5, 0.5, -30, 30],
            [3.3, -8.6, 180, -0.2, 1, -0.5, 0.5, -30, 30],
            [5, -6, 90, -0.8, 0, -1, 1, -45, 45],
            [3.2, -2.8, -30, 0, 1, -1, 0, -15, 15],
            [2.8, -14.5, -90, 0, 0, -0.2, 0, -15, 15],
            [1.7, -19, 90, 0, 0.5, -0.2, 0.5, -15, 15],
        ]

        self.target_locations = [
            [1, 10, -3, 3, -1, 3], [1, 16, -1, 1, -1, 1],
            [6.7, 12, -0.1, 0.1, -0.5, 2], [11, 13, -0.5, 0.5, -0.2, 0.2],
            [8, 4.8, -1.5, 1.5, -0.1, 0.1], [11.3, 5.5, -0.3, 0.3, -0.2, 0.2],
            [10.8, -2.1, -1, 1, -0.1, 0.1], [8.3, -6.8, -0.5, 0.5, -1, 1],
            [4.3, -27.6, -2, 0.5, -0.5, 0.5], [-2, -29.8, -0.5, 0.5, -1, 1],
            [-10.5, -26.3, -0.2, 1, -1, 1], [-7.7, -30, -0.8, 0.8, -1, 1],
            [-5, -21, -1, 1, -2.5, 0.5], [-1.5, -24.3, -1, 1, -1, 1],
            [-3.1, -3.5, -0.1, 0.1, -1, 1], [-5.2, -7, -0.9, 1, -2, 2],
            [0, 2, -3, 0, -1, 1], [-4.5, 4, -0.5, 0.5, -1, 1],
            [-7, 10.3, -0.5, 0.5, -0.5, 0.5], [-2.6, 10.3, -0.5, 2, -2, 2],
            [3.3, -8.6, -0.5, 0.5, -0.5, 0.5], [-1, -8.5, -1, 0, -0.2, 0.2],
            [3, -3.5, 0, 0, -1, 1], [4.6, -6.4, -0.5, 0.5, -1, 1],
            [1.5, -19, -0.1, 0.5, -1, 1], [2.8, -15.4, 0, 0, -0.5, 0.5],
        ]

        self.waypoints_locations = [
            [[2,10,-2,2,-1,1],[4,5,-0.5,0.5,-0.5,0.5],[5,0,-0.7,1,-1,1],[5,-5,-0.7,1,-1,1],[4,-8.5,-1,1,-0.5,0.5],[-3,-8.5,-1,1,-0.5,0.5],[-5,-13,-0.5,0.5,-1,1],[-5,-17.5,-0.5,0.5,-1,1],[-4,-25,-1,0,0,0],[-9,-26,-1,1,-0.5,0.5],[-7.5,-31,0,0,-0.5,0.5],[-7.5,-34,-1,1,-0.5,0.5],[-2,-33.5,-1,1,-0.5,0.5],[2,-33.5,-1,1,-0.5,0.5],[6,-33.5,-1,1,-0.5,0.5],[10,-33.5,-1,1,-0.5,0.5]],
            [[-1.6,11,-2,2,-1,1],[-3.3,6,-0.5,0.5,-0.5,0.5],[-4.7,3,-0.5,0.5,-0.2,1],[-5,-1.6,-0.5,0.5,-0.5,0.5],[-5.1,-6.6,-0.5,0.5,-1,1],[-4.8,-9.7,-0.7,0.7,-1,1],[-3.5,-14.6,-1,1,-1,1],[1.8,-14.5,-1,1,-1,1],[5,-16.9,-0.5,0.5,-0.5,0.5],[4.8,-23.1,-0.2,0.2,-0.2,0.2],[8.8,-22.9,0,0,-0.1,0.3],[8.5,-16.7,-1,1,-0.5,0.5],[8.8,-22.9,0,0,-0.1,0.3],[4.8,-23.1,-0.2,0.2,-0.2,0.2],[5.4,-27.7,-1,1,-0.5,0.5],[-1.8,-27.7,-1,1,-0.5,0.5]],
            [[4.1,11.9,-1,1,-1,1],[3.1,7.1,-0.5,0.5,-0.5,0.5],[5.1,2.7,-0.5,0.5,-0.5,0.5],[0.2,1.2,-0.5,0.5,-0.5,0.5],[-4.1,1,0,0,0,0],[-5,-1.6,-0.5,0.5,-0.5,0.5],[-3.5,-3.5,-0.5,0.1,-1,1],[-4.8,-6,-0.5,0.5,-1,1],[-4.9,-9,-1,0,0,0],[-4.9,-13.5,-0.5,0.5,-0.5,0.5],[-1.6,-14.5,-1,1,-0.5,0.5],[5.1,-14.5,-1,1,-0.5,0.5],[4.9,-24.5,-1,1,-0.5,0.5],[0,-24.6,-1,1,-0.5,0.5],[-4.9,-28.8,-0.5,0.5,-0.5,0.5],[-4.9,-33.8,-1,1,-0.5,0.5]],
            [[0.7,11.8,-1,1,-1,1],[4.7,10.6,-1,1,-0.5,0.5],[2.7,7.5,-0.5,0.5,-0.5,0.5],[4.9,4.1,-0.5,0.5,-0.5,0.5],[5.1,0,0,0,0,0],[1.4,2.1,-0.5,0.5,-0.5,0.5],[-3.3,1.3,-0.5,0.5,-0.5,0.5],[-5.1,-1.5,-0.5,0.5,-0.5,0.5],[-5,-5,-0.5,0.5,-0.5,0.5],[-4.9,-8.6,-0.5,0.5,-0.5,0.5],[-4.9,-14.5,-1,1,-0.5,0.5],[1.1,-14.5,-1,1,-0.5,0.5],[4.9,-14.8,-0.5,0.5,-0.5,0.5],[5.1,-9.4,-0.5,0.5,-0.5,0.5],[1.1,-7.7,0,0,0,0],[-3,-8.6,-0.5,0.5,-0.5,0.5]],
            [[-2.4,12.7,-1,1,-1,1],[-0.5,10,-0.5,0.5,-0.5,0.5],[-4.8,4,-0.5,0.5,-0.5,0.5],[-4.6,-0.8,0,0,0,0],[-5,-5.8,-0.5,0.5,-0.5,0.5],[-2.2,-8.6,-0.5,0.5,-0.5,0.5],[1.1,-7.7,0,0,0,0],[5.5,-9,-0.5,0.5,0,0],[8.8,-8.7,0,0,0,0],[8.3,-5.1,-0.5,0.5,-0.5,0.5],[8.1,-1.8,-0.5,0.5,-0.5,0.5],[8.3,-5.1,-0.5,0.5,-0.5,0.5],[8.8,-8.7,0,0,0,0],[8.3,-5.1,-0.5,0.5,-0.5,0.5],[8.1,-1.8,-0.5,0.5,-0.5,0.5],[8.3,-5.1,-0.5,0.5,-0.5,0.5]],
        ]

        self._which_waypoint  = 0
        self._path            = 0
        self._completed_paths = 0

        self.get_logger().info(
            f"Département : {self._departement_cible.upper()} | "
            f"Priorité : {self._priorite_courante} | "
            f"Deadline : {self._deadline_sec}s"
        )

    def step(self, action):
        self._num_steps += 1
        if self._normalize_act:
            action = self.denormalize_action(action)
        self.send_velocity_command(action)
        self.spin()
        self.transform_coordinates()
        observation = self._get_obs()
        info        = self._get_info()
        reward      = self.compute_rewards(info)
        if self._randomize_env_level <= 6.5:
            done = (info["distance"] < self._minimum_dist_from_target or
                    any(info["laser"] < self._minimum_dist_from_obstacles))
        else:
            if self._which_waypoint == len(self.waypoints_locations[0]) - 1:
                done = (info["distance"] < self._minimum_dist_from_target or
                        any(info["laser"] < self._minimum_dist_from_obstacles))
            else:
                done = any(info["laser"] < self._minimum_dist_from_obstacles)
                if info["distance"] < self._minimum_dist_from_target:
                    self._which_waypoint += 1
                    self.randomize_target_location()
                    if self._visualize_target:
                        self.call_set_target_state_service(self._target_location)
        return observation, reward, done, False, info

    def reset(self, seed=None, options=None):
        self._num_episodes += 1
        self._choisir_departement()
        pose2d = self.randomize_robot_location()
        self._done_set_rob_state = False
        self.call_set_robot_state_service(pose2d)
        while not self._done_set_rob_state:
            rclpy.spin_once(self)
        self._path           = np.random.randint(0, len(self.waypoints_locations))
        self._which_waypoint = 0
        if self._randomize_env_level >= 2:
            self.randomize_target_location()
        if self._visualize_target:
            self.call_set_target_state_service(self._target_location)
        self.spin()
        self.transform_coordinates()
        observation   = self._get_obs()
        info          = self._get_info()
        self._num_steps   = 0
        self._temps_debut = time.time()
        return observation, info

    def _choisir_departement(self):
        """Choisit le département selon une distribution réaliste."""
        depts  = ["reanimation", "urgences", "consultation"]
        poids  = [0.20, 0.40, 0.40]
        self._departement_cible = np.random.choice(depts, p=poids)
        d = DEPARTEMENTS[self._departement_cible]
        self._priorite_courante = d["priorite"]
        self._deadline_sec      = d["deadline_sec"]
        self._target_location   = np.array([d["x"], d["y"]], dtype=np.float32)
        self.get_logger().info(
            f"[REQUÊTE] → {d['nom']} | {self._priorite_courante} | "
            f"deadline={self._deadline_sec}s | couleur={d['couleur']}"
        )

    def compute_rewards(self, info):
        """Calcul récompense — méthode RT-aware (méthode 3, originale PharmaBot)."""
        temps_ecoule = time.time() - self._temps_debut
        deadline_ok  = (self._deadline_sec is None or temps_ecoule <= self._deadline_sec)
        facteurs     = {"HARD_RT": 3.0, "SOFT_RT": 2.0, "FIRM_RT": 1.0}
        facteur      = facteurs.get(self._priorite_courante, 1.0)

        if self._reward_method == 0:
            if info["distance"] < self._minimum_dist_from_target:
                reward = 1
            elif any(info["laser"] < self._minimum_dist_from_obstacles):
                reward = -1
            else:
                reward = 0

        elif self._reward_method == 1:
            if info["distance"] < self._minimum_dist_from_target:
                reward = 1
            elif any(info["laser"] < self._minimum_dist_from_obstacles):
                reward = -0.1
            else:
                reward = 0

        elif self._reward_method == 2:
            if info["distance"] < self._minimum_dist_from_target:
                reward = 1000 - self._num_steps
            elif any(info["laser"] < self._minimum_dist_from_obstacles):
                reward = -10000
            else:
                ir  = -info["distance"] * self._distance_penalty_factor
                ar  = (self._attraction_factor / info["distance"]
                       if info["distance"] < self._attraction_threshold else 0)
                rep = sum((-self._repulsion_factor / r**2) * (1/r - 1/self._repulsion_threshold)
                          for r in info["laser"] if r <= self._repulsion_threshold)
                reward = min(ir + ar + rep, 1)

        else:  # RT-aware
            if info["distance"] < self._minimum_dist_from_target:
                if self._priorite_courante == "FIRM_RT" and not deadline_ok:
                    reward = -0.5
                    self._stats["deadlines_firm"] += 1
                    self.get_logger().info("[FIRM RT] Livraison ANNULÉE — deadline dépassée")
                else:
                    reward = 1.0 * facteur
                    if deadline_ok and self._deadline_sec:
                        ratio  = 1.0 - (temps_ecoule / self._deadline_sec)
                        reward += 0.5 * facteur * max(0, ratio)
                    self._stats["succes"] += 1
                    self._stats["livraisons_par_dept"][self._departement_cible] += 1
                    self.get_logger().info(
                        f"[{self._priorite_courante}] LIVRAISON RÉUSSIE → "
                        f"{DEPARTEMENTS[self._departement_cible]['nom']} | "
                        f"reward={reward:.2f} | {temps_ecoule:.1f}s/{self._deadline_sec}s"
                    )
            elif any(info["laser"] < self._minimum_dist_from_obstacles):
                reward = -1.0 * facteur
                self._stats["echecs"] += 1
                if not deadline_ok:
                    if self._priorite_courante == "HARD_RT":
                        self._stats["deadlines_hard"] += 1
                        self.get_logger().info("[HARD RT] COLLISION + DEADLINE MANQUÉE — Mode récupération !")
                    elif self._priorite_courante == "SOFT_RT":
                        self._stats["deadlines_soft"] += 1
            else:
                reward = -0.01 * info["distance"] * facteur

        return reward

    def _get_obs(self):
        obs = {"agent": self._polar_coordinates, "laser": self._laser_reads}
        if self._normalize_obs:
            obs = self.normalize_observation(obs)
        return obs

    def _get_info(self):
        temps = time.time() - self._temps_debut
        return {
            "distance":           math.dist(self._agent_location, self._target_location),
            "laser":              self._laser_reads,
            "angle":              self._theta,
            "departement":        self._departement_cible,
            "priorite":           self._priorite_courante,
            "temps_ecoule":       temps,
            "deadline_sec":       self._deadline_sec,
            "deadline_respectee": (self._deadline_sec is None or temps <= self._deadline_sec),
        }

    def spin(self):
        self._done_pose = False; self._done_laser = False
        while not self._done_pose or not self._done_laser:
            rclpy.spin_once(self)

    def transform_coordinates(self):
        self._radius = math.dist(self._agent_location, self._target_location)
        rx = (math.cos(-self._agent_orientation) * (self._target_location[0] - self._agent_location[0]) -
              math.sin(-self._agent_orientation) * (self._target_location[1] - self._agent_location[1]))
        ry = (math.sin(-self._agent_orientation) * (self._target_location[0] - self._agent_location[0]) +
              math.cos(-self._agent_orientation) * (self._target_location[1] - self._agent_location[1]))
        self._theta             = math.atan2(ry, rx)
        self._polar_coordinates = np.array([self._radius, self._theta], dtype=np.float32)

    def randomize_target_location(self):
        if self._randomize_env_level in (2, 3):
            d = DEPARTEMENTS[self._departement_cible]
            self._target_location = np.array([d["x"], d["y"]], dtype=np.float32)
            self._target_location += np.float32(np.random.rand(2) * 2 - 1)
        elif self._randomize_env_level == 5:
            loc = self.target_locations[self._location]
            self._target_location = np.array([loc[0], loc[1]], dtype=np.float32)
            self._target_location[0] += float(np.random.rand(1) * (loc[3]-loc[2]) + loc[2])
            self._target_location[1] += float(np.random.rand(1) * (loc[5]-loc[4]) + loc[4])
        elif self._randomize_env_level == 7:
            wp = self.waypoints_locations[self._path][self._which_waypoint]
            self._target_location = np.array([wp[0], wp[1]], dtype=np.float32)
            self._target_location[0] += float(np.random.rand(1) * (wp[3]-wp[2]) + wp[2])
            self._target_location[1] += float(np.random.rand(1) * (wp[5]-wp[4]) + wp[4])

    def randomize_robot_location(self):
        if self._randomize_env_level in (0, 2):
            px, py = float(self._initial_agent_location[0]), float(self._initial_agent_location[1])
            a  = float(math.radians(self._initial_agent_location[2]))
        elif self._randomize_env_level in (1, 3, 7):
            px = 1.0 + float(np.random.rand(1) * 2 - 1)
            py = 16.0 + float(np.random.rand(1) - 0.5)
            a  = float(math.radians(-90) + math.radians(np.random.rand(1) * 60 - 30))
        elif self._randomize_env_level == 5:
            self._location = np.random.randint(0, len(self.robot_locations))
            loc = self.robot_locations[self._location]
            px = float(loc[0]) + float(np.random.rand(1) * (loc[4]-loc[3]) + loc[3])
            py = float(loc[1]) + float(np.random.rand(1) * (loc[6]-loc[5]) + loc[5])
            a  = float(math.radians(loc[2]) + math.radians(np.random.rand(1) * (loc[8]-loc[7]) + loc[7]))
        else:
            px, py = float(self._initial_agent_location[0]), float(self._initial_agent_location[1])
            a  = float(math.radians(self._initial_agent_location[2]))
        return [px, py, float(math.sin(a/2)), float(math.cos(a/2))]

    def normalize_observation(self, obs):
        obs["agent"][0] = obs["agent"][0] / 10
        obs["agent"][1] = (obs["agent"][1] + math.pi) / (2 * math.pi)
        obs["laser"]    = obs["laser"] / 10
        return obs

    def denormalize_action(self, norm_act):
        al = ((self._max_linear_velocity * (norm_act[0]+1)) + (self._min_linear_velocity * (1-norm_act[0]))) / 2
        aa = ((self._angular_velocity * (norm_act[1]+1)) + (-self._angular_velocity * (1-norm_act[1]))) / 2
        return np.array([al, aa], dtype=np.float32)

    def render(self): pass

    def close(self):
        self.get_logger().info("PharmaBot — Statistiques finales")
        self.get_logger().info(f"Succès : {self._stats['succes']} | Échecs : {self._stats['echecs']}")
        for dept, nb in self._stats["livraisons_par_dept"].items():
            self.get_logger().info(f"  {DEPARTEMENTS[dept]['nom']} : {nb}")
        self.destroy_node()
