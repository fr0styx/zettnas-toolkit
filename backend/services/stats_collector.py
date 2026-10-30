import concurrent.futures
import json
import logging
import os
import sqlite3
import time
import traceback
from typing import Any, Optional

from backend.config import (
    CLIENT_PREFS_FILE,
    DB_PATH,
    ENABLE_FB,
    FAN_CPU_HOLD_SECS,
    FAN_DISK_HOLD_SECS,
    FAN_FAILSAFE_PWM,
    FAN_MAX_PWM,
    FAN_MIN_PWM,
    FAN_SPINUP_GRACE_SECS,
    FAN_STATE_FILE,
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
from backend.fsutil import SETTINGS_RECHECK_SECS, read_json, read_json_cached
from backend.hardware.chassis import ChassisEngine
from backend.hardware.cpu import read_cpu_temp, read_cpu_util
from backend.hardware.disks import poll_all_disks_smart, read_disk_temps_and_io
from backend.hardware.docker_stats import read_docker_containers
from backend.hardware.fans import apply_zone_pwm, calc_curve_pwm, get_hold_remaining, read_fans, set_fan_pwm
from backend.hardware.host_telemetry import (
    get_cpu_telemetry,
    get_dmi_telemetry,
    get_gpu_telemetry,
    get_npu_telemetry,
    get_os_telemetry,
)
from backend.hardware.led import apply_led_state, find_led_port, send_led_packet
from backend.hardware.memory import read_mem
from backend.hardware.network import read_ip, read_network_rates
from backend.hardware.screen import (
    get_effective_brightness,
    is_in_time_window,
    set_screen_brightness,
)
from backend.hardware.storage import (
    detect_chassis_model,
    get_chassis_friendly_name,
    get_current_layout,
    read_storage,
    read_uptime,
)
from backend.hardware.unraid import read_unraid_status
from backend.hardware.ups import read_ups_status
from backend.services.alert_rules import evaluate_system_alerts
from backend.services.broadcaster import broadcaster
from backend.services.copy_engine import check_media_slot_transitions, read_media_slots
from backend.services.fan_control import fan_settings as _fan_settings  # moved out (ARC-5)
from backend.services.fan_control import run_fan_control as _run_fan_control
from backend.services.notifications import NOTIFICATIONS_FILE, send_notification
from backend.services.rag_reindex_status import get_reindex_status as get_ai_reindex_status
from backend.services.stats_delta import StatsDeltaEncoder
from backend.state import Z_STATE, add_event, events_snapshot

logger = logging.getLogger("ZettNAS")

_notify_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="zett_notify")


def _async_notify(**kwargs):
    """Dispatches notifications on a worker thread so slow webhooks never stall PWM fan loop updates."""
    try:
        _notify_executor.submit(send_notification, **kwargs)
    except Exception as e:
        logger.warning(f"[NOTIFY] Failed to queue async notification: {e}")


_delta_encoder = StatsDeltaEncoder()


def _check_health(bad, cpu_temp, ctrl_cpu_fan, fans, has_crit, now, all_disks=None):
    """Fan stalls, CPU temperature and drive health: events and notifications."""
    # Evaluate hardware health, stalls, and thermal alerts (unconditionally)
    notif_cfg = read_json_cached(NOTIFICATIONS_FILE, {}, max_age=SETTINGS_RECHECK_SECS)
    if not isinstance(notif_cfg, dict):
        notif_cfg = {}
    cpu_crit_threshold = notif_cfg.get("cpu_temp_threshold", 85)
    cpu_warn_threshold = max(50, cpu_crit_threshold - 10)

    if not ctrl_cpu_fan:
        Z_STATE.known_active_fans.discard(2)

    stalled_fans = []
    for i in Z_STATE.known_active_fans:
        if i >= len(fans):
            continue
        if i == 2 and not ctrl_cpu_fan:
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
    # No CPU temperature sensor (VMs, some boards): judge on the other signals only.
    temp_known = cpu_temp is not None
    is_crit = has_crit or (temp_known and cpu_temp >= cpu_crit_threshold) or is_failing_fan
    is_warn = (len(bad) > 0) or (temp_known and cpu_temp >= cpu_warn_threshold)

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

    if temp_known and cpu_temp >= cpu_crit_threshold:
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
    elif temp_known and cpu_temp >= cpu_warn_threshold:
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

    # Drives: a temperature alert once per crossing; their condition is alerted by Drive Health
    # when its verdict changes (REL-7), not every half hour from here.
    try:
        from backend.hardware.disks import drive_serials_by_dev
        from backend.services import drive_alerts
        from backend.services.drive_notes import temp_limits_for_devs

        drive_alerts.check_temperatures(
            all_disks or bad,
            notif_cfg.get("hdd_temp_threshold", 50),
            _async_notify,
            limits=temp_limits_for_devs(drive_serials_by_dev()),
        )
    except Exception:
        logger.debug("stats_collector: drive temperature check failed", exc_info=True)
    return {"is_crit": is_crit, "is_warn": is_warn}


