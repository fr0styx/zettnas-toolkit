"""Fan control: the fan settings and one control step (zones, zero-RPM, storage interlocks
and the critical-temperature override). It runs inside the 2-second stats loop
(stats_collector) but lives here, apart from the telemetry and publishing code, because it is
safety logic (ARC-5). tests/test_arc5_fan_control_characterization.py pins its behaviour.
"""

import time

from backend.config import (
    FAN_CPU_HOLD_SECS,
    FAN_DISK_HOLD_SECS,
    FAN_FAILSAFE_PWM,
    FAN_MAX_PWM,
    FAN_MIN_PWM,
    FAN_STATE_FILE,
    FAN_ZERO_RPM_DEFAULT_NVME_CEILING,
    FAN_ZERO_RPM_DEFAULT_START_TEMP,
    FAN_ZERO_RPM_DEFAULT_STOP_TEMP,
    FAN_ZERO_RPM_STOP_DELAY,
    HDD_CRITICAL_TEMP,
    NVME_CRITICAL_TEMP,
    logger,
)
from backend.fsutil import SETTINGS_RECHECK_SECS, read_json_cached
from backend.hardware.fans import apply_zone_pwm, calc_curve_pwm, set_fan_pwm
from backend.hardware.storage import detect_chassis_model
from backend.hardware.unraid import read_unraid_status
from backend.state import Z_STATE, add_event


def fan_settings():
    """The fan settings with their defaults."""
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
        "disk_hold_secs": FAN_DISK_HOLD_SECS,
        "cpu_hold_secs": FAN_CPU_HOLD_SECS,
    }
    loaded_fan_cfg = read_json_cached(FAN_STATE_FILE, {}, max_age=SETTINGS_RECHECK_SECS)
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
    zero_rpm_stop_delay = int(fan_cfg.get("zero_rpm_stop_delay", FAN_ZERO_RPM_STOP_DELAY))
    disk_hold_secs = int(fan_cfg.get("disk_hold_secs", FAN_DISK_HOLD_SECS))
    cpu_hold_secs = int(fan_cfg.get("cpu_hold_secs", FAN_CPU_HOLD_SECS))
    return {
        "cpu_hold_secs": cpu_hold_secs,
        "ctrl_cpu_fan": ctrl_cpu_fan,
        "disk_hold_secs": disk_hold_secs,
        "fan_cfg": fan_cfg,
        "profile": profile,
        "temp_max": temp_max,
        "temp_min": temp_min,
        "zero_rpm_enabled": zero_rpm_enabled,
        "zero_rpm_nvme_ceiling": zero_rpm_nvme_ceiling,
        "zero_rpm_start_temp": zero_rpm_start_temp,
        "zero_rpm_stop_delay": zero_rpm_stop_delay,
        "zero_rpm_stop_temp": zero_rpm_stop_temp,
    }


