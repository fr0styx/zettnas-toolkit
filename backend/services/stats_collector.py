import os
import json
import time
import sqlite3
import traceback
from backend.config import (
    logger, DB_PATH, FAN_STATE_FILE, LED_STATE_FILE,
    get_server_hostname, is_using_default_password
)
from backend.state import Z_STATE, add_event
from backend.hardware.cpu import read_cpu_temp, read_cpu_util
from backend.hardware.memory import read_mem
from backend.hardware.disks import read_disk_temps_and_io
from backend.hardware.fans import read_fans, calc_curve_pwm, apply_zone_pwm, get_hold_remaining, set_fan_pwm
from backend.hardware.led import send_led_packet, apply_led_state
from backend.hardware.screen import get_screen_state, set_screen_brightness, is_in_time_window
from backend.hardware.network import read_network_rates, read_ip
from backend.hardware.storage import read_storage, read_uptime, detect_chassis_model, get_current_layout
from backend.services.copy_engine import read_media_slots

def stats_collector_daemon():
    while True:
        try:
            disks = read_disk_temps_and_io()
            net = read_network_rates()
            bad = [d for d in disks if d.get("health") in ("warn", "crit")]
            has_crit = any(d.get("health") == "crit" for d in disks)
            if has_crit:
                status = f"{len(bad)} ALERT"
            elif bad:
                status = f"{len(bad)} WARN"
            else:
                status = f"{len(disks)} OK"

            cpu_temp = read_cpu_temp()
            fans = read_fans()

            fan_cfg = {"profile": "auto", "manual_pct": 60, "ctrl_cpu_fan": False, "temp_min": 37, "temp_max": 50}
            if os.path.exists(FAN_STATE_FILE):
                try:
                    with open(FAN_STATE_FILE, "r") as f:
                        fan_cfg.update(json.load(f))
                except Exception:
                    pass

            profile = fan_cfg.get("profile", "auto")
            ctrl_cpu_fan = fan_cfg.get("ctrl_cpu_fan", False)
            temp_min = fan_cfg.get("temp_min", 37)
            temp_max = fan_cfg.get("temp_max", 50)

            sata_disks = [d for d in disks if d.get("role") == "data" or d.get("dev", "").startswith("sd")]
            midpoint = max(1, len(sata_disks) // 2)

            zone1_disks = sata_disks[:midpoint]
            zone2_disks = sata_disks[midpoint:]

            active_z1 = [d["temp"] for d in zone1_disks if d.get("temp") is not None and not d.get("standby", False)]
            active_z2 = [d["temp"] for d in zone2_disks if d.get("temp") is not None and not d.get("standby", False)]

            t_zone1 = max(active_z1, default=32)
            t_zone2 = max(active_z2, default=32)

            curve_points = fan_cfg.get("curve_points", None)
            raw_pwm1 = calc_curve_pwm(t_zone1, min_pwm=58, max_pwm=183, temp_min=temp_min, temp_max=temp_max, curve_points=curve_points)
            raw_pwm2 = calc_curve_pwm(t_zone2, min_pwm=58, max_pwm=183, temp_min=temp_min, temp_max=temp_max, curve_points=curve_points)

            if cpu_temp >= 85:
                raw_pwm3 = 183
            elif cpu_temp >= 70:
                raw_pwm3 = 145
            elif cpu_temp >= 55:
                raw_pwm3 = 115
            else:
                raw_pwm3 = 85

            if profile == "auto":
                active_pwm1 = apply_zone_pwm(1, raw_pwm1, hold_secs=120)
                active_pwm2 = apply_zone_pwm(2, raw_pwm2, hold_secs=120)

                custom_pwms = {"pwm1": active_pwm1, "pwm2": active_pwm2}

                if ctrl_cpu_fan:
                    active_pwm3 = apply_zone_pwm(3, raw_pwm3, hold_secs=90)
                    custom_pwms["pwm3"] = active_pwm3
                else:
                    active_pwm3 = 0

                set_fan_pwm("auto", custom_pwms=custom_pwms, ctrl_cpu_fan=ctrl_cpu_fan)
            else:
                pct_map = {"quiet": 67, "balanced": 120, "performance": 155, "full": 183}
                man_pwm = pct_map.get(profile, int((fan_cfg.get("manual_pct", 60) / 100.0) * 183))
                active_pwm1 = man_pwm
                active_pwm2 = man_pwm
                active_pwm3 = man_pwm if ctrl_cpu_fan else 0
                set_fan_pwm(profile, manual_pct=fan_cfg.get("manual_pct", 60), ctrl_cpu_fan=ctrl_cpu_fan)

            # Screen Backlight Management
            screen_cfg = get_screen_state()
            in_screen_night = screen_cfg.get("night_mode", False) and is_in_time_window(screen_cfg.get("night_start", "23:00"), screen_cfg.get("night_end", "07:00"))
            target_bl = screen_cfg.get("night_brightness", 10) if in_screen_night else screen_cfg.get("brightness", 100)
            set_screen_brightness(target_bl)

            # LED Lighting & Schedule
            cfg = {}
            if os.path.exists(LED_STATE_FILE):
                try:
                    with open(LED_STATE_FILE, "r") as f:
                        cfg = json.load(f)
                except Exception:
                    pass

            in_led_night = cfg.get("night_mode", False) and is_in_time_window(cfg.get("night_start", "23:00"), cfg.get("night_end", "07:00"))

            if cfg.get("reactive", True):
                is_failing_fan = any(fans[i] == 0 for i in Z_STATE.known_active_fans if i < len(fans)) if Z_STATE.known_active_fans else False
                is_crit = has_crit or (cpu_temp >= 85) or is_failing_fan
                is_warn = (len(bad) > 0) or (cpu_temp >= 70)

                if is_failing_fan:
                    add_event("error", "Fan Stall Detected", "One or more cooling fans have stalled (0 RPM).", details={"fans": fans})

                if cpu_temp >= 85:
                    add_event("error", "CPU Thermal Critical", f"CPU temperature reached {cpu_temp}°C. Hardware throttling active.", details={"cpu_temp": cpu_temp})
                elif cpu_temp >= 75:
                    add_event("warning", "CPU Thermal Warning", f"CPU temperature is elevated ({cpu_temp}°C).", details={"cpu_temp": cpu_temp})

                for d in bad:
                    d_name = d.get("name", "Unknown")
                    d_health = d.get("health", "warn")
                    d_temp = d.get("temp", 0)
                    if d_health == "crit":
                        add_event("error", f"Drive Critical: {d_name}", f"Drive reached critical health or extreme temp ({d_temp}°C)", details=d)
                    elif d_health == "warn":
                        add_event("warning", f"Drive Warning: {d_name}", f"Drive is running hot or has warnings ({d_temp}°C)", details=d)

                is_disk_active = any(d.get("active", False) for d in disks)
                if is_crit:
                    Z_STATE.alert_active = True
                    send_led_packet(5, 255, 0, 0, 0, 0, 0, speed=10)
                elif Z_STATE.copy_active:
                    Z_STATE.alert_active = True
                    if Z_STATE.copy_status == "copying":
                        send_led_packet(2, 0, 100, 255, 0, 0, 0, speed=20)
                    elif Z_STATE.copy_status == "success":
                        send_led_packet(1, 0, 255, 0, 0, 0, 0, speed=10)
                    elif Z_STATE.copy_status == "error":
                        send_led_packet(5, 255, 0, 0, 0, 0, 0, speed=10)
                elif is_warn:
                    Z_STATE.alert_active = True
                    send_led_packet(1, 255, 120, 0, 0, 0, 0, speed=18)
                elif in_led_night:
                    Z_STATE.alert_active = False
                    send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)
                elif Z_STATE.alert_active:
                    Z_STATE.alert_active = False
                    apply_led_state(cfg)
            elif in_led_night:
                send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)

            disk_hold_rem = max(get_hold_remaining("pwm1", 120), get_hold_remaining("pwm2", 120))
            cpu_hold_rem = get_hold_remaining("pwm3", 90)

            data = {
                "name": get_server_hostname(),
                "status": status,
                "ip": read_ip(),
                "storage": read_storage(),
                "cpu": {"temp": cpu_temp, "util": read_cpu_util()},
                "mem": read_mem(),
                "fans": fans,
                "copy_state": {"active": Z_STATE.copy_active, "status": Z_STATE.copy_status, "progress": Z_STATE.copy_progress},
                "media_slots": read_media_slots(),
                "fan_control": {
                    "zone1_temp": t_zone1,
                    "zone1_pwm": active_pwm1,
                    "zone2_temp": t_zone2,
                    "zone2_pwm": active_pwm2,
                    "cpu_temp": cpu_temp,
                    "cpu_pwm": active_pwm3,
                    "disk_hold_remaining": disk_hold_rem,
                    "cpu_hold_remaining": cpu_hold_rem,
                    "ctrl_cpu_fan": ctrl_cpu_fan,
                    "profile": profile,
                    "temp_min": temp_min,
                    "temp_max": temp_max,
                    "curve_points": fan_cfg.get("curve_points", None)
                },
                "net": net,
                "uptime": read_uptime(),
                "disks": disks,
                "chassis": detect_chassis_model(),
                "layout": get_current_layout(),
                "copy_status": Z_STATE.copy_status,
                "events": list(Z_STATE.event_log),
                "security": {"is_default_password": is_using_default_password()}
            }
            
            with Z_STATE.lock:
                Z_STATE.cached_stats = data
                
            now_ts = int(time.time())
            if not hasattr(stats_collector_daemon, 'last_log'):
                stats_collector_daemon.last_log = 0
            if now_ts - stats_collector_daemon.last_log >= 300:
                stats_collector_daemon.last_log = now_ts
                try:
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute("INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)", (
                            now_ts, data["cpu"].get("temp", 0), data["cpu"].get("util", 0), data["mem"].get("pct", 0), json.dumps(disks), json.dumps(fans)
                        ))
                        conn.execute("DELETE FROM metrics WHERE ts < ?", (now_ts - 2592000,))
                except Exception as db_e:
                    logger.info(f"[ZettNAS] DB Log Error: {db_e}")

        except Exception as e:
            logger.error(f"CRASH in stats collector: {e}")
            traceback.print_exc()

        if Z_STATE.ui_wake.wait(2.0):
            Z_STATE.ui_wake.clear()