def _update_leds(is_crit, is_warn):
    """The light bar: alerts, copy progress and night mode."""
    # LED Lighting & Schedule (runs only if hardware present/configured)
    cfg = read_json_cached(LED_STATE_FILE, {}, max_age=SETTINGS_RECHECK_SECS)
    if not isinstance(cfg, dict):
        cfg = {}

    in_led_night = cfg.get("night_mode", False) and is_in_time_window(
        cfg.get("night_start", "23:00"), cfg.get("night_end", "07:00")
    )

    if cfg.get("reactive", True):
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

    last_led_night = getattr(stats_collector_daemon, "_last_led_night", False)
    if last_led_night and not in_led_night:
        apply_led_state(cfg)
    stats_collector_daemon._last_led_night = in_led_night


def _pending_offers() -> dict:
    """A card waiting to be copied, and a USB disk offered for a backup or an import (FEAT-07)."""
    return {
        "pending_ingest": getattr(Z_STATE, "pending_ingest", None),
        "pending_usb": getattr(Z_STATE, "pending_usb", None),
    }


def _build_payload(
    active_pwm1,
    active_pwm2,
    active_pwm3,
    cpu_hold_secs,
    cpu_temp,
    ctrl_cpu_fan,
    disk_hold_secs,
    disks,
    fan_cfg,
    fans,
    net,
    nvme_over_ceiling,
    profile,
    status,
    storage_busy,
    t_nvme,
    t_zone1,
    t_zone2,
    temp_max,
    temp_min,
    z1_all_standby,
    z1_eligible,
    z1_rem,
    z2_all_standby,
    z2_eligible,
    z2_rem,
    zero_rpm_enabled,
    zero_rpm_nvme_ceiling,
    zero_rpm_start_temp,
    zero_rpm_stop_delay,
    zero_rpm_stop_temp,
):
    """Everything the dashboard shows, in one dictionary."""
    disk_hold_rem = max(get_hold_remaining("pwm1", disk_hold_secs), get_hold_remaining("pwm2", disk_hold_secs))
    cpu_hold_rem = get_hold_remaining("pwm3", cpu_hold_secs)

    events_list = events_snapshot()
    docker_list = read_docker_containers()

    hw_features = ChassisEngine.detect_hardware_features()
    cpu_telemetry = get_cpu_telemetry()
    dmi_telemetry = get_dmi_telemetry()
    os_telemetry = get_os_telemetry()
    gpu_telemetry = get_gpu_telemetry()
    npu_telemetry = get_npu_telemetry()

    ai_active = getattr(Z_STATE, "ai_active", False)
    ai_accel = getattr(Z_STATE, "ai_accelerator", "")
    ai_model = getattr(Z_STATE, "ai_model", "")

    # Which accelerator the AI is using; the load figures stay as measured.
    if ai_active:
        if ai_accel == "gpu":
            gpu_telemetry["inference_active"] = True
        elif ai_accel == "npu":
            npu_telemetry["inference_active"] = True

    data = {
        "name": get_server_hostname(),
        "status": status,
        "ip": read_ip(),
        "storage": read_storage(),
        "cpu": {
            "temp": cpu_temp,
            "util": read_cpu_util(),
            "model": cpu_telemetry.get("model", ""),
            "cores": cpu_telemetry.get("cores", 1),
            "governor": cpu_telemetry.get("governor", "performance"),
            "load_avg": cpu_telemetry.get("load_avg", [0.0, 0.0, 0.0]),
        },
        "system": os_telemetry,
        "motherboard": dmi_telemetry,
        "gpu": gpu_telemetry,
        "npu": npu_telemetry,
        "ai_active": ai_active,
        "ai_accelerator": ai_accel,
        "ai_model": ai_model,
        "reindex_status": get_ai_reindex_status(),
        "mem": read_mem(),
        "fans": fans,
        "copy_state": {
            "active": Z_STATE.copy_active,
            "status": Z_STATE.copy_status,
            "progress": Z_STATE.copy.snapshot(),  # a copy: the copy thread keeps changing it (ARC-9)
            **_pending_offers(),
        },
        "media_slots": (lambda s: (check_media_slot_transitions(s), s)[1])(read_media_slots()),
        "fan_control": {
            "driver_mode": getattr(Z_STATE, "fan_driver_mode", "none"),
            "zone1_temp": t_zone1,
            "zone1_pwm": active_pwm1,
            "zone2_temp": t_zone2,
            "zone2_pwm": active_pwm2,
            "nvme_temp": t_nvme,
            "cpu_temp": cpu_temp,
            "cpu_pwm": active_pwm3,
            "disk_hold_remaining": disk_hold_rem,
            "cpu_hold_remaining": cpu_hold_rem,
            "disk_hold_secs": disk_hold_secs,
            "cpu_hold_secs": cpu_hold_secs,
            "ctrl_cpu_fan": ctrl_cpu_fan,
            "profile": profile,
            "temp_min": temp_min,
            "temp_max": temp_max,
            "zero_rpm_enabled": zero_rpm_enabled,
            "zero_rpm_nvme_ceiling": zero_rpm_nvme_ceiling,
            "zero_rpm_stop_temp": zero_rpm_stop_temp,
            "zero_rpm_start_temp": zero_rpm_start_temp,
            "zero_rpm_stop_delay": zero_rpm_stop_delay,
            "zone1_standby": z1_all_standby,
            "zone2_standby": z2_all_standby,
            "zone1_eligible": z1_eligible,
            "zone2_eligible": z2_eligible,
            "zone1_standby_rem": z1_rem,
            "zone2_standby_rem": z2_rem,
            "zone1_zero_rpm": active_pwm1 == 0,
            "zone2_zero_rpm": active_pwm2 == 0,
            "storage_busy": storage_busy,
            "nvme_over_ceiling": nvme_over_ceiling,
            "curve_points": fan_cfg.get("curve_points"),
            "nvme_curve_points": fan_cfg.get("nvme_curve_points"),
            "cpu_curve_points": fan_cfg.get("cpu_curve_points"),
            "zone1_curve_points": fan_cfg.get("zone1_curve_points"),
            "zone2_curve_points": fan_cfg.get("zone2_curve_points"),
        },
        "net": net,
        "uptime": read_uptime(),
        "disks": disks,
        "chassis": detect_chassis_model(),
        "chassis_label": get_chassis_friendly_name(detect_chassis_model()),
        "layout": get_current_layout(),
        "copy_status": Z_STATE.copy_status,
        "events": events_list,
        "security": {"is_default_password": is_using_default_password()},
        "unraid": read_unraid_status(),
        "docker": docker_list,
        "ups": (ups_stat := read_ups_status()),
        "lcd": {
            "page": Z_STATE.current_lcd_page,
            "cycle_seconds": Z_STATE.lcd_cycle_seconds,
        },
        "client_preferences": (
            Z_STATE.client_preferences
            if Z_STATE.client_preferences is not None
            else read_json_cached(CLIENT_PREFS_FILE, default={}, max_age=SETTINGS_RECHECK_SECS)
        ),
        "hardware": hw_features,
        "peripherals": {
            "fb_active": hw_features["has_lcd"],
            "led_port": find_led_port(),
            "led_ready": hw_features["has_mcu"],
            "has_custom_hardware": hw_features["has_custom_hardware"],
            "fan_count": len([f for f in fans if f > 0]) if fans else 0,
            "fans_online": bool(fans and (any(f > 0 for f in fans) or (active_pwm1 == 0 and active_pwm2 == 0))),
        },
    }
    return {"data": data}


