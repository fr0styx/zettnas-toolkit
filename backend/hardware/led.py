import os
import glob
import time
import colorsys
import subprocess
import threading
from backend.config import logger
from backend.state import Z_STATE

LED_PORT = os.environ.get("LED_PORT", "/dev/ttyACM0" if os.path.exists("/dev/ttyACM0") else "/host/dev/ttyACM0")

CRC_TABLE = [
    0x00, 0x07, 0x0e, 0x09, 0x1c, 0x1b, 0x12, 0x15, 0x38, 0x3f, 0x36, 0x31, 0x24, 0x23, 0x2a, 0x2d,
    0x70, 0x77, 0x7e, 0x79, 0x6c, 0x6b, 0x62, 0x65, 0x48, 0x4f, 0x46, 0x41, 0x54, 0x53, 0x5a, 0x5d,
    0xe0, 0xe7, 0xee, 0xe9, 0xfc, 0xfb, 0xf2, 0xf5, 0xd8, 0xdf, 0xd6, 0xd1, 0xc4, 0xc3, 0xca, 0xcd,
    0x90, 0x97, 0x9e, 0x99, 0x8c, 0x8b, 0x82, 0x85, 0xa8, 0xaf, 0xa6, 0xa1, 0xb4, 0xb3, 0xba, 0xbd,
    0xc7, 0xc0, 0xc9, 0xce, 0xdb, 0xdc, 0xd5, 0xd2, 0xff, 0xf8, 0xf1, 0xf6, 0xe3, 0xe4, 0xed, 0xea,
    0xb7, 0xb0, 0xb9, 0xbe, 0xab, 0xac, 0xa5, 0xa2, 0x8f, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9d, 0x9a,
    0x27, 0x20, 0x29, 0x2e, 0x3b, 0x3c, 0x35, 0x32, 0x1f, 0x18, 0x11, 0x16, 0x03, 0x04, 0x0d, 0x0a,
    0x57, 0x50, 0x59, 0x5e, 0x4b, 0x4c, 0x45, 0x42, 0x6f, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7d, 0x7a,
    0x89, 0x8e, 0x87, 0x80, 0x95, 0x92, 0x9b, 0x9c, 0xb1, 0xb6, 0xbf, 0xb8, 0xad, 0xaa, 0xa3, 0xa4,
    0xf9, 0xfe, 0xf7, 0xf0, 0xe5, 0xe2, 0xeb, 0xec, 0xc1, 0xc6, 0xcf, 0xc8, 0xdd, 0xda, 0xd3, 0xd4,
    0x69, 0x6e, 0x67, 0x60, 0x75, 0x72, 0x7b, 0x7c, 0x51, 0x56, 0x5f, 0x58, 0x4d, 0x4a, 0x43, 0x44,
    0x19, 0x1e, 0x17, 0x10, 0x05, 0x02, 0x0b, 0x0c, 0x21, 0x26, 0x2f, 0x28, 0x3d, 0x3a, 0x33, 0x34,
    0x4e, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5c, 0x5b, 0x76, 0x71, 0x78, 0x7f, 0x6a, 0x6d, 0x64, 0x63,
    0x3e, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2c, 0x2b, 0x06, 0x01, 0x08, 0x0f, 0x1a, 0x1d, 0x14, 0x13,
    0xae, 0xa9, 0xa0, 0xa7, 0xb2, 0xb5, 0xbc, 0xbb, 0x96, 0x91, 0x98, 0x9f, 0x8a, 0x8d, 0x84, 0x83,
    0xde, 0xd9, 0xd0, 0xd7, 0xc2, 0xc5, 0xcc, 0xcb, 0xe6, 0xe1, 0xe8, 0xef, 0xfa, 0xfd, 0xf4, 0xf3
]

