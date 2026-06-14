"""
pharmabot_full.launch.py — Lance TOUT en une seule commande
Phase 1+2 : Gazebo + RT Scheduler + DMA + Mission Manager +
            Watchdog + Dashboard + Doctor Request + Nav Bridge +
            Delivery Detector + Pharmacist

Ordre de démarrage :
    t+0s   Gazebo (hospital.world)
    t+3s   Spawn robot (Pioneer 3AT)
    t+5s   RT Scheduler (EDF)
    t+5s   DMA Scheduler
    t+5s   Pharmacist Node         ← NOUVEAU Phase 2
    t+6s   Mission Manager
    t+6s   Watchdog Node
    t+7s   Navigation Bridge       ← NOUVEAU Phase 1
    t+7s   Delivery Detector       ← NOUVEAU Phase 1
    t+8s   Doctor Request Node     ← NOUVEAU Phase 1
    t+10s  Dashboard
    t+12s  Trained Agent (navigation RL)
"""
import os
from launch import LaunchDescription
from launch.actions import ExecuteProcess, TimerAction
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_dir = get_package_share_directory('hospital_robot_spawner')
    os.environ["GAZEBO_MODEL_PATH"] = os.path.join(pkg_dir, 'models')
    world = os.path.join(pkg_dir, 'worlds', 'hospital.world')

    # ── Gazebo ──
    gazebo = ExecuteProcess(
        cmd=[
            'gazebo', '--verbose', world,
            '-s', 'libgazebo_ros_init.so',
            '-s', 'libgazebo_ros_factory.so',
        ],
        output='screen',
    )

    # ── Spawn robot à t+3s ──
    spawn = TimerAction(period=3.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='spawn_demo',
            arguments=['PharmaBot', 'demo', '1', '16.0', '0.0'],
            output='screen',
        )
    ])

    # ── EDF RT Scheduler à t+5s ──
    rt_scheduler = TimerAction(period=5.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='rt_scheduler',
            name='rt_scheduler',
            output='screen',
        )
    ])

    # ── DMA Scheduler à t+5s ──
    dma = TimerAction(period=5.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='dma_tasks',
            name='dma_scheduler',
            output='screen',
        )
    ])

    # ── Pharmacist Node à t+5s (Phase 2) ──
    pharmacist = TimerAction(period=5.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='pharmacist',
            name='pharmacist_node',
            output='screen',
        )
    ])

    # ── Mission Manager à t+6s ──
    mission = TimerAction(period=6.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='mission_manager',
            name='mission_manager',
            output='screen',
        )
    ])

    # ── Watchdog à t+6s (CORRECTION : était présent dans launch mais pas dans setup.py) ──
    watchdog = TimerAction(period=6.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='watchdog_node',
            name='pharmabot_watchdog',
            output='screen',
        )
    ])

    # ── Navigation Bridge à t+7s (Phase 1) ──
    nav_bridge = TimerAction(period=7.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='nav_bridge',
            name='navigation_bridge',
            output='screen',
        )
    ])

    # ── Delivery Detector à t+7s (Phase 1) ──
    delivery = TimerAction(period=7.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='delivery_detect',
            name='delivery_detector',
            output='screen',
        )
    ])

    # ── Doctor Request Node à t+8s (Phase 1) ──
    # Démarré APRÈS nav_bridge et delivery_detector pour éviter
    # les requêtes sans consommateurs prêts
    doctor = TimerAction(period=8.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='doctor_request',
            name='doctor_request_node',
            output='screen',
        )
    ])

    # ── Dashboard à t+10s ──
    dashboard = TimerAction(period=10.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='dashboard',
            name='pharmabot_dashboard',
            output='screen',
        )
    ])

    # ── Agent RL (navigation) à t+12s ──
    # Démarré en dernier car il prend le contrôle du robot
    trained_agent = TimerAction(period=12.0, actions=[
        Node(
            package='hospital_robot_spawner',
            executable='trained_agent',
            name='trained_pharmabot',
            output='screen',
        )
    ])

    return LaunchDescription([
        gazebo,
        spawn,
        rt_scheduler,
        dma,
        pharmacist,
        mission,
        watchdog,
        nav_bridge,
        delivery,
        doctor,
        dashboard,
        trained_agent,
    ])
