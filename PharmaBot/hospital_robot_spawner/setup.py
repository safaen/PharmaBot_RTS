import os
from glob import glob
from setuptools import setup

package_name = 'hospital_robot_spawner'
cur_directory_path = os.path.abspath(os.path.dirname(__file__))

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'worlds/'), glob('./worlds/*')),
        (os.path.join('share', package_name, 'models/mobile_warehouse_robot/'), glob('./models/mobile_warehouse_robot/*')),
        (os.path.join('share', package_name, 'models/pioneer3at/'), glob('./models/pioneer3at/model.sdf')),
        (os.path.join('share', package_name, 'models/pioneer3at/'), glob('./models/pioneer3at/model.config')),
        (os.path.join('share', package_name, 'models/Target/'), glob('./models/Target/model.sdf')),
        (os.path.join('share', package_name, 'models/Target/'), glob('./models/Target/model.config')),
        (os.path.join('share', package_name, 'rl_models/'), glob('./rl_models/*.zip')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Team PharmaBot',
    maintainer_email='pharmabot@ibntomail.ac.ma',
    description='PharmaBot — Autonomous Hospital Medicine Delivery Robot with Real-Time Scheduling (EDF/RMS/DMA)',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'spawn_demo       = hospital_robot_spawner.spawn_demo:main',
            'start_training   = hospital_robot_spawner.start_training:main',
            'trained_agent    = hospital_robot_spawner.trained_agent:main',
            'rt_scheduler     = hospital_robot_spawner.rt_scheduler:main',
            'dma_tasks        = hospital_robot_spawner.dma_tasks:main',
            'mission_manager  = hospital_robot_spawner.mission_manager:main',
            'watchdog_node    = hospital_robot_spawner.watchdog_node:main',
            'dashboard        = hospital_robot_spawner.dashboard:main',
        ],
    },
)