def _publish(data, disks, fans, net, now):
    """Alerts, the UPS watchdog, the cached copy, the SSE broadcast and the 5-minute metrics log."""
    # Evaluate alerts & UPS power watchdog
    evaluate_system_alerts(data["unraid"], data["ups"])
    try:
        from backend.services.ups_watchdog import check_ups_power_watchdog

        check_ups_power_watchdog(data["ups"], now)
    except Exception as ue:
        logger.debug(f"[UPS Watchdog] Evaluation error: {ue}")

    with Z_STATE.lock:
        Z_STATE.cached_stats = data
    if not getattr(Z_STATE, "lcd_blanked", False):
        Z_STATE.lcd_wake.set()  # the built-in LCD renderer redraws with the new numbers

    # Send only what changed; clients merge it into their copy (see stats_delta.py). With nobody
    # listening there is nothing to compare against: the next listener starts from a full
    # snapshot, so the encoder starts over too (PERF-20)
    if broadcaster.get_subscriber_count():
        broadcaster.broadcast(_delta_encoder.encode(data), full_data=data)
    else:
        _delta_encoder.reset()
        broadcaster.broadcast(data, full_data=data)

    now_ts = int(time.time())
    if not hasattr(stats_collector_daemon, "last_log"):
        stats_collector_daemon.last_log = 0
    if now_ts - stats_collector_daemon.last_log >= 300:
        stats_collector_daemon.last_log = now_ts
        try:
            disk_rates = getattr(Z_STATE, "disk_throughput", {})
            log_metrics(
                now_ts,
                data["cpu"].get("temp", 0),
                data["cpu"].get("util", 0),
                data["mem"].get("pct", 0),
                disks,
                fans,
                net_rx_bytes_sec=net.get("rx_bytes_sec", 0.0) if isinstance(net, dict) else 0.0,
                net_tx_bytes_sec=net.get("tx_bytes_sec", 0.0) if isinstance(net, dict) else 0.0,
                disk_read_bytes_sec=disk_rates.get("read_bytes_sec", 0.0) if isinstance(disk_rates, dict) else 0.0,
                disk_write_bytes_sec=disk_rates.get("write_bytes_sec", 0.0) if isinstance(disk_rates, dict) else 0.0,
            )
        except Exception as db_e:
            logger.info(f"[ZettNAS] DB Log Error: {db_e}")


