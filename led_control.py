#!/usr/bin/env python3
"""
Enhanced Chassis LED Control Tool
Supports state retention, color parsing, and brightness scaling.
"""
import os
import sys
import glob
import json
import argparse
import subprocess

STATE_FILE = "/tmp/led_state.json"

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

COLOR_PRESETS = {
    "white": (255, 255, 255),
    "warm": (255, 180, 100),
    "teal": (37, 194, 160),
    "cyan": (0, 255, 255),
    "green": (51, 209, 122),
    "blue": (0, 100, 255),
    "purple": (192, 140, 255),
    "red": (255, 0, 0),
    "orange": (255, 120, 0)
}

def find_port():
    env_port = os.environ.get("LED_PORT")
    if env_port and os.path.exists(env_port):
        return env_port
    by_id = glob.glob("/dev/serial/by-id/*ZettOS_RGB*")
    if by_id and os.path.exists(by_id[0]):
        return by_id[0]
    for p in ["/dev/ttyACM0", "/host/dev/ttyACM0"]:
        if os.path.exists(p):
            return p
    return None

def get_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"action": "off", "color": "teal", "brightness": 10, "speed": 20}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

def send_frame(mode, r1, g1, b1, r2, g2, b2, speed):
    port = find_port()
    if not port or not os.path.exists(port):
        print(f"Error: Compatible LED port not found.", file=sys.stderr)
        sys.exit(1)

    subprocess.run(["stty", "-F", port, "115200", "cs8", "-cstopb", "-parenb", "raw", "-echo"],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    neg_speed = (-speed) & 0xFF
    payload = bytes([mode, r1, g1, b1, r2, g2, b2, neg_speed])

    crc = 0
    for b in payload:
        crc = CRC_TABLE[crc ^ b]

    frame = bytes([0xFF, 0xFF]) + payload + bytes([crc])

    with open(port, "wb", buffering=0) as f:
        f.write(frame)

def parse_color(c_str):
    c = c_str.lower().lstrip("#")
    if c in COLOR_PRESETS:
        return COLOR_PRESETS[c]
    if len(c) == 6:
        try:
            return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
        except ValueError:
            pass
    return COLOR_PRESETS["teal"]

def main():
    parser = argparse.ArgumentParser(description="Chassis LED Control Tool")
    parser.add_argument("action", nargs="?", default=None,
                        choices=["on", "off", "toggle", "breathe", "flow", "gradient", "status"])
    parser.add_argument("--color", "-c", default=None)
    parser.add_argument("--brightness", "-b", type=int, default=None)
    parser.add_argument("--speed", "-s", type=int, default=None)

    args = parser.parse_args()
    state = get_state()

    if args.action == "status" or (args.action is None and args.color is None and args.brightness is None):
        print(json.dumps(state, indent=2))
        return

    if args.action == "toggle":
        args.action = "off" if state.get("action") != "off" else "on"

    action = args.action or state.get("action", "on")
    color = args.color or state.get("color", "teal")
    brightness = args.brightness if args.brightness is not None else state.get("brightness", 10)
    speed = args.speed if args.speed is not None else state.get("speed", 20)

    if action == "off" or brightness <= 0:
        send_frame(0, 0, 0, 0, 0, 0, 0, 0)
        state["action"] = "off"
        save_state(state)
        print("LED bar is OFF.")
        return

    base_rgb = parse_color(color)
    factor = max(0.0, min(1.0, brightness / 100.0))
    r = int(base_rgb[0] * factor)
    g = int(base_rgb[1] * factor)
    b = int(base_rgb[2] * factor)

    if action == "on":
        send_frame(6, r, g, b, r, g, b, 5)
        print(f"LED ON: {color} at {brightness}% (RGB: {r},{g},{b})")
    elif action == "breathe":
        send_frame(1, r, g, b, 0, 0, 0, speed)
        print(f"LED BREATHE: {color} at {brightness}% (speed: {speed})")
    elif action == "flow":
        send_frame(2, r, g, b, 0, 0, 0, speed)
        print(f"LED FLOW: {color} at {brightness}% (speed: {speed})")
    elif action == "gradient":
        send_frame(4, r, g, b, 0, 20, 40, speed)
        print(f"LED GRADIENT: {color} at {brightness}% (speed: {speed})")

    state.update({"action": action, "color": color, "brightness": brightness, "speed": speed})
    save_state(state)

if __name__ == "__main__":
    main()
