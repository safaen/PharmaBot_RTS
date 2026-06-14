#!/usr/bin/env python3
"""
trained_agent.py — Agent pré-entraîné PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
"""
import rclpy
from rclpy.node import Node
from gymnasium.envs.registration import register
from hospital_robot_spawner.pharmabot_env import PharmaBotEnv
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.evaluation import evaluate_policy
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.env_checker import check_env
import os
import numpy as np

class TrainedAgent(Node):
    def __init__(self):
        super().__init__("trained_pharmabot",
                         allow_undeclared_parameters=True,
                         automatically_declare_parameters_from_overrides=True)

def main(args=None):
    rclpy.init()
    node = TrainedAgent()
    node.get_logger().info("Trained agent node has been created")

    pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'rl_models')
    trained_model_path = os.path.join(pkg_dir, 'PPO_second_generation.zip')
    node.get_logger().info(f"Loading model: {trained_model_path}")

    register(
        id="PharmaBotEnv-v0",
        entry_point="hospital_robot_spawner.pharmabot_env:PharmaBotEnv",
        max_episode_steps=3000,
    )

    env = gym.make('PharmaBotEnv-v0')
    env = Monitor(env)
    check_env(env)

    custom_obj = {'action_space': env.action_space, 'observation_space': env.observation_space}
    model = PPO.load(trained_model_path, env=env, custom_objects=custom_obj)

    Mean_ep_rew, Num_steps = evaluate_policy(
        model, env=env, n_eval_episodes=100,
        return_episode_rewards=True, deterministic=True
    )

    node.get_logger().info(f"Mean Reward: {np.mean(Mean_ep_rew):.2f} | Std: {np.std(Mean_ep_rew):.2f}")
    node.get_logger().info(f"Max: {np.max(Mean_ep_rew):.2f} | Min: {np.min(Mean_ep_rew):.2f}")
    node.get_logger().info(f"Mean episode length: {np.mean(Num_steps):.1f}")

    env.close()
    node.get_logger().info("Script complete")
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()
