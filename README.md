Plant Growth Phase Monitoring System

This project presents a prototype system for automated indoor plant monitoring using a combination of embedded systems, computer vision, and machine learning. The system captures images of a plant from multiple positions, classifies its growth phase, reads environmental data, and performs automated actions based on the detected stage.

Overview

The system is built around a master–slave architecture:

Raspberry Pi acts as the main controller
Arduino Nano handles low-level hardware control

The system continuously performs scanning cycles, analyzes plant condition, and adjusts environmental parameters accordingly.

System Workflow

The process is divided into two phases:

ZERO Phase

During this phase, the system performs a full scan:

The stepper motor rotates the plant platform
The camera captures:
12 images during forward rotation
12 images during reverse rotation
Each image is processed using a machine learning model
Predictions are collected and aggregated

A final decision is made using majority voting across all captured images.

INTERVENTION Phase

Based on the detected plant stage, the system performs predefined actions:

Germination (GR)
LED turned off
Dark environment maintained
Growth (GP)
LED set to 50% power
Motor performs one rotation cycle
Pre-harvest (PH)
LED set to full power
Motor performs two rotation cycles

Each phase lasts for a fixed period, after which the system returns to the ZERO phase and repeats the process.

Machine Learning

The system uses a MobileNetV2 convolutional neural network:

Pretrained on ImageNet
Fine-tuned on a custom dataset of 300 images
The dataset was split using a 70/30 ratio:
70% of images were used for training
30% of images were used for validation

dataset/
├── train/
│   ├── GR/
│   ├── GP/
│   └── PH/
├── validation/
│   ├── GR/
│   ├── GP/
│   └── PH/

***
GR – Germination
GP – Growth
PH – Pre-harvest

Dataset is available here:
https://drive.google.com/drive/folders/1q_EWHuwKacSHNcrIof5lPpwcbzGtp47S?usp=sharing

The trained model is exported to TensorFlow Lite and runs locally on the Raspberry Pi.

Hardware Components
Raspberry Pi 4 Model B (8GB RAM)
Arduino Nano (ATmega328P)
Raspberry Pi Camera Module v2 (Sony IMX219)
28BYJ-48 stepper motor with ULN2003 driver
DHT11 temperature and humidity sensor
Capacitive soil moisture sensor
LED grow strip (5V, PWM controlled)
External power supply
3D-printed enclosure and mechanical structure
Software Structure
Arduino

The Arduino firmware is responsible for:

Stepper motor control (absolute positioning and rotation)
Sensor data acquisition
LED control (on/off/PWM/blink)
Serial communication with Raspberry Pi
Python (Raspberry Pi)

The Python script coordinates the system:

Detects and connects to the Arduino via serial port
Controls motor positioning
Captures images using the camera
Runs inference using a TensorFlow Lite model
Reads sensor data from Arduino
Logs results into CSV files
Applies decision logic (majority voting)
Triggers actions based on plant stage
Data Output

The system generates two main log files:

scan_log.csv
Contains detailed data for each position:
prediction
sensor values
timing information
scan_summary.csv
Contains final decisions for each scan cycle.
3D Model

A custom 3D-printed model was designed and used as part of the system.

It is used for:

mounting electronic components
holding the plant/sample
enabling controlled rotation for image acquisition

The model is included in this repository and can be used for 3D printing.

How to Run
Upload the Arduino code to the Arduino Nano
On the Raspberry Pi, install dependencies:
pip install pyserial
Run the main script:
python3 scan_sync.py
Notes
The homing process is software-based (no physical limit switch)
DHT11 is used as a basic sensor (limited accuracy)
Model accuracy is approximately 73% due to dataset size
The system is designed as a prototype
Future Work
Improve model accuracy with a larger dataset
Add a physical homing sensor
Replace sensors with higher-precision alternatives
Implement a web interface for remote monitoring and control
Optimize image acquisition and inference pipeline
