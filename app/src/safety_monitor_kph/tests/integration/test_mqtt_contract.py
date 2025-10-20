import json, time
import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
TOPIC_SB = "ext/safety/seatbelt"
TOPIC_DR = "ext/safety/door"

received = {"seatbelt": [], "door": []}

def on_message(_c, _u, msg):
    data = json.loads(msg.payload.decode())
    if msg.topic == TOPIC_SB:
        received["seatbelt"].append(data)
    elif msg.topic == TOPIC_DR:
        received["door"].append(data)

def test_mqtt_roundtrip_template():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_HOST, 1883, 60)
    client.subscribe([(TOPIC_SB,0), (TOPIC_DR,0)])
    client.loop_start()

    # While this runs, in another terminal use KUKSA CLI:
    # set Vehicle.Speed 10
    # set Cabin.Seat.Row1.DriverSide.Belt.IsFastened false
    # set Cabin.Seat.Row1.DriverSide.Belt.IsFastened true
    time.sleep(5.0)

    client.loop_stop()
    client.disconnect()

    assert any(x for x in received.values()), "No MQTT messages captured; run scenario manually."
    for stream in received.values():
        for msg in stream:
            assert "state" in msg and msg["state"] in ("active","cleared")
            assert "thresholdKph" in msg
