# Beacon: the Arduino UNO Q companion

Beacon sits on the desk of a deaf or hard-of-hearing user. When Samvaad hears their name, or a smoke-alarm-like tone, Beacon vibrates and flashes. It talks to the laptop over Wi-Fi.

## Parts

| Part | Notes |
| --- | --- |
| Arduino UNO Q | The board from the Snapdragon AI Lab kit |
| Coin vibration motor (3 V) | Any small ERM motor |
| NPN transistor (2N2222 or BC547), 1 kΩ resistor, 1N4148 diode | Drives the motor safely from a pin |
| LED and 220 Ω resistor | Any colour; a bright white or amber LED is easiest to notice |

## Wiring

- **D3** → 1 kΩ → transistor base. Transistor emitter → GND. Motor between **3V3** and the collector. Diode across the motor, stripe towards 3V3.
- **D5** → 220 Ω → LED (long leg) → LED short leg → **GND**.

No motor yet? The LED alone works for a first test.

## Install

1. Connect the UNO Q to the same Wi-Fi network as the laptop (Arduino App Lab walks you through this on first start).
2. In **Arduino App Lab**, create a new app called `Samvaad Beacon`.
3. Replace the app's `python/main.py` with [`python/main.py`](python/main.py) and its `sketch/sketch.ino` with [`sketch/sketch.ino`](sketch/sketch.ino).
4. On the laptop, start Samvaad with `.\run.ps1 -Lan` (Windows) or `bash run.sh --lan` (Mac, Linux). It prints a **Beacon address** such as `http://192.168.1.23:8765`. Allow access if the firewall asks (Private networks only on Windows).
5. In `main.py`, set `SAMVAAD_URL` to that address, then press **Run** in App Lab.

Beacon gives one long buzz when it connects, and the Beacon card in Samvaad shows **connected**. Press **Send a test alert** in Samvaad to try it.

## Patterns

| Event | Pattern |
| --- | --- |
| Your name was said | Three short buzzes |
| Alarm-like tone | Fast pulsing for about 2 seconds |
| Test / connected | One long buzz |

## Notes

- This code uses the App Lab Router Bridge (`Bridge.provide` in the sketch, `Bridge.call` in Python). It was written against the documented Bridge pattern and has not yet been run on hardware; if App Lab reports an error, check the pin numbers and the Bridge library name in your App Lab version.
- The board only makes outgoing requests to the laptop, so nothing on the UNO Q is exposed to the network.