def stats_collector_daemon():
    from backend.services.fan_heartbeat import beat
    from backend.services.supervisor import beat as supervisor_beat

    while not Z_STATE.shutting_down:
        Z_STATE.collector_heartbeat = time.time()
        supervisor_beat("StatsCollector")
        beat(released=bool(getattr(Z_STATE, "fans_released", False)))  # for the host fan watchdog
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

            _r = _fan_settings()
            cpu_hold_secs = _r["cpu_hold_secs"]
            ctrl_cpu_fan = _r["ctrl_cpu_fan"]
            disk_hold_secs = _r["disk_hold_secs"]
            fan_cfg = _r["fan_cfg"]
            profile = _r["profile"]
            temp_max = _r["temp_max"]
            temp_min = _r["temp_min"]
            zero_rpm_enabled = _r["zero_rpm_enabled"]
            zero_rpm_nvme_ceiling = _r["zero_rpm_nvme_ceiling"]
            zero_rpm_start_temp = _r["zero_rpm_start_temp"]
            zero_rpm_stop_delay = _r["zero_rpm_stop_delay"]
            zero_rpm_stop_temp = _r["zero_rpm_stop_temp"]

            _r = _run_fan_control(
                cpu_hold_secs,
                cpu_temp,
                ctrl_cpu_fan,
                disk_hold_secs,
                disks,
                fan_cfg,
                profile,
                temp_max,
                temp_min,
                zero_rpm_enabled,
                zero_rpm_nvme_ceiling,
                zero_rpm_stop_delay,
                zero_rpm_stop_temp,
            )
            active_pwm1 = _r["active_pwm1"]
            active_pwm2 = _r["active_pwm2"]
            active_pwm3 = _r["active_pwm3"]
            now = _r["now"]
            nvme_over_ceiling = _r["nvme_over_ceiling"]
            storage_busy = _r["storage_busy"]
            t_nvme = _r["t_nvme"]
            t_zone1 = _r["t_zone1"]
            t_zone2 = _r["t_zone2"]
            z1_all_standby = _r["z1_all_standby"]
            z1_eligible = _r["z1_eligible"]
            z1_rem = _r["z1_rem"]
            z2_all_standby = _r["z2_all_standby"]
            z2_eligible = _r["z2_eligible"]
            z2_rem = _r["z2_rem"]

            # Screen Backlight Management
            target_bl = get_effective_brightness()
            set_screen_brightness(target_bl, cached=True)  # written when it changes (PERF-5)

            _r = _check_health(bad, cpu_temp, ctrl_cpu_fan, fans, has_crit, now, disks)
            is_crit = _r["is_crit"]
            is_warn = _r["is_warn"]

            _update_leds(is_crit, is_warn)

            _r = _build_payload(
                active_pwm1,
                active_pwm2,
                active_pwm3,
                cpu_hold_secs,
                cpu_temp,
                ctrl_cpu_fan,
                disk_hold_secs,
                disks,
                fan_cfg,
                fans,
                net,
                nvme_over_ceiling,
                profile,
                status,
                storage_busy,
                t_nvme,
                t_zone1,
                t_zone2,
                temp_max,
                temp_min,
                z1_all_standby,
                z1_eligible,
                z1_rem,
                z2_all_standby,
                z2_eligible,
                z2_rem,
                zero_rpm_enabled,
                zero_rpm_nvme_ceiling,
                zero_rpm_start_temp,
                zero_rpm_stop_delay,
                zero_rpm_stop_temp,
            )
            data = _r["data"]

            _publish(data, disks, fans, net, now)

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
                "storage": {"used": "0GB", "total": "0GB", "pct": 0, "engine": "Btrfs / OpenZFS"},
                "cpu": {
                    "temp": 0,
                    "util": 0,
                    "model": "x86_64",
                    "cores": 1,
                    "governor": "performance",
                    "load_avg": [0.0, 0.0, 0.0],
                },
                "system": {
                    "distro": "Linux",
                    "kernel": "Linux",
                    "uptime_str": "0s",
                    "uptime_sec": 0.0,
                    "hostname": get_server_hostname(),
                },
                "motherboard": {"vendor": "Zettlab", "board": "Standard PC", "bios_version": "N/A", "bios_date": ""},
                "gpu": {"present": False, "vendor": "Generic", "model": "None", "codecs": [], "ready": False},
                "npu": {"present": False, "vendor": "None", "model": "None", "frameworks": [], "ready": False},
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
        data["events"] = events_snapshot()
        data["security"] = {"is_default_password": is_using_default_password()}
        if "lcd" not in data:
            data["lcd"] = {"page": Z_STATE.current_lcd_page, "cycle_seconds": Z_STATE.lcd_cycle_seconds}
        if "unraid" not in data:
            data["unraid"] = read_unraid_status()
    return data


