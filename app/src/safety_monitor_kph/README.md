# 🚗 Safety Monitor (km/h) — Door & Seatbelt Warning System

---

## 📘 Overview

The **Safety Monitor** feature extends the Eclipse Velocitas Python VehicleApp to monitor and alert when:
- The **vehicle speed** (in km/h) exceeds a defined threshold (default 5 km/h).
- Any **door** is open.
- Any **seatbelt** is unfastened.

When the vehicle moves above the threshold:
- It raises alerts if a door is open or a seatbelt is unfastened.  
- It clears alerts when all doors are closed and all seatbelts are fastened, or when the vehicle stops.

This implementation integrates with:
- **KUKSA Data Broker** for vehicle signals.  
- **MQTT Broker (HiveMQ)** for input and alert messages.  
- **Velocitas VehicleApp framework**, following the Seat Adjuster template pattern.

## 🧩 Implementation Summary

| **Component** | **Description** |
|----------------|----------------|
| **KUKSA Data Broker** | Provides real-time access to `Vehicle.Speed` used to detect motion. |
| **Safety VehicleApp** | Velocitas `VehicleApp` that subscribes to `Vehicle.Speed`, listens to MQTT input topics for doors and seatbelts, and publishes alerts. |
| **MQTT Broker (HiveMQ)** | Handles message exchange between the app and external clients (CLI publishers/subscribers). |
| **CLI Tools** | `hivemq/mqtt-cli` and `kuksa-databroker-cli` simulate inputs and monitor outputs for testing. |

---

## 📁 Repository Structure

```text
app/src/safety_monitor_kph/
│
├── safety_vapp.py              # Core logic for the Safety VehicleApp
├── safety_vapp_main.py         # Entry-point script to launch the app
│
└── README.md                   # Project documentation
```

This layout follows the official Velocitas `vehicle-app-python-template` and keeps the new Safety Monitor lightweight, modular, and easy to extend for future testing.

## ⚙️ Environment Configuration

The Safety Monitor behavior is controlled using environment variables.  
You can modify these before running the app to customize thresholds, debounce counts, and MQTT topic names.

| **Variable** | **Default** | **Description** |
|---------------|-------------|-----------------|
| `VEHICLE_INSTANCE_NAME` | `Vehicle` | Must match the root node in KUKSA Data Broker (`Vehicle.Speed`). |
| `SAFETY_SPEED_THRESHOLD_KPH` | `5.0` | Speed threshold (in km/h) above which the vehicle is considered "moving". |
| `SAFETY_DEBOUNCE_COUNT` | `2` | Number of consecutive evaluations required to confirm a state change (to avoid flicker). |
| `SAFETY_TICK_MS` | `500` | Optional tick interval (in milliseconds) if using periodic evaluation. |
| `TOPIC_SEATBELT` | `ext/safety/seatbelt` | MQTT output topic for seatbelt warning messages. |
| `TOPIC_DOOR` | `ext/safety/door` | MQTT output topic for door warning messages. |

---

## 🧰 Prerequisites

Before running the Safety Monitor, ensure your development environment includes:

- ✅ **Python 3.10+** (preinstalled in Velocitas DevContainer)  
- ✅ **KUKSA Data Broker** running locally (default `127.0.0.1:55555`)  
- ✅ **HiveMQ MQTT Broker** running on port `1883`  
- ✅ **Velocitas SDK dependencies** already included in the base template  

If needed, install `paho-mqtt` manually (used for MQTT communication):

```bash
pip install paho-mqtt
```

These prerequisites match the same setup used by the original Seat Adjuster example — ensuring full compatibility.

## 🚀 How to Run the Safety Monitor

Follow these steps in order to run and test the Safety Monitor VehicleApp.

---

### 1️⃣ Start the Safety VehicleApp

Open a terminal in your project directory and run:

```bash
cd /workspaces/vehicle-app-python-template
export PYTHONPATH="$PWD/app/src:$PYTHONPATH"
export VEHICLE_INSTANCE_NAME="Vehicle"
python -m safety_monitor_kph.safety_vapp_main
```

Expected log output:

```
Subscribing to SELECT Vehicle.Speed
SafetyApp started with threshold_kph=5.0 debounce=2
Mqtt native connection OK!
```

