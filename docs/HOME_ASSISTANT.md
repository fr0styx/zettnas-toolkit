# Home Assistant

Kiboto can show its health in Home Assistant as sensors, through the MQTT broker Home Assistant
already uses (usually the Mosquitto add-on). Nothing is installed in Home Assistant: the sensors
appear on their own under **Settings → Devices & services → MQTT**, grouped as one device named
after the NAS.

## Set it up

1. In Home Assistant, make sure the MQTT integration is set up and note the broker's address, port
   (1883, or 8883 with TLS) and a user for Kiboto.
2. In Kiboto: **Mission Control → Network → File Sharing Services → Home Assistant**. Enter the
   broker, the user and its password, then **Send now** to check. Turn it **On** to keep sending.

Kiboto connects once a minute, sends the values and disconnects. The first send after a start also
announces the sensors (MQTT discovery, under the `homeassistant/` prefix). If the updates stop, Home
Assistant marks the sensors unavailable after three minutes instead of showing an old value.

## Sensors

| Sensor | Unit |
|---|---|
| CPU usage, memory usage | % |
| CPU temperature, each disk's temperature, the hottest disk | °C |
| UPS battery, UPS load | % |
| UPS time left | min |
| UPS on battery | on/off |
| Ransomware guard froze writes | on/off (a problem) |

The values are published retained on `kiboto/<nas-name>/state`, one JSON message, so automations
can also read them directly. The broker password is stored encrypted in Kiboto's data folder.