_SMART_VELOCITY_LAST_ALERT: dict[str, float] = {}


def evaluate_smart_velocity_alerts() -> list[dict[str, Any]]:
    """
    Evaluates 7-day degradation velocity for all discovered disks.
    If accelerating sector decay or active sector shedding is detected (realloc_7d_delta > 0 or shedding_sectors=True),
    dispatches a CRITICAL_DRIVE_DEGRADATION push notification via Apprise with 24-hour alert deduplication.
    """
    from backend.db import query_smart_velocity
    from backend.hardware.disks import _discover_disks
    from backend.services.notifications import send_notification
    from backend.state import add_event

    now = time.time()
    triggered_alerts: list[dict[str, Any]] = []
    try:
        disks = _discover_disks()
        for d in disks:
            dev = d.get("dev")
            if not dev:
                continue
            v = query_smart_velocity(dev)
            if not isinstance(v, dict):
                continue

            realloc_7d = v.get("realloc_7d_delta", 0)
            shedding = bool(v.get("shedding_sectors", False))
            risk = str(v.get("failure_risk", "")).lower()
            pred = v.get("predictive_velocity", {})
            is_accel = bool(pred.get("is_accelerating", False))
            # Shown on the desktop and the front LCD (D6)
            Z_STATE.smart.set_risk(
                dev,
                {
                    "risk": risk or "low",
                    "probability": v.get("failure_probability"),
                    "advice": str(v.get("recommendation") or "")[:200],
                },
            )

            if shedding or realloc_7d > 0 or risk == "critical" or is_accel:
                last_alert_time = _SMART_VELOCITY_LAST_ALERT.get(dev, 0)
                # 24-hour deduplication window (86400 seconds)
                if now - last_alert_time >= 86400:
                    _SMART_VELOCITY_LAST_ALERT[dev] = now
                    title = f"⚠️ Critical Drive Degradation Detected: {dev}"
                    msg = (
                        f"Drive {dev} shows active media degradation: "
                        f"{realloc_7d} reallocated sectors in the last 7 days. "
                        f"Risk level: {risk.upper()}. "
                        f"{v.get('recommendation', 'Plan replacement.')}"
                    )
                    add_event("critical", "Drive Degradation", msg)
                    send_notification(
                        {
                            "type": "smart",
                            "level": "critical",
                            "title": title,
                            "message": msg,
                        }
                    )
                    triggered_alerts.append({"dev": dev, "realloc_7d_delta": realloc_7d, "risk": risk})
    except Exception as ex:
        logger.debug(f"[SMART Velocity] Alert evaluation error: {ex}")

    return triggered_alerts


