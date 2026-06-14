#!/usr/bin/env python3
"""
pharmabot_rt.launch.py — Lance tous les nœuds RT PharmaBot
EDF Scheduler + DMA + Mission Manager + Watchdog + Dashboard
"""
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(package='hospital_robot_spawner', executable='rt_scheduler',
             name='rt_scheduler', output='screen'),
        Node(package='hospital_robot_spawner', executable='dma_tasks',
             name='dma_scheduler', output='screen'),
        Node(package='hospital_robot_spawner', executable='mission_manager',
             name='mission_manager', output='screen'),
        Node(package='hospital_robot_spawner', executable='watchdog_node',
             name='pharmabot_watchdog', output='screen'),
        Node(package='hospital_robot_spawner', executable='dashboard',
             name='pharmabot_dashboard', output='screen'),
    ])