This means the app is running and connected to both KUKSA Data Broker and MQTT Broker.

---

### 2️⃣ Start the KUKSA Data Broker CLI

In a new terminal, start the Data Broker CLI:

```bash
docker run --rm -it --network host \
  -e KUKSA_DATA_BROKER_ADDR=127.0.0.1 \
  -e KUKSA_DATA_BROKER_PORT=55555 \
  ghcr.io/eclipse-kuksa/kuksa-databroker-cli:latest
```

Then at the prompt, simulate the vehicle speed:

```text
publish Vehicle.Speed 10
get Vehicle.Speed
```

This sets the car’s speed to 10 km/h (above the alert threshold).

---

### 3️⃣ Publish Door States (MQTT Input)

Now use the HiveMQ MQTT CLI to simulate door open/close actions:

```bash
# Open front-left door
docker run --rm --network host hivemq/mqtt-cli \
  pub -h 127.0.0.1 -p 1883 \
  -t safety/input/door/frontLeft \
  -m true

# Close front-left door
docker run --rm --network host hivemq/mqtt-cli \
  pub -h 127.0.0.1 -p 1883 \
  -t safety/input/door/frontLeft \
  -m false
```

---

### 4️⃣ Publish Seatbelt States (MQTT Input)

Simulate seatbelt being unfastened or fastened:

```bash
# Unfasten seatbelt (row1, pos1)
docker run --rm --network host hivemq/mqtt-cli \
  pub -h 127.0.0.1 -p 1883 \
  -t safety/input/seatbelt/row1_pos1 \
  -m false

# Fasten seatbelt
docker run --rm --network host hivemq/mqtt-cli \
  pub -h 127.0.0.1 -p 1883 \
  -t safety/input/seatbelt/row1_pos1 \
  -m true
```

---

### 5️⃣ Subscribe to Safety Alerts (Outputs)

To view alert messages, open new terminal(s) and subscribe to the output topics:

```bash
# Door alerts
docker run --rm -it --network host hivemq/mqtt-cli \
  sub -h 127.0.0.1 -p 1883 -t ext/safety/door -v

# Seatbelt alerts
docker run --rm -it --network host hivemq/mqtt-cli \
  sub -h 127.0.0.1 -p 1883 -t ext/safety/seatbelt -v
```

When speed > 5 km/h and a door is open or seatbelt unfastened, you’ll see alerts like:

```json
{"moving": true, "anyOpen": true, "open": ["frontLeft"], "thresholdKph": 5.0, "state": "active"}
{"moving": true, "anyUnfastened": true, "unfastened": ["row1_pos1"], "thresholdKph": 5.0, "state": "active"}
```

When conditions are safe again, “cleared” messages appear.

---

✅ **Tip:**  
If you don’t see alerts immediately, check that:
- `Vehicle.Speed` is greater than the threshold (default 5 km/h).  
- You published the input topic twice or reduced `SAFETY_DEBOUNCE_COUNT` to `1`.

## 📜 Example Log Output

Below is a real run excerpt showing alerts and cleared states in the app logs:

```
INFO [safety_monitor_kph.safety_vapp]: Door active {'moving': True, 'anyOpen': True, 'open': ['frontLeft'], 'thresholdKph': 5.0, 'state': 'active'}
INFO [safety_monitor_kph.safety_vapp]: Door cleared {'moving': True, 'anyOpen': False, 'open': [], 'thresholdKph': 5.0, 'state': 'cleared'}
INFO [safety_monitor_kph.safety_vapp]: Seatbelt active {'moving': True, 'anyUnfastened': True, 'unfastened': ['row1_pos1'], 'thresholdKph': 5.0, 'state': 'active'}
INFO [safety_monitor_kph.safety_vapp]: Seatbelt cleared {'moving': True, 'anyUnfastened': False, 'unfastened': [], 'thresholdKph': 5.0, 'state': 'cleared'}
```

## 🏁 Summary

This Safety Monitor extension:
- Subscribes to real vehicle speed from the **KUKSA Data Broker**.  
- Uses **MQTT topics** for door and seatbelt input/output alerts.  
- Implements **debounce, threshold, and configurable logic** for accurate testing.  
