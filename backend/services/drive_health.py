"""Drive Health: one verdict per drive, the reasons, and what to do (the rules behind the app).

A SMART table says "5 Reallocated_Sector_Ct 100 100 010 ... 8". This turns it into "8 sectors
were replaced a while ago and the number has not moved: keep an eye on it". The rules follow
what large drive fleets have found predicts failure (reallocated, pending and uncorrectable
sectors, command timeouts, spin retries, a failed self-test) and what is not the drive's fault
(cable errors, heat). A count that is growing matters more than one that has stood still, so
the stored history (history.db, smart_history) is part of every assessment.

Input: smartctl's JSON for the drive (smartctl -a -j / -x -j) or, for a sleeping drive, nothing
but its stored history, which is enough for a verdict without waking it. Output: assess().
Nothing here touches a disk.
"""

from __future__ import annotations

import time
from typing import Any

# Verdicts, mildest first; a drive takes the most severe of its findings
OK, WATCH, SOON, NOW = "ok", "watch", "soon", "now"
ORDER = {OK: 0, WATCH: 1, SOON: 2, NOW: 3}
# What a finding asks for: replacing the drive, or something around it
REPLACE, COOLING, CABLE, TEST, INFO = "replace", "cooling", "cable", "test", "info"

HDD_HOT_C, HDD_CRITICAL_C = 50, 60
NVME_HOT_C, NVME_CRITICAL_C = 70, 80
OLD_HDD_HOURS = 5 * 365 * 24  # five years powered on
TREND_DAYS = 30
TEST_STALE_DAYS = 35  # no self-test for longer than this (a monthly schedule plus slack)


def _raw(attr: dict[str, Any]) -> int:
    raw = attr.get("raw") or {}
    value = raw.get("value", 0)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 0
    # several vendors pack extra counters into the high bytes of the raw value: Seagate puts three
    # 16-bit counters in 188 (the low one is the timeouts), others use the top bytes of 5 and 197
    if attr.get("id") == 188:
        return value & 0xFFFF
    return value & 0xFFFFFFFF if attr.get("id") in (5, 187, 197, 198) else value


def read_smartctl(doc: dict[str, Any] | None) -> dict[str, Any]:
    """The readings the rules use, from smartctl's JSON (ATA, NVMe or SCSI)."""
    doc = doc or {}
    device = doc.get("device") or {}
    protocol = str(device.get("protocol") or "").lower()
    is_nvme = protocol == "nvme" or "nvme_smart_health_information_log" in doc
    r: dict[str, Any] = {
        "protocol": "nvme" if is_nvme else ("scsi" if protocol == "scsi" else "ata"),
        "model": doc.get("model_name") or doc.get("scsi_model_name") or "",
        "serial": doc.get("serial_number") or "",
        "capacity_bytes": (doc.get("user_capacity") or {}).get("bytes"),
        "rotation_rpm": doc.get("rotation_rate"),
        "smart_passed": (doc.get("smart_status") or {}).get("passed"),
        "temp_c": (doc.get("temperature") or {}).get("current"),
        "power_on_hours": (doc.get("power_on_time") or {}).get("hours"),
        "attributes": {},
        "failing_attributes": [],
        # who the drive is, for "About this drive" (Drive Health revamp)
        "firmware": doc.get("firmware_version") or "",
        "power_cycles": doc.get("power_cycle_count"),
        "form_factor": (doc.get("form_factor") or {}).get("name") or "",
        "link": ((doc.get("interface_speed") or {}).get("current") or {}).get("string")
        or (doc.get("sata_version") or {}).get("string")
        or "",
    }
    for a in ((doc.get("ata_smart_attributes") or {}).get("table")) or []:
        aid = a.get("id")
        if not isinstance(aid, int):
            continue
        r["attributes"][aid] = {
            "name": a.get("name") or "",
            "value": a.get("value"),
            "thresh": a.get("thresh"),
            "raw": _raw(a),
        }
        if str(a.get("when_failed") or "").strip() in ("now", "FAILING_NOW"):
            r["failing_attributes"].append(a.get("name") or str(aid))
    nv = doc.get("nvme_smart_health_information_log") or {}
    if nv:
        r["nvme"] = {
            "critical_warning": nv.get("critical_warning", 0) or 0,
            "available_spare": nv.get("available_spare"),
            "available_spare_threshold": nv.get("available_spare_threshold"),
            "percentage_used": nv.get("percentage_used"),
            "media_errors": nv.get("media_errors", 0) or 0,
            "unsafe_shutdowns": nv.get("unsafe_shutdowns", 0) or 0,
        }
        if r["temp_c"] is None and nv.get("temperature") is not None:
            r["temp_c"] = nv.get("temperature")
        if r["power_cycles"] is None:
            r["power_cycles"] = nv.get("power_cycles")
        if nv.get("data_units_written") is not None:
            r["written_bytes"] = int(nv["data_units_written"]) * 512000  # NVMe counts 1000 x 512 bytes
    scsi_defects = doc.get("scsi_grown_defect_list")
    if scsi_defects is not None:
        r["attributes"][5] = {"name": "Grown_defect_list", "value": None, "thresh": None, "raw": int(scsi_defects)}
    r["self_tests"] = _self_tests(doc)
    return r


