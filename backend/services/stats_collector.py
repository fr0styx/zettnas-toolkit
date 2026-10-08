import concurrent.futures
import json
import os
import sqlite3
import time
import traceback

from backend.config import (
    DB_PATH,
    ENABLE_FB,
    FAN_MAX_PWM,
    FAN_MIN_PWM,
    FAN_SPINUP_GRACE_SECS,
    FAN_STATE_FILE,
    CLIENT_PREFS_FILE,
    FAN_ZERO_RPM_DEFAULT_NVME_CEILING,
    FAN_ZERO_RPM_DEFAULT_START_TEMP,
    FAN_ZERO_RPM_DEFAULT_STOP_TEMP,
    FAN_ZERO_RPM_STOP_DELAY,
    HDD_CRITICAL_TEMP,
    LED_STATE_FILE,
    NVME_CRITICAL_TEMP,
    get_server_hostname,
    is_using_default_password,
    logger,
)
from backend.db import log_metrics
from backend.fsutil import read_json
from backend.hardware.cpu import read_cpu_temp, read_cpu_util
from backend.hardware.disks import poll_all_disks_smart, read_disk_temps_and_io
from backend.hardware.fans import apply_zone_pwm, calc_curve_pwm, get_hold_remaining, read_fans, set_fan_pwm
from backend.hardware.led import apply_led_state, find_led_port, send_led_packet
from backend.hardware.memory import read_mem
from backend.hardware.network import read_ip, read_network_rates
from backend.hardware.screen import get_screen_state, is_in_time_window, set_screen_brightness
from backend.hardware.storage import detect_chassis_model, get_current_layout, read_storage, read_uptime
from backend.hardware.unraid import read_unraid_status
from backend.hardware.docker_stats import read_docker_containers
from backend.hardware.ups import read_ups_status
from backend.services.broadcaster import broadcaster
from backend.services.copy_engine import check_media_slot_transitions, read_media_slots
from backend.services.notifications import send_notification
from backend.state import Z_STATE, add_event
from backend.services.alert_rules import evaluate_system_alerts

_notify_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="zett_notify")


def _async_notify(**kwargs):
    """Dispatches notifications on a worker thread so slow webhooks never stall PWM fan loop updates."""
    try:
        _notify_executor.submit(send_notification, **kwargs)
    except Exception as e:
        logger.warning(f"[NOTIFY] Failed to queue async notification: {e}")


