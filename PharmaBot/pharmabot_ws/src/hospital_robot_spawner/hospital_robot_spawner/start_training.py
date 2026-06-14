#!/usr/bin/env python3
"""
start_training.py — Script d'entraînement PharmaBot
Équipe PharmaBot — Systèmes Embarqués Temps Réel 2025-2026
"""
import rclpy
from rclpy.node import Node
from gymnasium.envs.registration import register
from hospital_robot_spawner.pharmabot_env import PharmaBotEnv
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnRewardThreshold
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.evaluation import evaluate_policy
import os
import optuna

class TrainingNode(Node):
    def __init__(self):
        super().__init__("pharmabot_training",
                         allow_undeclared_parameters=True,
                         automatically_declare_parameters_from_overrides=True)
        self._training_mode = "training"

def main(args=None):
    rclpy.init()
    node = TrainingNode()
    node.get_logger().info("Training node has been created")

    pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'rl_models')
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'logs')
    trained_models_dir = pkg_dir

    os.makedirs(trained_models_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    register(
        id="PharmaBotEnv-v0",
        entry_point="hospital_robot_spawner.pharmabot_env:PharmaBotEnv",
        max_episode_steps=300,
    )
    node.get_logger().info("The environment has been registered")

    env = gym.make('PharmaBotEnv-v0')
    env = Monitor(env)
    check_env(env)
    node.get_logger().info("Environment check finished")

    stop_callback = StopTrainingOnRewardThreshold(reward_threshold=900, verbose=1)
    eval_callback = EvalCallback(env, callback_on_new_best=stop_callback,
                                 eval_freq=100000,
                                 best_model_save_path=trained_models_dir,
                                 n_eval_episodes=40)

    if node._training_mode == "random_agent":
        node.get_logger().info("Starting RANDOM AGENT")
        for ep in range(10):
            obs, _ = env.reset()
            done = False
            while not done:
                obs, reward, done, truncated, info = env.step(env.action_space.sample())
                node.get_logger().info(f"dist={info['distance']:.2f} | dept={info['departement']} | reward={reward:.2f}")

    elif node._training_mode == "training":
        model = PPO("MultiInputPolicy", env, verbose=1, tensorboard_log=log_dir,
                    n_steps=20480, gamma=0.9880614935504514,
                    gae_lambda=0.9435887928788405, ent_coef=0.00009689939917928778,
                    vf_coef=0.6330533453055319, learning_rate=0.00001177011863371444,
                    clip_range=0.1482)
        try:
            model.learn(total_timesteps=int(40000000), reset_num_timesteps=False,
                        callback=eval_callback, tb_log_name="PPO_pharmabot")
        except KeyboardInterrupt:
            model.save(f"{trained_models_dir}/PPO_pharmabot")
        model.save(f"{trained_models_dir}/PPO_pharmabot")

    elif node._training_mode == "retraining":
        trained_model_path = os.path.join(trained_models_dir, 'PPO_second_generation.zip')
        custom_obj = {'action_space': env.action_space, 'observation_space': env.observation_space}
        model = PPO.load(trained_model_path, env=env, custom_objects=custom_obj)
        try:
            model.learn(total_timesteps=int(20000000), reset_num_timesteps=False,
                        callback=eval_callback, tb_log_name="PPO_pharmabot_retrain")
        except KeyboardInterrupt:
            model.save(f"{trained_models_dir}/PPO_pharmabot_retrain")
        model.save(f"{trained_models_dir}/PPO_pharmabot_retrain")

    elif node._training_mode == "hyperparam_tuning":
        env.close()
        del env
        study = optuna.create_study(direction='maximize')
        study.optimize(optimize_agent, n_trials=10, n_jobs=1)
        node.get_logger().info("Best Hyperparameters: " + str(study.best_params))

    node.get_logger().info("Training finished")
    node.destroy_node()
    rclpy.shutdown()

def optimize_agent(trial):
    try:
        env_opt = gym.make('PharmaBotEnv-v0')
        LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
        params  = {'n_steps': trial.suggest_int('n_steps', 2048, 8192),
                   'gamma': trial.suggest_float('gamma', 0.8, 0.9999, log=True),
                   'learning_rate': trial.suggest_float('learning_rate', 1e-6, 1e-3, log=True),
                   'clip_range': trial.suggest_float('clip_range', 0.1, 0.4),
                   'gae_lambda': trial.suggest_float('gae_lambda', 0.8, 0.99),
                   'ent_coef': trial.suggest_float('ent_coef', 1e-8, 0.1, log=True),
                   'vf_coef': trial.suggest_float('vf_coef', 0, 1)}
        model = PPO("MultiInputPolicy", env_opt, tensorboard_log=LOG_DIR, verbose=0, **params)
        model.learn(total_timesteps=150000)
        mean_reward, _ = evaluate_policy(model, env_opt, n_eval_episodes=20)
        env_opt.close()
        return mean_reward
    except Exception:
        return -10000

if __name__ == "__main__":
    main()
