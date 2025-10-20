import os
def get_config() -> dict:
    return {
        "THRESHOLD_KPH": float(os.getenv("SAFETY_SPEED_THRESHOLD_KPH", 5.0)),
        "DEBOUNCE_COUNT": int(os.getenv("SAFETY_DEBOUNCE_COUNT", "2")),
        "TICK_MS": int(os.getenv("SAFETY_TICK_MS", "500")),
        "TOPIC_SEATBELT": os.getenv("TOPIC_SEATBELT", "ext/safety/seatbelt"),
        "TOPIC_DOOR": os.getenv("TOPIC_DOOR", "ext/safety/door"),
    }