def run_fan_control(
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
):
    """Zones, zero-RPM, storage interlocks and the critical-temperature override; sets the fans."""
    # Chassis Topology Resolution
    chassis_model = detect_chassis_model()
    sata_disks = [d for d in disks if d.get("role") == "data" or d.get("dev", "").startswith("sd")]

    if chassis_model == "d4":
        # ZettLab D4: Single exhaust fan (pwm1) cools ALL 4 bays
        zone1_disks = sata_disks
        zone2_disks = []
    else:
        # ZettLab D6U / D8U or generic: Check if disks have physical bay numbers assigned
        midpoint_bay = 4 if chassis_model == "d8u" else 3
        z1_bays, z2_bays = [], []
        has_bay_info = False
        for d in sata_disks:
            b = d.get("bay")
            if b is not None and isinstance(b, int) and b > 0:
                has_bay_info = True
                if b <= midpoint_bay:
                    z1_bays.append(d)
                else:
                    z2_bays.append(d)
        if has_bay_info and (z1_bays or z2_bays):
            zone1_disks = z1_bays
            zone2_disks = z2_bays
        else:
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
        z2_all_standby = (
            bool(zone2_disks) and all(d.get("standby", False) for d in zone2_disks) if zone2_disks else z1_all_standby
        )

    # Active temperatures per zone (sleeping disks' cached temps are ignored unless critical >= 55)
    active_z1 = [d["temp"] for d in zone1_disks if d.get("temp") is not None and not d.get("standby", False)]
    active_z2 = [d["temp"] for d in zone2_disks if d.get("temp") is not None and not d.get("standby", False)]

    t_zone1 = max(active_z1, default=30)
    t_zone2 = max(active_z2, default=30)

    # NVMe Drives & Wind Tunnel Cooling Override
    nvme_disks = [d for d in disks if d.get("role") == "cache" or "nvme" in d.get("dev", "")]
    active_nvme = [d["temp"] for d in nvme_disks if d.get("temp") is not None and not d.get("standby", False)]
    t_nvme = max(active_nvme, default=None)
    # If NVMe disks are installed, their temperature must be readable and below ceiling to allow Zero RPM
    nvme_over_ceiling = bool(nvme_disks and (t_nvme is None or t_nvme >= zero_rpm_nvme_ceiling))

    # Universal Storage Subsystem Interlocks (Unraid Parity/Mover, Btrfs Scrub, ZFS Scrub)
    unraid_status = read_unraid_status()
    mover_active = bool(unraid_status.get("mover", {}).get("active", False))
    parity_active = bool(unraid_status.get("parity_check", {}).get("active", False))
    pal_busy = False
    try:
        from backend.hardware.pal_storage import get_storage_platform

        pal_adapter = get_storage_platform()
        if hasattr(pal_adapter, "is_storage_busy"):
            pal_busy = bool(pal_adapter.is_storage_busy())
    except Exception:
        logger.debug("backend.services.fan_control.run_fan_control: ignored error", exc_info=True)
    storage_busy = mover_active or parity_active or pal_busy

    curve_points = fan_cfg.get("curve_points")
    zone1_curve = fan_cfg.get("zone1_curve_points") or curve_points
    zone2_curve = fan_cfg.get("zone2_curve_points") or curve_points
    nvme_curve = fan_cfg.get("nvme_curve_points")
    cpu_curve = fan_cfg.get("cpu_curve_points")

    raw_pwm1 = calc_curve_pwm(
        t_zone1,
        min_pwm=FAN_MIN_PWM,
        max_pwm=FAN_MAX_PWM,
        temp_min=temp_min,
        temp_max=temp_max,
        curve_points=zone1_curve,
        allow_zero=zero_rpm_enabled,
        zone_key="zone1",
    )
    raw_pwm2 = calc_curve_pwm(
        t_zone2,
        min_pwm=FAN_MIN_PWM,
        max_pwm=FAN_MAX_PWM,
        temp_min=temp_min,
        temp_max=temp_max,
        curve_points=zone2_curve,
        allow_zero=zero_rpm_enabled,
        zone_key="zone2",
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
            zone_key="nvme",
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

    if cpu_temp is None or cpu_temp <= 0:
        raw_pwm3 = FAN_FAILSAFE_PWM
    elif cpu_curve:
        raw_pwm3 = calc_curve_pwm(
            cpu_temp,
            min_pwm=FAN_MIN_PWM,
            max_pwm=FAN_MAX_PWM,
            temp_min=50,
            temp_max=85,
            curve_points=cpu_curve,
            allow_zero=False,
            zone_key="cpu",
        )
    elif cpu_temp >= 80:
        raw_pwm3 = FAN_MAX_PWM
    elif cpu_temp >= 70:
        raw_pwm3 = 145
    elif cpu_temp >= 55:
        raw_pwm3 = 115
    else:
        raw_pwm3 = 85

    # Safety override: any spinning or solid state disk at/above its critical temperature,
    # or CPU at/above 80°C, forces fans to 100% regardless of profile or curve.
    hot_disks = []
    for d in disks:
        t = d.get("temp")
        if t is not None and not d.get("standby", False):
            is_nvme = (
                d.get("is_nvme", False) or d.get("dev", "").startswith("nvme") or d.get("name", "").startswith("nv")
            )
            crit_thresh = NVME_CRITICAL_TEMP if is_nvme else HDD_CRITICAL_TEMP
            if t >= crit_thresh:
                hot_disks.append((d, crit_thresh))

    cpu_critical = cpu_temp is not None and cpu_temp >= 80
    critical_override = bool(hot_disks) or cpu_critical
    if critical_override and not Z_STATE.critical_temp_active:
        reasons = []
        if hot_disks:
            reasons.append(
                ", ".join(
                    f"{d.get('name', d.get('dev', '?'))} ({d['temp']}°C >= {thresh}°C)" for d, thresh in hot_disks
                )
            )
        if cpu_critical:
            reasons.append(f"CPU ({cpu_temp}°C >= 80°C)")
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

    # Standby Cooldown & Anti-Flutter Delay Resolution
    # Dynamic fast-path: when drive bay is already at/below ambient equilibrium (<= 32°C),
    # cooldown delay is safely reduced to 15s to verify stable platter halt without noise linger.
    effective_delay_z1 = min(zero_rpm_stop_delay, 15) if t_zone1 <= 32 else zero_rpm_stop_delay
    effective_delay_z2 = min(zero_rpm_stop_delay, 15) if t_zone2 <= 32 else zero_rpm_stop_delay

    z1_zero_rpm_ready = bool(
        z1_eligible and st1.get("standby_since", 0.0) > 0.0 and (now - st1["standby_since"]) >= effective_delay_z1
    )
    z2_zero_rpm_ready = bool(
        z2_eligible and st2.get("standby_since", 0.0) > 0.0 and (now - st2["standby_since"]) >= effective_delay_z2
    )

    z1_rem = (
        max(0, int(effective_delay_z1 - (now - st1["standby_since"])))
        if (z1_eligible and st1.get("standby_since", 0.0) > 0 and not z1_zero_rpm_ready)
        else 0
    )
    z2_rem = (
        max(0, int(effective_delay_z2 - (now - st2["standby_since"])))
        if (z2_eligible and st2.get("standby_since", 0.0) > 0 and not z2_zero_rpm_ready)
        else 0
    )

    if critical_override:
        raw_pwm1 = raw_pwm2 = FAN_MAX_PWM
        active_pwm1 = apply_zone_pwm(1, FAN_MAX_PWM, hold_secs=disk_hold_secs, allow_zero=False)
        active_pwm2 = apply_zone_pwm(2, FAN_MAX_PWM, hold_secs=disk_hold_secs, allow_zero=False)
        custom_pwms = {"pwm1": active_pwm1, "pwm2": active_pwm2}
        if ctrl_cpu_fan:
            active_pwm3 = apply_zone_pwm(3, FAN_MAX_PWM, hold_secs=cpu_hold_secs, allow_zero=False)
            custom_pwms["pwm3"] = active_pwm3
        else:
            active_pwm3 = 0
        set_fan_pwm("auto", custom_pwms=custom_pwms, ctrl_cpu_fan=ctrl_cpu_fan, zero_rpm_allowed=False)
    elif profile == "auto":
        # Standby and Zero-RPM target and hold resolution:
        # 1. If zero-RPM ready -> drop to 0 PWM with 0s hold
        # 2. If eligible for zero-RPM (cooldown phase) -> ramp directly down to FAN_MIN_PWM without being held at peak PWM
        # 3. Else active spinning -> dynamic thermal curve with disk_hold_secs downward hysteresis hold
        if z1_zero_rpm_ready:
            target_pwm1 = 0
            z1_hold = 0
        elif z1_eligible:
            target_pwm1 = FAN_MIN_PWM
            z1_hold = 0
        else:
            target_pwm1 = max(FAN_MIN_PWM, raw_pwm1)
            z1_hold = disk_hold_secs

        if z2_zero_rpm_ready:
            target_pwm2 = 0
            z2_hold = 0
        elif z2_eligible:
            target_pwm2 = FAN_MIN_PWM
            z2_hold = 0
        else:
            target_pwm2 = max(FAN_MIN_PWM, raw_pwm2)
            z2_hold = disk_hold_secs

        allow_zero_z1 = z1_zero_rpm_ready
        allow_zero_z2 = z2_zero_rpm_ready

        active_pwm1 = apply_zone_pwm(1, target_pwm1, hold_secs=z1_hold, allow_zero=allow_zero_z1)
        active_pwm2 = apply_zone_pwm(2, target_pwm2, hold_secs=z2_hold, allow_zero=allow_zero_z2)

        custom_pwms = {"pwm1": active_pwm1, "pwm2": active_pwm2}

        if ctrl_cpu_fan:
            active_pwm3 = apply_zone_pwm(3, raw_pwm3, hold_secs=cpu_hold_secs, allow_zero=False)
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
        if critical_override:
            man_pwm = FAN_MAX_PWM
        man_pwm = max(FAN_MIN_PWM, min(FAN_MAX_PWM, man_pwm))
        active_pwm1 = apply_zone_pwm(1, man_pwm, hold_secs=disk_hold_secs, allow_zero=False)
        active_pwm2 = apply_zone_pwm(2, man_pwm, hold_secs=disk_hold_secs, allow_zero=False)
        active_pwm3 = apply_zone_pwm(3, man_pwm, hold_secs=cpu_hold_secs, allow_zero=False) if ctrl_cpu_fan else 0
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
    return {
        "active_pwm1": active_pwm1,
        "active_pwm2": active_pwm2,
        "active_pwm3": active_pwm3,
        "now": now,
        "nvme_over_ceiling": nvme_over_ceiling,
        "storage_busy": storage_busy,
        "t_nvme": t_nvme,
        "t_zone1": t_zone1,
        "t_zone2": t_zone2,
        "z1_all_standby": z1_all_standby,
        "z1_eligible": z1_eligible,
        "z1_rem": z1_rem,
        "z2_all_standby": z2_all_standby,
        "z2_eligible": z2_eligible,
        "z2_rem": z2_rem,
    }
