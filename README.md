# PharmaBot RTS

## Overview
PharmaBot RTS is an intelligent hospital medication delivery platform combining robotics, real-time systems, artificial intelligence, and autonomous navigation.

## Objectives
- Automate medication delivery inside a hospital.
- Respect real-time scheduling constraints.
- Manage pharmaceutical stock.
- Provide real-time monitoring through a dashboard.
- Enable autonomous robot navigation.

## System Architecture

Doctor Request
→ EDF Scheduler
→ Mission Manager
→ Virtual Pharmacist
→ Stock Verification
→ PharmaBot Robot
→ Autonomous Navigation
→ Medication Delivery
→ Dashboard Update

## Project Phases

### Phase 1 – Real-Time System
- EDF Scheduler
- Watchdog
- DMA Simulation
- Deadline Monitoring

### Phase 2 – Pharmaceutical Management
- Virtual Pharmacist
- Stock Management
- Medication Tracking
- Dashboard

### Phase 3 – Delivery Robot
- Tray Management
- Medication Spawning
- Delivery Zone
- Object Attachment

### Phase 4 – Intelligent Navigation
- SLAM
- Nav2
- Autonomous Navigation
- Obstacle Avoidance

## Technologies
- ROS2 Humble
- Gazebo
- Python
- PPO Reinforcement Learning
- Streamlit
- Nav2
- SLAM

## Features
- Prescription processing
- Mission scheduling
- Stock verification
- Autonomous delivery
- Real-time monitoring
- Intelligent navigation

## Repository Structure
- hospital_robot_spawner/
- models/
- worlds/
- launch/
- config/
- rl_models/
- dashboard/
- reports/

## Authors
PharmaBot RTS Project Team

## License
Academic Project