def send_led_packet(mode, r1, g1, b1, r2=0, g2=0, b2=0, speed=5):
    port = LED_PORT
    by_id = glob.glob("/dev/serial/by-id/*ZettOS_RGB*")
    if by_id and os.path.exists(by_id[0]):
        port = by_id[0]
    elif os.path.exists(LED_PORT):
        port = LED_PORT
    elif os.path.exists("/dev/ttyACM0"):
        port = "/dev/ttyACM0"
    elif os.path.exists("/host/dev/ttyACM0"):
        port = "/host/dev/ttyACM0"

    if not os.path.exists(port):
        return False, f"Device {port} not found"

    subprocess.run(["stty", "-F", port, "115200", "cs8", "-cstopb", "-parenb", "raw", "-echo"],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raw_delay = max(1, min(255, int(speed))) & 0xFF
    payload = bytes([mode, r1, g1, b1, r2, g2, b2, raw_delay])
    crc = 0
    for byte in payload:
        crc = CRC_TABLE[crc ^ byte]
    frame = bytes([0xFF, 0xFF]) + payload + bytes([crc])
    try:
        with open(port, "wb", buffering=0) as f:
            f.write(frame)
        return True, "OK"
    except Exception as e:
        return False, str(e)

def _rainbow_worker(brightness, slider_speed):
    hue = 0.0
    interval = max(0.04, 0.16 - (slider_speed / 100.0) * 0.12)
    while not Z_STATE.rainbow_stop.is_set():
        r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        scale = brightness / 100.0
        r = int(r_f * 255 * scale)
        g = int(g_f * 255 * scale)
        b = int(b_f * 255 * scale)
        send_led_packet(6, r, g, b, r, g, b, speed=5)
        hue = (hue + 0.015) % 1.0
        time.sleep(interval)

def apply_led_state(data):
    Z_STATE.rainbow_stop.set()
    if Z_STATE.rainbow_thread and Z_STATE.rainbow_thread.is_alive():
        Z_STATE.rainbow_thread.join(timeout=0.4)

    power = data.get("power", "on")
    brightness = int(data.get("brightness", 25))
    color_hex = data.get("color", "25c2a0").lstrip("#")
    color2_hex = data.get("color2", "ff0055").lstrip("#")
    effect = data.get("mode", "solid")
    slider_speed = max(1, min(100, int(data.get("speed", 50))))

    if power == "off" or brightness <= 0:
        return send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)

    if effect == "rainbow":
        Z_STATE.rainbow_stop.clear()
        Z_STATE.rainbow_thread = threading.Thread(target=_rainbow_worker, args=(brightness, slider_speed), daemon=True)
        Z_STATE.rainbow_thread.start()
        return True, "Rainbow Active"

    factor = (100 - slider_speed) / 99.0
    hw_delay = max(1, min(255, int(1 + (factor ** 2.2) * 254)))

    r_raw = int(color_hex[0:2], 16)
    g_raw = int(color_hex[2:4], 16)
    b_raw = int(color_hex[4:6], 16)
    scale = brightness / 100.0
    r = max(0, min(255, int(r_raw * scale)))
    g = max(0, min(255, int(g_raw * scale)))
    b = max(0, min(255, int(b_raw * scale)))

    if len(color2_hex) >= 6:
        r2_raw = int(color2_hex[0:2], 16)
        g2_raw = int(color2_hex[2:4], 16)
        b2_raw = int(color2_hex[4:6], 16)
    else:
        r2_raw, g2_raw, b2_raw = 255, 0, 85

    r2 = max(0, min(255, int(r2_raw * scale)))
    g2 = max(0, min(255, int(g2_raw * scale)))
    b2 = max(0, min(255, int(b2_raw * scale)))

    if effect == "breathe":
        return send_led_packet(1, r, g, b, 0, 0, 0, speed=hw_delay)
    elif effect == "flow":
        return send_led_packet(2, r, g, b, 0, 0, 0, speed=hw_delay)
    elif effect == "chase":
        return send_led_packet(3, r, g, b, 0, 0, 0, speed=hw_delay)
    elif effect == "gradient":
        return send_led_packet(4, r, g, b, r2, g2, b2, speed=hw_delay)
    elif effect == "flashing":
        return send_led_packet(5, r, g, b, 0, 0, 0, speed=hw_delay)
    else:
        return send_led_packet(6, r, g, b, r, g, b, speed=5)
