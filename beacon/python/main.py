"""Samvaad Beacon, Linux side of the Arduino UNO Q (runs in Arduino App Lab).

Long-polls the Samvaad laptop over Wi-Fi for events (name heard, alarm, test) and
asks the microcontroller to vibrate and flash. The laptop never connects to the
board, so no port needs opening here.

Set SAMVAAD_URL below to the "Beacon address" that Samvaad prints when started
with  .\\run.ps1 -Lan  or  bash run.sh --lan  (for example http://192.168.1.23:8765).
"""

import json
import os
import time
import urllib.request

from arduino.app_utils import App, Bridge

SAMVAAD_URL = os.environ.get("SAMVAAD_URL", "http://192.168.1.23:8765")

# Vibration/light pattern per event kind; the sketch defines what each number does.
PATTERNS = {"name": 1, "alarm": 2, "test": 3}

last_id = 0
connected = False


def loop():
    global last_id, connected
    try:
        with urllib.request.urlopen(f"{SAMVAAD_URL}/api/beacon/poll?since={last_id}", timeout=35) as reply:
            events = json.load(reply).get("events", [])
        if not connected:
            connected = True
            print(f"Beacon: connected to Samvaad at {SAMVAAD_URL}")
            Bridge.call("alert", 3)  # one long pulse says "connected"
        for event in events:
            last_id = max(last_id, int(event["id"]))
            print(f"Beacon: {event['title']} ({event.get('detail', '')})")
            Bridge.call("alert", PATTERNS.get(event.get("kind"), 3))
    except Exception as err:  # laptop asleep, Wi-Fi down, Samvaad not running with -Lan
        if connected:
            print(f"Beacon: lost Samvaad ({err}); retrying")
        else:
            print(f"Beacon: waiting for Samvaad at {SAMVAAD_URL} ({err})")
        connected = False
        time.sleep(3)


App.run(user_loop=loop)
