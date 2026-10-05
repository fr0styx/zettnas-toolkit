import colorsys
import glob
import os
import subprocess
import threading
import time

from backend.state import Z_STATE

LED_PORT = os.environ.get("LED_PORT", "/dev/ttyACM0" if os.path.exists("/dev/ttyACM0") else "/host/dev/ttyACM0")

CRC_TABLE = [
    0x00,
    0x07,
    0x0E,
    0x09,
    0x1C,
    0x1B,
    0x12,
    0x15,
    0x38,
    0x3F,
    0x36,
    0x31,
    0x24,
    0x23,
    0x2A,
    0x2D,
    0x70,
    0x77,
    0x7E,
    0x79,
    0x6C,
    0x6B,
    0x62,
    0x65,
    0x48,
    0x4F,
    0x46,
    0x41,
    0x54,
    0x53,
    0x5A,
    0x5D,
    0xE0,
    0xE7,
    0xEE,
    0xE9,
    0xFC,
    0xFB,
    0xF2,
    0xF5,
    0xD8,
    0xDF,
    0xD6,
    0xD1,
    0xC4,
    0xC3,
    0xCA,
    0xCD,
    0x90,
    0x97,
    0x9E,
    0x99,
    0x8C,
    0x8B,
    0x82,
    0x85,
    0xA8,
    0xAF,
    0xA6,
    0xA1,
    0xB4,
    0xB3,
    0xBA,
    0xBD,
    0xC7,
    0xC0,
    0xC9,
    0xCE,
    0xDB,
    0xDC,
    0xD5,
    0xD2,
    0xFF,
    0xF8,
    0xF1,
    0xF6,
    0xE3,
    0xE4,
    0xED,
    0xEA,
    0xB7,
    0xB0,
    0xB9,
    0xBE,
    0xAB,
    0xAC,
    0xA5,
    0xA2,
    0x8F,
    0x88,
    0x81,
    0x86,
    0x93,
    0x94,
    0x9D,
    0x9A,
    0x27,
    0x20,
    0x29,
    0x2E,
    0x3B,
    0x3C,
    0x35,
    0x32,
    0x1F,
    0x18,
    0x11,
    0x16,
    0x03,
    0x04,
    0x0D,
    0x0A,
    0x57,
    0x50,
    0x59,
    0x5E,
    0x4B,
    0x4C,
    0x45,
    0x42,
    0x6F,
    0x68,
    0x61,
    0x66,
    0x73,
    0x74,
    0x7D,
    0x7A,
    0x89,
    0x8E,
    0x87,
    0x80,
    0x95,
    0x92,
    0x9B,
    0x9C,
    0xB1,
    0xB6,
    0xBF,
    0xB8,
    0xAD,
    0xAA,
    0xA3,
    0xA4,
    0xF9,
    0xFE,
    0xF7,
    0xF0,
    0xE5,
    0xE2,
    0xEB,
    0xEC,
    0xC1,
    0xC6,
    0xCF,
    0xC8,
    0xDD,
    0xDA,
    0xD3,
    0xD4,
    0x69,
    0x6E,
    0x67,
    0x60,
    0x75,
    0x72,
    0x7B,
    0x7C,
    0x51,
    0x56,
    0x5F,
    0x58,
    0x4D,
    0x4A,
    0x43,
    0x44,
    0x19,
    0x1E,
    0x17,
    0x10,
    0x05,
    0x02,
    0x0B,
    0x0C,
    0x21,
    0x26,
    0x2F,
    0x28,
    0x3D,
    0x3A,
    0x33,
    0x34,
    0x4E,
    0x49,
    0x40,
    0x47,
    0x52,
    0x55,
    0x5C,
    0x5B,
    0x76,
    0x71,
    0x78,
    0x7F,
    0x6A,
    0x6D,
    0x64,
    0x63,
    0x3E,
    0x39,
    0x30,
    0x37,
    0x22,
    0x25,
    0x2C,
    0x2B,
    0x06,
    0x01,
    0x08,
    0x0F,
    0x1A,
    0x1D,
    0x14,
    0x13,
    0xAE,
    0xA9,
    0xA0,
    0xA7,
    0xB2,
    0xB5,
    0xBC,
    0xBB,
    0x96,
    0x91,
    0x98,
    0x9F,
    0x8A,
    0x8D,
    0x84,
    0x83,
    0xDE,
    0xD9,
    0xD0,
    0xD7,
    0xC2,
    0xC5,
    0xCC,
    0xCB,
    0xE6,
    0xE1,
    0xE8,
    0xEF,
    0xFA,
    0xFD,
    0xF4,
    0xF3,
]

_configured_ports = set()


def find_led_port():
    env_port = os.environ.get("LED_PORT")
    if env_port and os.path.exists(env_port):
        return env_port
    by_ids = glob.glob("/dev/serial/by-id/*ZettOS_RGB*") + glob.glob("/host/dev/serial/by-id/*ZettOS_RGB*")
    for b in by_ids:
        if os.path.exists(b):
            try:
                real = os.path.realpath(b)
                if os.path.exists(real):
                    return real
            except Exception:
                pass
            return b
    for p in ["/dev/ttyACM0", "/host/dev/ttyACM0", LED_PORT]:
        if p and os.path.exists(p):
            return p
    return None


def send_led_packet(mode, r1, g1, b1, r2=0, g2=0, b2=0, speed=5):
    port = find_led_port()
    if not port or not os.path.exists(port):
        return False, f"Device {port or 'ttyACM0'} not found"

    if port not in _configured_ports:
        subprocess.run(
            ["stty", "-F", port, "115200", "cs8", "-cstopb", "-parenb", "raw", "-echo", "-hupcl"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _configured_ports.add(port)

    raw_delay = (-speed) & 0xFF if speed is not None else 0xFB
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
        _configured_ports.discard(port)
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
    hw_delay = max(1, min(255, int(1 + (factor**2.2) * 254)))

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