SMART_POLL_TICK_SECS = 10.0
SMART_VELOCITY_EVERY_SECS = 300.0
DRIVE_VERDICTS_EVERY_SECS = 1800.0  # Drive Health verdicts for the Overview


def smart_poller_daemon():
    """
    Dedicated worker thread: decouples slow smartctl disk inspection and
    UPS polling from the high-frequency 2s fan PWM loop.
    """
    logger.info("[SMART/UPS Poller] Background telemetry poller thread started.")
    try:
        poll_all_disks_smart(force=True)
        read_ups_status(force=True)
        evaluate_smart_velocity_alerts()
    except Exception as e:
        logger.debug(f"[SMART/UPS Poller] Initial scan error: {e}")

    last_velocity = time.monotonic()
    last_verdicts = None
    last_pack = time.monotonic()
    while not Z_STATE.shutting_down:
        try:
            # one 10 s sleep, not twenty 0.5 s slices (PERF-5); per-disk SMART intervals and the
            # UPS cache decide what is actually read
            from backend.services.supervisor import beat as supervisor_beat

            supervisor_beat("SmartPoller")
            time.sleep(SMART_POLL_TICK_SECS)
            if Z_STATE.shutting_down:
                break
            poll_all_disks_smart()
            read_ups_status()
            if time.monotonic() - last_pack >= 60:  # the AI pack stops when nothing used it (AI-40)
                last_pack = time.monotonic()
                try:
                    from backend.services import ai_pack
                    from backend.services.rag_engine import get_rag_engine

                    engine = get_rag_engine()
                    ai_pack.idle_tick(engine.get_config(), indexing=bool(getattr(engine, "_is_indexing", False)))
                except Exception:
                    logger.debug("[SMART/UPS Poller] AI pack idle check failed", exc_info=True)
            if time.monotonic() - last_velocity >= SMART_VELOCITY_EVERY_SECS:
                evaluate_smart_velocity_alerts()  # SMART history changes slowly
                last_velocity = time.monotonic()
            if last_verdicts is None or time.monotonic() - last_verdicts >= DRIVE_VERDICTS_EVERY_SECS:
                last_verdicts = time.monotonic()
                try:
                    from backend.hardware.disks import refresh_drive_verdicts

                    refresh_drive_verdicts()  # never wakes a sleeping drive
                except Exception as dv_e:
                    logger.debug(f"[SMART Poller] drive verdicts threw: {dv_e}")
            try:
                from backend.hardware.disks import check_active_smart_tests

                check_active_smart_tests()
            except Exception as st_e:
                logger.debug(f"[SMART Poller] check_active_smart_tests threw: {st_e}")
            try:
                from backend.services.health_signal import maybe_send

                maybe_send()  # opt-in weekly report; reads its file at most hourly
            except Exception as hs_e:
                logger.debug(f"[SMART Poller] health signal threw: {hs_e}")
        except Exception as e:
            logger.error(f"[SMART/UPS Poller] Polling cycle error: {e}")