def stats_collector_daemon():
    while True:
        Z_STATE.collector_heartbeat = time.time()
        try:
            disks = read_disk_temps_and_io()
            net = read_network_rates()

            # Auto-cycle LCD page if interval configured
            if Z_STATE.lcd_cycle_seconds > 0:
                if (time.time() - Z_STATE.last_lcd_cycle_time) >= Z_STATE.lcd_cycle_seconds:
                    Z_STATE.cycle_lcd_page()

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

            fan_cfg = {
                "profile": "auto",
                "manual_pct": 60,
                "ctrl_cpu_fan": False,
                "temp_min": 37,
                "temp_max": 50,
                "zero_rpm_enabled": False,
                "zero_rpm_nvme_ceiling": FAN_ZERO_RPM_DEFAULT_NVME_CEILING,
                "zero_rpm_stop_temp": FAN_ZERO_RPM_DEFAULT_STOP_TEMP,
                "zero_rpm_start_temp": FAN_ZERO_RPM_DEFAULT_START_TEMP,
            }
            loaded_fan_cfg = read_json(FAN_STATE_FILE, {})
            if isinstance(loaded_fan_cfg, dict):
                fan_cfg.update(loaded_fan_cfg)

            profile = fan_cfg.get("profile", "auto")
            ctrl_cpu_fan = fan_cfg.get("ctrl_cpu_fan", False)
            temp_min = fan_cfg.get("temp_min", 37)
            temp_max = fan_cfg.get("temp_max", 50)
            zero_rpm_enabled = fan_cfg.get("zero_rpm_enabled", False)
            zero_rpm_nvme_ceiling = fan_cfg.get("zero_rpm_nvme_ceiling", FAN_ZERO_RPM_DEFAULT_NVME_CEILING)
            zero_rpm_stop_temp = fan_cfg.get("zero_rpm_stop_temp", FAN_ZERO_RPM_DEFAULT_STOP_TEMP)
            zero_rpm_start_temp = fan_cfg.get("zero_rpm_start_temp", FAN_ZERO_RPM_DEFAULT_START_TEMP)

            # Chassis Topology Resolution
            chassis_model = detect_chassis_model()
            sata_disks = [d for d in disks if d.get("role") == "data" or d.get("dev", "").startswith("sd")]

            if chassis_model == "d4" or len(sata_disks) <= 4:
                # ZettLab D4: Single exhaust fan (pwm1) cools ALL 4 bays
                zone1_disks = sata_disks
                zone2_disks = []
            else:
                # ZettLab D6U / D8: Dual fan split across Zone 1 (pwm1) and Zone 2 (pwm2)
                midpoint = max(1, len(sata_disks) // 2)
                zone1_disks = sata_disks[:midpoint]
                zone2_disks = sata_disks[midpoint:]

            # Standby state per zone
            if not sata_disks:
                # All-flash array (no mechanical SATA drives installed)
                # Zero RPM is permitted if NVMe is cold and storage is not busy
                z1_all_standby = True
                z2_all_standby = True
            else:
                z1_all_standby = bool(zone1_disks) and all(d.get("standby", False) for d in zone1_disks)
                # If zone2 has no disks installed (under-populated chassis), inherit zone1 standby
                z2_all_standby = all(d.get("standby", False) for d in zone2_disks) if zone2_disks else z1_all_standby

            # Active temperatures per zone (sleeping disks' cached temps are ignored unless critical >= 55)
            active_z1 = [d["temp"] for d in zone1_disks if d.get("temp") is not None and not d.get("standby", False)]
            active_z2 = [d["temp"] for d in zone2_disks if d.get("temp") is not None and not d.get("standby", False)]

            t_zone1 = max(active_z1, default=30)
            t_zone2 = max(active_z2, default=30)

            # NVMe Drives & Wind Tunnel Cooling Override
            nvme_disks = [d for d in disks if d.get("role") == "cache" or "nvme" in d.get("dev", "")]
            active_nvme = [d["temp"] for d in nvme_disks if d.get("temp") is not None and not d.get("standby", False)]
            t_nvme = max(active_nvme, default=None)
            nvme_over_ceiling = t_nvme is not None and t_nvme >= zero_rpm_nvme_ceiling

            # Unraid Storage Subsystem Interlocks (Parity Check & Mover)
            unraid_status = read_unraid_status()
            mover_active = bool(unraid_status.get("mover", {}).get("active", False))
            parity_active = bool(unraid_status.get("parity_check", {}).get("active", False))
            storage_busy = mover_active or parity_active

            curve_points = fan_cfg.get("curve_points", None)
            zone1_curve = fan_cfg.get("zone1_curve_points") or curve_points
            zone2_curve = fan_cfg.get("zone2_curve_points") or curve_points
            nvme_curve = fan_cfg.get("nvme_curve_points", None)
            cpu_curve = fan_cfg.get("cpu_curve_points", None)

            raw_pwm1 = calc_curve_pwm(
                t_zone1,
                min_pwm=FAN_MIN_PWM,
                max_pwm=FAN_MAX_PWM,
                temp_min=temp_min,
                temp_max=temp_max,
                curve_points=zone1_curve,
                allow_zero=zero_rpm_enabled,
            )
            raw_pwm2 = calc_curve_pwm(
                t_zone2,
                min_pwm=FAN_MIN_PWM,
                max_pwm=FAN_MAX_PWM,
                temp_min=temp_min,
                temp_max=temp_max,
                curve_points=zone2_curve,
                allow_zero=zero_rpm_enabled,
            )

            if nvme_curve and t_nvme is not None:
                raw_nvme_pwm = calc_curve_pwm(
                    t_nvme,
                    min_pwm=FAN_MIN_PWM,
                    max_pwm=FAN_MAX_PWM,
                    temp_min=temp_min,
                    temp_max=temp_max,
                    curve_points=nvme_curve,
                    allow_zero=False,
                )
                raw_pwm1 = max(raw_pwm1, raw_nvme_pwm)
                raw_pwm2 = max(raw_pwm2, raw_nvme_pwm)
            elif t_nvme is not None and t_nvme >= 50:
                # Default NVMe thermal wind-tunnel ramp if no custom curve configured:
                # 50°C -> 95 PWM (~50%), 65°C -> 145 PWM (~80%), 75°C -> MAX_PWM (100%)
                ratio = min(1.0, max(0.0, (t_nvme - 50.0) / 25.0))
                default_nvme_pwm = int(95 + ratio * (FAN_MAX_PWM - 95))
                raw_pwm1 = max(raw_pwm1, default_nvme_pwm)
                raw_pwm2 = max(raw_pwm2, default_nvme_pwm)

            if cpu_curve:
                raw_pwm3 = calc_curve_pwm(
                    cpu_temp,
                    min_pwm=FAN_MIN_PWM,
                    max_pwm=FAN_MAX_PWM,
                    temp_min=50,
                    temp_max=85,
                    curve_points=cpu_curve,
                    allow_zero=False,
                )
            elif cpu_temp >= 85:
                raw_pwm3 = FAN_MAX_PWM
            elif cpu_temp >= 70:
                raw_pwm3 = 145
            elif cpu_temp >= 55:
                raw_pwm3 = 115
            else:
                raw_pwm3 = 85

            # Safety override: any spinning or solid state disk at/above its critical temperature,
            # or CPU at/above 85°C, forces fans to 100% regardless of profile or curve.
            hot_disks = []
            for d in disks:
                t = d.get("temp")
                if t is not None and not d.get("standby", False):
                    is_nvme = (
                        d.get("is_nvme", False)
                        or d.get("dev", "").startswith("nvme")
                        or d.get("name", "").startswith("nv")
                    )
                    crit_thresh = NVME_CRITICAL_TEMP if is_nvme else HDD_CRITICAL_TEMP
                    if t >= crit_thresh:
                        hot_disks.append((d, crit_thresh))

            cpu_critical = cpu_temp is not None and cpu_temp >= 85
            critical_override = bool(hot_disks) or cpu_critical
            if critical_override and not Z_STATE.critical_temp_active:
                reasons = []
                if hot_disks:
                    reasons.append(
                        ", ".join(
                            f"{d.get('name', d.get('dev', '?'))} ({d['temp']}°C >= {thresh}°C)"
                            for d, thresh in hot_disks
                        )
                    )
                if cpu_critical:
                    reasons.append(f"CPU ({cpu_temp}°C >= 85°C)")
                names = "; ".join(reasons)
                logger.warning(f"[FANS] Critical temperature detected: {names}. Forcing fans to 100%.")
                add_event(
                    "error",
                    "Critical Temperature Threshold Reached",
                    f"{names}. Fans forced to 100%.",
                    details={"cpu_temp": cpu_temp, "disks": [d.get("dev") for d, _ in hot_disks]},
                )
            elif not critical_override and Z_STATE.critical_temp_active:
                logger.info("[FANS] Hardware temperatures back below critical threshold.")
            Z_STATE.critical_temp_active = critical_override

            # Continuous Anti-Flutter Gating for Zero RPM
            now = time.time()
            zero_rpm_cfg_enabled = bool(zero_rpm_enabled and profile == "auto")

            z1_eligible = bool(
                zero_rpm_cfg_enabled
                and not critical_override
                and not storage_busy
                and z1_all_standby
                and t_zone1 <= zero_rpm_stop_temp
                and not nvme_over_ceiling
            )

            z2_eligible = bool(
                zero_rpm_cfg_enabled
                and not critical_override
                and not storage_busy
                and z2_all_standby
                and t_zone2 <= zero_rpm_stop_temp
                and not nvme_over_ceiling
            )

            st1 = Z_STATE.fan_state_tracker.setdefault(
                "pwm1",
                {
                    "current": 67,
                    "last_up_time": 0.0,
                    "kickstart_until": 0.0,
                    "last_spinup_time": now,
                    "standby_since": 0.0,
                },
            )
            if z1_eligible:
                if st1.get("standby_since", 0.0) == 0.0:
                    st1["standby_since"] = now
            else:
                st1["standby_since"] = 0.0

            st2 = Z_STATE.fan_state_tracker.setdefault(
                "pwm2",
                {
                    "current": 67,
                    "last_up_time": 0.0,
                    "kickstart_until": 0.0,
                    "last_spinup_time": now,
                    "standby_since": 0.0,
                },
            )
            if z2_eligible:
                if st2.get("standby_since", 0.0) == 0.0:
                    st2["standby_since"] = now
            else:
                st2["standby_since"] = 0.0

            z1_zero_rpm_ready = bool(
                z1_eligible
                and st1.get("standby_since", 0.0) > 0.0
                and (now - st1["standby_since"]) >= FAN_ZERO_RPM_STOP_DELAY
            )
            z2_zero_rpm_ready = bool(
                z2_eligible
                and st2.get("standby_since", 0.0) > 0.0
                and (now - st2["standby_since"]) >= FAN_ZERO_RPM_STOP_DELAY
            )

            if critical_override:
                raw_pwm1 = raw_pwm2 = FAN_MAX_PWM
                active_pwm1 = apply_zone_pwm(1, FAN_MAX_PWM, hold_secs=120, allow_zero=False)
                active_pwm2 = apply_zone_pwm(2, FAN_MAX_PWM, hold_secs=120, allow_zero=False)
                custom_pwms = {"pwm1": active_pwm1, "pwm2": active_pwm2}
                if ctrl_cpu_fan:
                    active_pwm3 = apply_zone_pwm(3, FAN_MAX_PWM, hold_secs=90, allow_zero=False)
                    custom_pwms["pwm3"] = active_pwm3
                else:
                    active_pwm3 = 0
                set_fan_pwm("auto", custom_pwms=custom_pwms, ctrl_cpu_fan=ctrl_cpu_fan, zero_rpm_allowed=False)
            elif profile == "auto":
                target_pwm1 = 0 if z1_zero_rpm_ready else max(FAN_MIN_PWM, raw_pwm1)
                target_pwm2 = 0 if z2_zero_rpm_ready else max(FAN_MIN_PWM, raw_pwm2)

                allow_zero_z1 = z1_zero_rpm_ready
                allow_zero_z2 = z2_zero_rpm_ready

                active_pwm1 = apply_zone_pwm(1, target_pwm1, hold_secs=120, allow_zero=allow_zero_z1)
                active_pwm2 = apply_zone_pwm(2, target_pwm2, hold_secs=120, allow_zero=allow_zero_z2)

                custom_pwms = {"pwm1": active_pwm1, "pwm2": active_pwm2}

                if ctrl_cpu_fan:
                    active_pwm3 = apply_zone_pwm(3, raw_pwm3, hold_secs=90, allow_zero=False)
                    custom_pwms["pwm3"] = active_pwm3
                else:
                    active_pwm3 = 0

                set_fan_pwm(
                    "auto",
                    custom_pwms=custom_pwms,
                    ctrl_cpu_fan=ctrl_cpu_fan,
                    zero_rpm_allowed=(allow_zero_z1 or allow_zero_z2),
                )
            else:
                pct_map = {"quiet": 67, "balanced": 120, "performance": 155, "full": FAN_MAX_PWM}
                man_pwm = pct_map.get(profile, int((fan_cfg.get("manual_pct", 60) / 100.0) * FAN_MAX_PWM))
                man_pwm = max(FAN_MIN_PWM, min(FAN_MAX_PWM, man_pwm))
                active_pwm1 = apply_zone_pwm(1, man_pwm, hold_secs=120, allow_zero=False)
                active_pwm2 = apply_zone_pwm(2, man_pwm, hold_secs=120, allow_zero=False)
                active_pwm3 = apply_zone_pwm(3, man_pwm, hold_secs=90, allow_zero=False) if ctrl_cpu_fan else 0
                custom_pwms = {"pwm1": active_pwm1, "pwm2": active_pwm2}
                if ctrl_cpu_fan:
                    custom_pwms["pwm3"] = active_pwm3
                set_fan_pwm(
                    profile,
                    manual_pct=fan_cfg.get("manual_pct", 60),
                    custom_pwms=custom_pwms,
                    ctrl_cpu_fan=ctrl_cpu_fan,
                    zero_rpm_allowed=False,
                )

            # Screen Backlight Management
            screen_cfg = get_screen_state()
            in_screen_night = screen_cfg.get("night_mode", False) and is_in_time_window(
                screen_cfg.get("night_start", "23:00"), screen_cfg.get("night_end", "07:00")
            )
            target_bl = screen_cfg.get("night_brightness", 10) if in_screen_night else screen_cfg.get("brightness", 100)
            set_screen_brightness(target_bl)

            # LED Lighting & Schedule
            cfg = read_json(LED_STATE_FILE, {})
            if not isinstance(cfg, dict):
                cfg = {}

            in_led_night = cfg.get("night_mode", False) and is_in_time_window(
                cfg.get("night_start", "23:00"), cfg.get("night_end", "07:00")
            )

            if cfg.get("reactive", True):
                stalled_fans = []
                for i in Z_STATE.known_active_fans:
                    if i >= len(fans):
                        continue
                    rpm = fans[i]
                    if rpm == 0:
                        pwm_key = f"pwm{i + 1}"
                        st = Z_STATE.fan_state_tracker.get(pwm_key, {})
                        cmd_pwm = st.get("current", 67)
                        last_spinup = st.get("last_spinup_time", 0.0)
                        # Suppress stall alert if the fan is commanded to 0 RPM (passive Zero RPM mode)
                        # OR if it is within the 6.0-second spinup grace window
                        is_suppressed = (cmd_pwm == 0) or ((now - last_spinup) < FAN_SPINUP_GRACE_SECS)
                        if not is_suppressed:
                            stalled_fans.append(i)

                is_failing_fan = bool(stalled_fans)
                is_crit = has_crit or (cpu_temp >= 85) or is_failing_fan
                is_warn = (len(bad) > 0) or (cpu_temp >= 70)

                if is_failing_fan:
                    stalled_names = [f"pwm{idx + 1}" for idx in stalled_fans]
                    add_event(
                        "error",
                        "Fan Stall Detected",
                        f"One or more cooling fans have stalled (0 RPM): channels {stalled_names}.",
                        details={"fans": fans, "stalled_channels": stalled_names},
                    )
                    _async_notify(
                        title="ZettNAS Alert: Fan Stall Detected",
                        message=f"Cooling fan stall detected on channels {stalled_names}.",
                        level="critical",
                        event_type="fan",
                        dedup_key="fan_stall",
                    )

                if cpu_temp >= 85:
                    add_event(
                        "error",
                        "CPU Thermal Critical",
                        f"CPU temperature reached {cpu_temp}°C. Hardware throttling active.",
                        details={"cpu_temp": cpu_temp},
                    )
                    _async_notify(
                        title="ZettNAS Alert: CPU Thermal Critical",
                        message=f"CPU temperature reached critical level: {cpu_temp}°C!",
                        level="critical",
                        event_type="temp",
                        dedup_key="cpu_temp_crit",
                    )
                elif cpu_temp >= 75:
                    add_event(
                        "warning",
                        "CPU Thermal Warning",
                        f"CPU temperature is elevated ({cpu_temp}°C).",
                        details={"cpu_temp": cpu_temp},
                    )
                    _async_notify(
                        title="ZettNAS Warning: CPU Thermal Elevated",
                        message=f"CPU temperature is elevated at {cpu_temp}°C.",
                        level="warning",
                        event_type="temp",
                        dedup_key="cpu_temp_warn",
                    )

                for d in bad:
                    d_name = d.get("name", "Unknown")
                    d_health = d.get("health", "warn")
                    d_temp = d.get("temp", 0)
                    if d_health == "crit":
                        add_event(
                            "error",
                            f"Drive Critical: {d_name}",
                            f"Drive reached critical health or extreme temp ({d_temp}°C)",
                            details=d,
                        )
                        _async_notify(
                            title=f"ZettNAS Alert: Drive Critical ({d_name})",
                            message=f"Drive {d_name} has entered CRITICAL state ({d_temp}°C). Inspect S.M.A.R.T. health immediately.",
                            level="critical",
                            event_type="smart",
                            dedup_key=f"drive_crit_{d_name}",
                        )
                    elif d_health == "warn":
                        add_event(
                            "warning",
                            f"Drive Warning: {d_name}",
                            f"Drive is running hot or has warnings ({d_temp}°C)",
                            details=d,
                        )
                        _async_notify(
                            title=f"ZettNAS Warning: Drive Alert ({d_name})",
                            message=f"Drive {d_name} is running hot or reported S.M.A.R.T. warnings ({d_temp}°C).",
                            level="warning",
                            event_type="smart",
                            dedup_key=f"drive_warn_{d_name}",
                        )

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

            events_list = list(Z_STATE.event_log)
            docker_list = read_docker_containers()

            if not hasattr(stats_collector_daemon, "_last_events_ts"):
                stats_collector_daemon._last_events_ts = 0
                stats_collector_daemon._last_events_count = -1
                stats_collector_daemon._last_docker_summary = None

            top_event_ts = events_list[0].get("ts", 0) if events_list else 0
            events_count = len(events_list)
            events_changed = (
                top_event_ts != stats_collector_daemon._last_events_ts
                or events_count != stats_collector_daemon._last_events_count
            )
            if events_changed:
                stats_collector_daemon._last_events_ts = top_event_ts
                stats_collector_daemon._last_events_count = events_count

            docker_summary = tuple((c.get("id"), c.get("state")) for c in docker_list)
            docker_changed = docker_summary != stats_collector_daemon._last_docker_summary
            if docker_changed:
                stats_collector_daemon._last_docker_summary = docker_summary

            data = {
                "name": get_server_hostname(),
                "status": status,
                "ip": read_ip(),
                "storage": read_storage(),
                "cpu": {"temp": cpu_temp, "util": read_cpu_util()},
                "mem": read_mem(),
                "fans": fans,
                "copy_state": {
                    "active": Z_STATE.copy_active,
                    "status": Z_STATE.copy_status,
                    "progress": Z_STATE.copy_progress,
                    "pending_ingest": getattr(Z_STATE, "pending_ingest", None),
                },
                "media_slots": (lambda s: (check_media_slot_transitions(s), s)[1])(read_media_slots()),
                "fan_control": {
                    "zone1_temp": t_zone1,
                    "zone1_pwm": active_pwm1,
                    "zone2_temp": t_zone2,
                    "zone2_pwm": active_pwm2,
                    "nvme_temp": t_nvme,
                    "cpu_temp": cpu_temp,
                    "cpu_pwm": active_pwm3,
                    "disk_hold_remaining": disk_hold_rem,
                    "cpu_hold_remaining": cpu_hold_rem,
                    "ctrl_cpu_fan": ctrl_cpu_fan,
                    "profile": profile,
                    "temp_min": temp_min,
                    "temp_max": temp_max,
                    "zero_rpm_enabled": zero_rpm_enabled,
                    "zero_rpm_nvme_ceiling": zero_rpm_nvme_ceiling,
                    "zero_rpm_stop_temp": zero_rpm_stop_temp,
                    "zero_rpm_start_temp": zero_rpm_start_temp,
                    "zone1_standby": z1_all_standby,
                    "zone2_standby": z2_all_standby,
                    "zone1_zero_rpm": active_pwm1 == 0,
                    "zone2_zero_rpm": active_pwm2 == 0,
                    "curve_points": fan_cfg.get("curve_points", None),
                    "nvme_curve_points": fan_cfg.get("nvme_curve_points", None),
                    "cpu_curve_points": fan_cfg.get("cpu_curve_points", None),
                    "zone1_curve_points": fan_cfg.get("zone1_curve_points", None),
                    "zone2_curve_points": fan_cfg.get("zone2_curve_points", None),
                },
                "net": net,
                "uptime": read_uptime(),
                "disks": disks,
                "chassis": detect_chassis_model(),
                "layout": get_current_layout(),
                "copy_status": Z_STATE.copy_status,
                "events": events_list,
                "security": {"is_default_password": is_using_default_password()},
                "unraid": read_unraid_status(),
                "docker": docker_list,
                "ups": read_ups_status(),
                "lcd": {
                    "page": Z_STATE.current_lcd_page,
                    "cycle_seconds": Z_STATE.lcd_cycle_seconds,
                },
                "client_preferences": (
                    Z_STATE.client_preferences
                    if Z_STATE.client_preferences is not None
                    else read_json(CLIENT_PREFS_FILE, default={})
                ),
                "peripherals": {
                    "fb_active": bool(ENABLE_FB and os.path.exists("/dev/fb0")),
                    "led_port": find_led_port(),
                    "led_ready": bool(find_led_port() is not None),
                    "fan_count": len([f for f in fans if f > 0]) if fans else 0,
                    "fans_online": bool(fans and (any(f > 0 for f in fans) or (active_pwm1 == 0 and active_pwm2 == 0))),
                },
            }

            # Evaluate alerts
            evaluate_system_alerts(data["unraid"], data["ups"])

            with Z_STATE.lock:
                Z_STATE.cached_stats = data

            broadcast_data = data
            if not events_changed or not docker_changed:
                broadcast_data = dict(data)
                if not events_changed:
                    del broadcast_data["events"]
                if not docker_changed:
                    del broadcast_data["docker"]

            broadcaster.broadcast(broadcast_data, full_data=data)

            now_ts = int(time.time())
            if not hasattr(stats_collector_daemon, "last_log"):
                stats_collector_daemon.last_log = 0
            if now_ts - stats_collector_daemon.last_log >= 300:
                stats_collector_daemon.last_log = now_ts
                try:
                    log_metrics(
                        now_ts,
                        data["cpu"].get("temp", 0),
                        data["cpu"].get("util", 0),
                        data["mem"].get("pct", 0),
                        disks,
                        fans,
                    )
                except Exception as db_e:
                    logger.info(f"[ZettNAS] DB Log Error: {db_e}")

        except Exception as e:
            logger.error(f"CRASH in stats collector: {e}")
            traceback.print_exc()

        if Z_STATE.ui_wake.wait(2.0):
            Z_STATE.ui_wake.clear()


def collect():
    with Z_STATE.lock:
        data = (
            dict(Z_STATE.cached_stats)
            if Z_STATE.cached_stats
            else {
                "name": get_server_hostname(),
                "status": "-- OK",
                "ip": read_ip(),
                "storage": {"used": "0GB", "total": "0GB", "pct": 0},
                "cpu": {"temp": 0, "util": 0},
                "mem": {"used_gb": 0, "total_gb": 0, "pct": 0},
                "fans": [],
                "copy_state": {"active": False, "status": "idle", "progress": {}},
                "net": {"tx": "0 B/s", "rx": "0 B/s", "iface": "bond0"},
                "uptime": "0s",
                "disks": [],
                "unraid": read_unraid_status(),
                "lcd": {"page": Z_STATE.current_lcd_page, "cycle_seconds": Z_STATE.lcd_cycle_seconds},
            }
        )
        data["events"] = list(Z_STATE.event_log)
        data["security"] = {"is_default_password": is_using_default_password()}
        if "lcd" not in data:
            data["lcd"] = {"page": Z_STATE.current_lcd_page, "cycle_seconds": Z_STATE.lcd_cycle_seconds}
        if "unraid" not in data:
            data["unraid"] = read_unraid_status()
    return data


def smart_poller_daemon():
    """
    Dedicated worker thread: decouples slow smartctl disk inspection and
    UPS polling from the high-frequency 2s fan PWM loop.
    """
    logger.info("[SMART/UPS Poller] Background telemetry poller thread started.")
    try:
        poll_all_disks_smart(force=True)
        read_ups_status(force=True)
    except Exception as e:
        logger.debug(f"[SMART/UPS Poller] Initial scan error: {e}")

    while True:
        try:
            time.sleep(4.0)
            poll_all_disks_smart()
            read_ups_status()
        except Exception as e:
            logger.error(f"[SMART/UPS Poller] Polling cycle error: {e}")
