# Child Mode Integration Extension

This document describes the **Child Presence Detection** extension for the Safety Monitor VehicleApp.  
It references the main project structure described in [README.md](./README.md).

---

## 📘 Extension Overview

The Child Mode feature automatically enhances vehicle safety by inspecting the rear seat using a camera.

### Key Logic
1.  **Detection**: Uses a `ResNet18` deep learning model to detect child presence in the video feed.
2.  **Auto-Enable**: If a child is detected, **Child Mode** is enabled (`vehicle/childLock/set` -> `true`).
3.  **Auto-Disable**: If no child is detected for a configurable duration (debounce), it disables Child Mode.
4.  **Restrictions**: When active, "Inside" unlock requests for rear doors are **blocked**.

---

### Core Components
1.  **ChildPresenceDetector (`child_detector.py`)**:
    *   Uses a pre-trained **ResNet18** model (via PyTorch) to extract image features.
    *   Classifies features using K-means clustering (Child vs No-Child regions).
    *   Runs on CPU (optimized for standard dev containers).

2.  **ChildLockController (`childlock_vapp_main.py`)**:
    *   Manages the "Child Mode" state machine.
    *   **Debounces** detections (requires `DEBOUNCE_THRESHOLD` consecutive negative checks to disable).
    *   Intersects with Door/Seatbelt/Speed signals to enforce safety rules.

3.  **Live Video Server**:
    *   Embedded HTTP Server (Port 8080) for real-time visualization.
    *   Streams detection overlay for debugging and verification.

---

## ⚙️ Configuration (Environment Variables)

The following environment variables can be set in `.devcontainer/devcontainer.json` or exported in the terminal to tune behavior.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `VEHICLE_INSTANCE_NAME` | `Vehicle` | KUKSA root node name. |
| `CHILD_MODE_MAX_SPEED_KPH` | `30.0` | Max speed allowed before "Speed Exceeded" alerts are fired in Child Mode. |
| `MQTT_BROKER_HOST` | `127.0.0.1` | Address of the HiveMQ broker. |
| `MQTT_BROKER_PORT` | `1883` | Port of the HiveMQ broker. |
| `MQTT_TOPIC_CHILDLOCK_EVENTS` | `ext/safety/childLock/events` | Topic where alerts are published. |

---

## � MQTT API

### **Inputs (Subscribed)**
| Topic | Payload | Description |
| :--- | :--- | :--- |
| `vehicle/childLock/set` | `true`/`false` | Manually toggle Child Mode (Override). |
| `ext/doors/+/unlock` | `"inside"`/`"outside"` | Unlock requests (e.g., `ext/doors/rearLeft/unlock`). |
| `ext/safety/door` | JSON | Aggregate door status from Safety App. |
| `ext/safety/seatbelt` | JSON | Aggregate seatbelt status from Safety App. |

### **Outputs (Published)**

**Topic:** `ext/safety/childLock/events`

**Event: Mode Change**
```json
{ "event": "child_mode_activated", "child_lock_threshold_kph": 30.0 }
```

**Event: Unlock Blocked**
```json
{ "event": "child_mode_blocked_rear_inside_unlock", "door": "REARLEFT" }
```

**Event: Safety Violation**
```json
{ "event": "child_mode_speed_exceeded", "speedKph": 45.5, "limitKph": 30.0 }
```

---

## 🪟 Windows Host Setup (CRITICAL)

Since this feature relies on hardware access (Webcam), Windows users running Docker/WSL must bridge the device manually.

**Prerequisite**: Run these commands in **PowerShell (Administrator)** on your host machine.

### 1. Install USBIPD
```powershell
winget install dorssel.usbipd-win
```
*(Restart your PowerShell window after installation).*

### 2. Identify and Bind Camera
List your USB devices to find your camera (e.g., "Integrated Webcam"):
```powershell
usbipd list
```
Note the **BUSID** (e.g., `1-8` or `2-1`). Then bind it (run once):
```powershell
usbipd bind --busid <YOUR-BUSID>
```

### 3. Attach to WSL
Performs the actual connection to the Linux subsystem. Run this **every time you restart your computer**:
```powershell
usbipd attach --wsl --busid <YOUR-BUSID> --auto-attach
```

---

## 🚀 How to Run

### 1. Rebuild Container (One-time)
Ensure all ML dependencies (`torch`, `opencv`, `pillow`) are installed.
*   In VS Code: Press `F1` -> **Dev Containers: Rebuild Container**.

### 2. Run the Application
Open the integrated terminal in VS Code and run:

```bash
export VEHICLE_INSTANCE_NAME="Vehicle"
python -m safety_monitor_kph.childlock_vapp_main
```

You should see logs indicating the model has loaded:
> `INFO:childlock_vapp:ChildPresenceDetector initialized successfully.`

---

## 📺 Verification (Live Web UI)

To verify the detection logic visually without needing physical child actors constantly:

1.  Keep the app running.
2.  Open your browser to: **[http://localhost:8080](http://localhost:8080)**
3.  Observe the live stream:
    *   **Text Overlay**: Shows `CHILD MODE: ON` (Red) or `CHILD MODE: OFF` (Green).
    *   **Lag?**: The stream uses MJPEG at 640x480 to ensure compatibility with USBIP.

---

## 🐛 Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `No module named 'cv2'` | Missing dependencies | Rebuild the container. |
| `can't open camera by index` | USBIPD not attached | Run the **Step 3** command in PowerShell. |
| `select() timeout` | Bandwidth too high | The app is already configured to force 640x480. Ensure no other app is using the camera. |
| `Permission denied: /dev/video0` | Container permissions | Run `sudo chmod 666 /dev/video0`. |