def collect():
    with Z_STATE.lock:
        data = dict(Z_STATE.cached_stats) if Z_STATE.cached_stats else {
            "name": get_server_hostname(), "status": "-- OK", "ip": read_ip(),
            "storage": {"used": "0GB", "total": "0GB", "pct": 0}, "cpu": {"temp": 0, "util": 0}, "mem": {"used_gb": 0, "total_gb": 0, "pct": 0},
            "fans": [], "copy_state": {"active": False, "status": "idle", "progress": {}},
            "net": {"tx": "0 B/s", "rx": "0 B/s"}, "uptime": "0s", "disks": []
        }
        data["events"] = list(Z_STATE.event_log)
        data["security"] = {"is_default_password": is_using_default_password()}
    return data

def _old_collect_wrapper():
    return {
        "name": get_server_hostname(),
        "status": "-- OK",
        "ip": read_ip(),
        "storage": {"used": "0GB", "total": "0GB", "pct": 0},
        "cpu": {"temp": 0, "util": 0},
        "mem": {"used_gb": 0, "total_gb": 0, "pct": 0},
        "fans": [],
        "net": {"tx": "0 B/s", "rx": "0 B/s"},
        "uptime": "0s",
        "disks": [],
        "chassis": "D6",
        "layout": None,
        "copy_status": "idle"
    }