def _self_tests(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The drive's own self-test log, newest first: kind, passed, hours when run."""
    out = []
    ata = (((doc.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table")) or []
    for t in ata:
        st = t.get("status") or {}
        out.append(
            {
                "kind": "long" if "extended" in str((t.get("type") or {}).get("string", "")).lower() else "short",
                "passed": st.get("passed"),
                "status": st.get("string") or "",
                "hours": t.get("lifetime_hours"),
                "lba_first_error": t.get("lba"),
            }
        )
    nvme = ((doc.get("nvme_self_test_log") or {}).get("table")) or []
    for t in nvme:
        res = t.get("self_test_result") or {}
        code = res.get("value")
        out.append(
            {
                "kind": "long" if (t.get("self_test_code") or {}).get("value") == 2 else "short",
                "passed": code == 0 if isinstance(code, int) else None,
                "status": res.get("string") or "",
                "hours": t.get("power_on_hours"),
                "lba_first_error": t.get("lba"),
            }
        )
    return out


# --- history: what grew lately --------------------------------------------------------------------
COUNTERS = {  # history column -> attribute id it follows (NVMe ones have their own keys)
    "reallocated_sectors": 5,
    "pending_sectors": 197,
    "offline_uncorrectable": 198,
    "crc_errors": 199,
    "nvme_media_errors": "media_errors",
    "nvme_pct_used": "percentage_used",
    "command_timeouts": 188,
    "spin_retries": 10,
}


def growth(history: list[dict[str, Any]], now: float | None = None, days: int = TREND_DAYS) -> dict[str, int]:
    """How much each counter rose over the last `days` days of stored samples (0 when it did not)."""
    now = now or time.time()
    rows = sorted((h for h in history if h.get("ts")), key=lambda h: h["ts"])
    if len(rows) < 2:
        return {}
    start = next((h for h in rows if h["ts"] >= now - days * 86400), None)
    if start is None:
        return {}
    # the last sample before the window, when there is one, is the fairest starting point
    before = [h for h in rows if h["ts"] < start["ts"]]
    base = before[-1] if before else start
    last = rows[-1]
    return {k: max(0, int(last.get(k) or 0) - int(base.get(k) or 0)) for k in COUNTERS}


def from_history(last: dict[str, Any]) -> dict[str, Any]:
    """Readings rebuilt from the newest stored sample (a sleeping drive is judged on these)."""
    return {
        "protocol": "nvme" if (last.get("nvme_pct_used") or last.get("nvme_media_errors")) else "ata",
        "model": "",
        "serial": "",
        "smart_passed": None,
        "temp_c": last.get("temp"),
        "power_on_hours": last.get("power_on_hours") or None,
        "attributes": {
            5: {"name": "Reallocated_Sector_Ct", "raw": int(last.get("reallocated_sectors") or 0)},
            197: {"name": "Current_Pending_Sector", "raw": int(last.get("pending_sectors") or 0)},
            198: {"name": "Offline_Uncorrectable", "raw": int(last.get("offline_uncorrectable") or 0)},
            199: {"name": "UDMA_CRC_Error_Count", "raw": int(last.get("crc_errors") or 0)},
            188: {"name": "Command_Timeout", "raw": int(last.get("command_timeouts") or 0)},
            10: {"name": "Spin_Retry_Count", "raw": int(last.get("spin_retries") or 0)},
        },
        "failing_attributes": [],
        "self_tests": [],
        "from_history_ts": last.get("ts"),
    }


# --- the rules ------------------------------------------------------------------------------------
# Every finding carries a message key and the values in it, so the interface shows it in the
# reader's language (dh.f.<key>.title / .detail / .action in the locale files). The English text
# here is the same message filled in; tests/test_drive_health.py keeps the two in step.
def _f(
    code: str,
    severity: str,
    kind: str,
    title: str,
    detail: str,
    action: str,
    *,
    key: str | None = None,
    params: dict[str, Any] | None = None,
    **evidence: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "key": key or code,
        "params": params or {},
        "severity": severity,
        "kind": kind,
        "title": title,
        "detail": detail,
        "action": action,
        "evidence": evidence,
    }


def _count(r: dict[str, Any], aid: int) -> int:
    return int(((r.get("attributes") or {}).get(aid) or {}).get("raw") or 0)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


BACKUP = "Copy what matters on it to another drive or a backup now"


def findings_for(
    r: dict[str, Any],
    grew: dict[str, int] | None = None,
    tests: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Every rule that applies to these readings, most severe first."""
    grew = grew or {}
    now = now or time.time()
    out: list[dict[str, Any]] = []
    nvme = r.get("protocol") == "nvme"
    days = TREND_DAYS

    # the drive's own verdict and its own tests
    if r.get("smart_passed") is False:
        out.append(
            _f(
                "smart_failed",
                NOW,
                REPLACE,
                "The drive reports that it is failing",
                "Its own health check (SMART overall status) says FAILED.",
                f"{BACKUP}, then replace it.",
                smart_passed=False,
            )
        )
    if r.get("failing_attributes"):
        names = ", ".join(r["failing_attributes"])
        out.append(
            _f(
                "attribute_failing",
                NOW,
                REPLACE,
                "A health value is below the maker's limit",
                f"Failing now: {names}.",
                f"{BACKUP}, then replace it.",
                params={"names": names},
                attributes=r["failing_attributes"],
            )
        )
    drive_tests = r.get("self_tests") or []
    if drive_tests and drive_tests[0].get("passed") is False:
        t = drive_tests[0]
        status = t.get("status") or "a read error"
        out.append(
            _f(
                "self_test_failed",
                NOW,
                REPLACE,
                "Its last self-test failed",
                f"The test stopped with: {status}.",
                f"{BACKUP}, then replace it.",
                params={"status": status},
                test=t,
            )
        )

    # sectors it could not read or had to replace
    pending, offline, reported = _count(r, 197), _count(r, 198), _count(r, 187)
    if pending or offline or reported:
        n = max(pending, offline, reported)
        worse = bool(grew.get("pending_sectors") or grew.get("offline_uncorrectable"))
        out.append(
            _f(
                "unreadable_sectors",
                NOW if worse else SOON,
                REPLACE,
                "Parts of the disk could not be read" + (" and it is getting worse" if worse else ""),
                f"{_plural(n, 'sector', 'sectors')} could not be read back. Files there may already be damaged.",
                f"{BACKUP}. Run a long self-test, and plan to replace the drive.",
                key="unreadable_sectors_worse" if worse else "unreadable_sectors",
                params={"n": n},
                pending=pending,
                offline_uncorrectable=offline,
                reported_uncorrectable=reported,
                grew_pending=grew.get("pending_sectors", 0),
                grew_offline=grew.get("offline_uncorrectable", 0),
            )
        )
    realloc = _count(r, 5)
    if realloc:
        rising = grew.get("reallocated_sectors", 0)
        if rising:
            out.append(
                _f(
                    "reallocated_growing",
                    SOON,
                    REPLACE,
                    "The drive keeps replacing worn-out sectors",
                    f"{_plural(rising, 'sector was', 'sectors were')} replaced in the last {days} days "
                    f"({realloc} in all). A drive that keeps doing this usually fails within months.",
                    f"{BACKUP} and plan to replace it.",
                    params={"rising": rising, "total": realloc, "days": days},
                    reallocated=realloc,
                    grew=rising,
                )
            )
        elif realloc >= 100:
            out.append(
                _f(
                    "reallocated_many",
                    SOON,
                    REPLACE,
                    "Many sectors have been replaced",
                    f"{realloc} sectors were replaced over the drive's life. The count is stable for now.",
                    "Keep backups current and plan a replacement.",
                    params={"n": realloc},
                    reallocated=realloc,
                )
            )
        else:
            out.append(
                _f(
                    "reallocated_stable",
                    WATCH,
                    REPLACE,
                    "Some sectors were replaced, a while ago",
                    f"{_plural(realloc, 'sector was', 'sectors were')} replaced and the number has not moved "
                    f"in the last {days} days. That alone is not a reason to replace the drive.",
                    "Nothing to do now. If the number starts to rise, replace it.",
                    params={"n": realloc, "days": days},
                    reallocated=realloc,
                )
            )
    spins = _count(r, 10)
    if spins:
        rising = grew.get("spin_retries", 0)
        out.append(
            _f(
                "spin_retries",
                SOON,
                REPLACE,
                "The motor needed several tries to spin up" + (", more of them lately" if rising else ""),
                f"Spin-up retries: {spins}"
                + (f", {rising} of them in the last {days} days" if rising else "")
                + ". A weak motor or a power problem.",
                f"Check the power cable and supply; if they are fine, {BACKUP.lower()} and replace the drive.",
                key="spin_retries_growing" if rising else "spin_retries",
                params={"n": spins, "rising": rising, "days": days},
                spin_retries=spins,
                grew=rising,
            )
        )
    if _count(r, 184):
        out.append(
            _f(
                "end_to_end",
                SOON,
                REPLACE,
                "Data got corrupted inside the drive",
                f"End-to-end errors: {_count(r, 184)}. The drive's own path from cache to disk is faulty.",
                f"{BACKUP} and replace the drive.",
                params={"n": _count(r, 184)},
                end_to_end=_count(r, 184),
            )
        )
    timeouts = _count(r, 188)
    if timeouts:
        rising = grew.get("command_timeouts", 0)
        many = timeouts >= 100
        if rising:
            # new timeouts since the last weeks: something is wrong now, most often the cable
            out.append(
                _f(
                    "command_timeouts",
                    WATCH,
                    CABLE,
                    "Commands to the drive keep timing out",
                    f"{_plural(rising, 'timeout', 'timeouts')} in the last {days} days ({timeouts} in all). "
                    "Usually a loose cable, a weak power supply or a busy controller.",
                    "Reseat the data and power cables, or try another port.",
                    key="command_timeouts_growing",
                    params={"rising": rising, "total": timeouts, "days": days},
                    command_timeouts=timeouts,
                    grew=rising,
                )
            )
        else:
            out.append(
                _f(
                    "command_timeouts",
                    WATCH if many else OK,
                    CABLE if many else INFO,
                    "Many commands to the drive timed out" if many else "A few commands timed out at some point",
                    f"Command timeouts: {timeouts}. Usually a loose cable, a weak power supply or a busy controller.",
                    "Reseat the data and power cables, or try another port."
                    if many
                    else "Nothing to do unless other errors appear; then check its cables.",
                    key="command_timeouts_many" if many else "command_timeouts_few",
                    params={"n": timeouts},
                    command_timeouts=timeouts,
                )
            )

    # not the drive's fault: the cable
    crc = _count(r, 199)
    if crc:
        rising = grew.get("crc_errors", 0)
        if rising:
            out.append(
                _f(
                    "cable_errors",
                    WATCH,
                    CABLE,
                    "Errors on the cable to this drive",
                    f"{_plural(rising, 'transfer error', 'transfer errors')} in the last {days} days "
                    f"({crc} in all). The drive itself is fine; the data got garbled on the way.",
                    "Reseat or replace the SATA cable, or move the drive to another bay.",
                    params={"rising": rising, "total": crc, "days": days},
                    crc=crc,
                    grew=rising,
                )
            )
        else:
            out.append(
                _f(
                    "cable_errors_old",
                    OK,
                    INFO,
                    "Old cable errors, none lately",
                    f"{_plural(crc, 'transfer error was', 'transfer errors were')} counted at some point, "
                    f"none in the last {days} days.",
                    "Nothing to do.",
                    params={"n": crc, "days": days},
                    crc=crc,
                )
            )

    # NVMe and SSD wear
    nv = r.get("nvme") or {}
    if nv:
        cw = int(nv.get("critical_warning") or 0)
        if cw & 0x01 or (
            nv.get("available_spare") is not None
            and nv.get("available_spare_threshold") is not None
            and nv["available_spare"] <= nv["available_spare_threshold"]
        ):
            spare, limit = nv.get("available_spare"), nv.get("available_spare_threshold")
            out.append(
                _f(
                    "nvme_spare",
                    NOW,
                    REPLACE,
                    "The SSD has run out of spare blocks",
                    f"Spare blocks left: {spare}% (the maker's limit is {limit}%).",
                    f"{BACKUP}, then replace it.",
                    params={"spare": spare, "limit": limit},
                    available_spare=spare,
                )
            )
        if cw & 0x04:
            out.append(
                _f(
                    "nvme_degraded",
                    NOW,
                    REPLACE,
                    "The SSD reports it is no longer reliable",
                    "Its own reliability flag is set (critical warning bit 2).",
                    f"{BACKUP}, then replace it.",
                    critical_warning=cw,
                )
            )
        if cw & 0x08:
            out.append(
                _f(
                    "nvme_read_only",
                    NOW,
                    REPLACE,
                    "The SSD has switched itself to read-only",
                    "It no longer accepts writes, to protect what is on it.",
                    "Copy everything off it, then replace it.",
                    critical_warning=cw,
                )
            )
        if cw & 0x10:
            out.append(
                _f(
                    "nvme_backup_failed",
                    SOON,
                    REPLACE,
                    "The SSD's power-loss protection failed",
                    "Data in its cache may be lost in a power cut (critical warning bit 4).",
                    "Keep it on a UPS and plan a replacement.",
                    critical_warning=cw,
                )
            )
        used = nv.get("percentage_used")
        if isinstance(used, int) and used >= 80:
            past = used >= 100
            out.append(
                _f(
                    "nvme_wear",
                    SOON if past else WATCH,
                    REPLACE,
                    "The SSD is past its rated life" if past else "The SSD is wearing out",
                    f"{used}% of its rated writes are used up.",
                    "Replace it soon; it can fail without warning now." if past else "Plan a replacement.",
                    key="nvme_wear_past" if past else "nvme_wear",
                    params={"used": used},
                    percentage_used=used,
                )
            )
        media = int(nv.get("media_errors") or 0)
        if media:
            rising = grew.get("nvme_media_errors", 0)
            out.append(
                _f(
                    "nvme_media_errors",
                    SOON if rising else WATCH,
                    REPLACE,
                    "The SSD could not read some data" + (" and it is getting worse" if rising else ""),
                    f"Media errors: {media}" + (f", {rising} of them in the last {days} days." if rising else "."),
                    f"{BACKUP}." + (" Plan to replace it." if rising else " If the count rises, replace it."),
                    key="nvme_media_errors_growing" if rising else "nvme_media_errors",
                    params={"n": media, "rising": rising, "days": days},
                    media_errors=media,
                    grew=rising,
                )
            )
    for aid, name in ((231, "SSD_Life_Left"), (233, "Media_Wearout_Indicator"), (177, "Wear_Leveling_Count")):
        a = (r.get("attributes") or {}).get(aid)
        if a and isinstance(a.get("value"), int) and a["value"] <= 20 and not nv:
            attr = a.get("name") or name
            out.append(
                _f(
                    "ssd_wear",
                    SOON if a["value"] <= 10 else WATCH,
                    REPLACE,
                    "The SSD is wearing out",
                    f"About {a['value']}% of its life is left ({attr}).",
                    "Plan a replacement.",
                    params={"left": a["value"], "attr": attr},
                    life_left=a["value"],
                )
            )
            break

    # heat: the room or the fans, not the drive
    temp = r.get("temp_c")
    if isinstance(temp, (int, float)):
        hot, critical = (NVME_HOT_C, NVME_CRITICAL_C) if nvme else (HDD_HOT_C, HDD_CRITICAL_C)
        if temp >= critical:
            out.append(
                _f(
                    "too_hot",
                    SOON,
                    COOLING,
                    "The drive is too hot",
                    f"{temp:g} °C now; it should stay below {hot} °C.",
                    "Check that the fans run and nothing blocks the airflow. Heat shortens a drive's life.",
                    params={"temp": f"{temp:g}", "limit": hot},
                    temp_c=temp,
                )
            )
        elif temp >= hot:
            out.append(
                _f(
                    "warm",
                    WATCH,
                    COOLING,
                    "The drive runs warm",
                    f"{temp:g} °C now; below {hot} °C is better for its life.",
                    "Check the fan curve and the airflow around it.",
                    params={"temp": f"{temp:g}", "limit": hot},
                    temp_c=temp,
                )
            )

    # age and testing
    hours = r.get("power_on_hours")
    if isinstance(hours, int) and hours >= OLD_HDD_HOURS and not nvme and r.get("rotation_rpm") != 0:
        out.append(
            _f(
                "old_drive",
                WATCH,
                REPLACE,
                "An old drive",
                f"Powered on for {hours // 8760} years. Failures become more likely after five.",
                "Nothing urgent. Keep backups current and budget for a replacement.",
                params={"years": hours // 8760},
                power_on_hours=hours,
            )
        )
    last_test = (tests or [None])[0]
    if last_test is None or (now - float(last_test.get("ts") or 0)) > TEST_STALE_DAYS * 86400:
        out.append(
            _f(
                "no_recent_test",
                OK,
                TEST,
                "No self-test lately",
                "A long self-test reads the whole surface and finds bad spots before your files do.",
                "Run a long self-test (it runs in the background; the drive stays usable).",
                last_test_ts=(last_test or {}).get("ts"),
            )
        )

    out.sort(key=lambda f: -ORDER[f["severity"]])
    return out


LABELS = {  # label key -> English label (dh.label.<key> in the locale files)
    "ok": "Healthy",
    "watch": "Keep an eye on it",
    "soon_replace": "Replace soon",
    "now_replace": "Replace now",
    "soon_other": "Needs attention",
    "now_other": "Needs attention now",
    "unknown": "Not read yet",
}


def assess(
    readings: dict[str, Any] | None,
    history: list[dict[str, Any]] | None = None,
    tests: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """The verdict for one drive: {verdict, label, summary, findings, from_history}, plus the keys
    the interface translates them by (label_key, summary_key, summary_params)."""
    history = history or []
    if not readings and history:
        readings = from_history(max(history, key=lambda h: h.get("ts") or 0))
    if not readings:
        return {
            "verdict": "unknown",
            "label": LABELS["unknown"],
            "label_key": "unknown",
            "summary": "No reading of this drive yet.",
            "summary_key": "unread",
            "summary_params": {},
            "findings": [],
            "from_history": False,
        }
    findings = findings_for(readings, growth(history, now), tests, now)
    return {
        **summarize(findings),
        "from_history": bool(readings.get("from_history_ts")),
        "reading_ts": readings.get("from_history_ts"),
        "identity": identity(readings),
    }


def summarize(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """The verdict, label and one-line summary from a drive's findings (the most severe one leads).
    Also used again after the owner acknowledged some of them (drive_notes.apply_acks)."""
    worst = max((f["severity"] for f in findings), key=lambda s: ORDER[s], default=OK)
    top = next((f for f in findings if f["severity"] == worst), None)
    if worst in (OK, WATCH):
        label_key = worst
    else:
        label_key = f"{worst}_{'replace' if top and top['kind'] == REPLACE else 'other'}"
    trouble = bool(top and worst != OK)
    return {
        "verdict": worst,
        "label": LABELS[label_key],
        "label_key": label_key,
        "summary": top["title"] if trouble and top else "No sign of trouble.",
        # a finding's title (dh.f.<key>.title), or dh.f.fine.title when there is nothing to report
        "summary_key": top["key"] if trouble and top else "fine",
        "summary_params": top["params"] if trouble and top else {},
        "findings": findings,
    }


IDENTITY_KEYS = (
    "protocol",
    "capacity_bytes",
    "rotation_rpm",
    "firmware",
    "power_cycles",
    "form_factor",
    "link",
    "written_bytes",
)


def identity(readings: dict[str, Any]) -> dict[str, Any]:
    """The drive's make-up from a live reading: interface, size, speed, firmware (empty from history)."""
    if readings.get("from_history_ts"):
        return {}
    return {k: readings[k] for k in IDENTITY_KEYS if readings.get(k) not in (None, "")}


COUNTERS = (
    "reallocated_sectors",
    "pending_sectors",
    "offline_uncorrectable",
    "crc_errors",
    "command_timeouts",
    "spin_retries",
    "nvme_media_errors",
)


def history_view(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Temperature and error counters over the stored samples, for the History charts. Only
    counters that were ever above zero are sent."""
    temps = [(int(s["ts"]), float(s["temp"])) for s in samples if s.get("temp") not in (None, 0)]
    temp = None
    if temps:
        values = [v for _, v in temps]
        temp = {
            "points": temps,
            "min": min(values),
            "max": max(values),
            "avg": round(sum(values) / len(values), 1),
            "now": values[-1],
        }
    counters = {}
    for key in COUNTERS:
        series = [(int(s["ts"]), int(s.get(key) or 0)) for s in samples]
        if any(v for _, v in series):
            counters[key] = {"points": series, "first": series[0][1], "last": series[-1][1]}
    span = (samples[-1]["ts"] - samples[0]["ts"]) / 86400 if len(samples) > 1 else 0
    return {"temp": temp, "counters": counters, "days": round(span, 1), "samples": len(samples)}


HOURS_PER_YEAR = 8766


def life_outlook(samples: list[dict[str, Any]], min_days: float = 7.0) -> dict[str, Any]:
    """Age, and for NVMe drives how fast their rated writes are used up, from measurements only:
    no estimate until the wear figure has moved over at least a week."""
    if not samples:
        return {"age_years": None}
    hours = max(int(s.get("power_on_hours") or 0) for s in samples)
    out: dict[str, Any] = {
        "power_on_hours": hours or None,
        "age_years": round(hours / HOURS_PER_YEAR, 1) if hours else None,
    }
    worn = [s for s in samples if s.get("nvme_pct_used") is not None]
    if worn and any(s.get("nvme_pct_used") for s in worn):
        first, last = worn[0], worn[-1]
        used = int(last.get("nvme_pct_used") or 0)
        out["wear_pct"] = used
        span_years = (last["ts"] - first["ts"]) / (365.25 * 86400)
        moved = used - int(first.get("nvme_pct_used") or 0)
        if span_years * 365.25 >= min_days and moved > 0:
            per_year = moved / span_years
            out["wear_per_year"] = round(per_year, 1)
            out["years_left"] = round(max(0, 100 - used) / per_year, 1)
        else:
            out["years_left"] = None
    return out
