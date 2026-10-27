"""Drive Health speaks the reader's language: every finding has a message in the locale files,
and the English message filled in with the finding's values is exactly the server's text."""

import json
import pathlib
import re
import time

from backend import db
from backend.services import drive_health as dh
from tests.test_drive_health import NOW, ata, history, nvme, verdict

LOCALES = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "locales"


def strings(lang="en"):
    out = {}
    for line in (LOCALES / f"{lang}.js").read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*"((?:dh\.f|dh\.label)\.[\w.]+)":\s*(".*"),?\s*$', line)
        if m:
            out[m.group(1)] = json.loads(m.group(2))
    return out


def fill(msg, params):
    """The ICU subset t() handles: {n, plural, one {...} other {...}} with #, then {name}."""

    def plural(m):
        n = int(params[m.group(1)])
        one, other = m.group(2), m.group(3)
        return (one if n == 1 else other).replace("#", str(n))

    msg = re.sub(r"\{(\w+), plural, one \{([^{}]*)\} other \{([^{}]*)\}\}", plural, msg)
    return re.sub(r"\{(\w+)\}", lambda m: str(params[m.group(1)]), msg)


def every_finding():
    grew_all = history(
        pending_sectors=(1, 3),
        reallocated_sectors=(0, 2),
        spin_retries=(1, 2),
        command_timeouts=(2, 5),
        crc_errors=(2, 4),
    )
    docs = [
        (
            ata(
                {
                    197: ("Current_Pending_Sector", 3, 100),
                    5: ("Reallocated_Sector_Ct", 1, 100),
                    10: ("Spin_Retry_Count", 2, 100),
                    184: ("End-to-End_Error", 1, 99),
                    188: ("Command_Timeout", 5, 100),
                    199: ("UDMA_CRC_Error_Count", 1, 200),
                    231: ("SSD_Life_Left", 0, 15),
                    1: ("Raw_Read_Error_Rate", 0, 5),
                },
                passed=False,
                temp=62,
                hours=50000,
                failing=("Raw_Read_Error_Rate",),
                tests=[{"type": {"string": "Extended offline"}, "status": {"string": "read failure", "passed": False}}],
            ),
            [],
            None,
        ),
        (
            ata(
                {
                    197: ("Current_Pending_Sector", 3, 100),
                    5: ("Reallocated_Sector_Ct", 2, 100),
                    10: ("Spin_Retry_Count", 2, 100),
                    188: ("Command_Timeout", 5, 100),
                    199: ("UDMA_CRC_Error_Count", 4, 200),
                },
                temp=55,
            ),
            grew_all,
            None,
        ),
        (ata({5: ("Reallocated_Sector_Ct", 150, 90), 188: ("Command_Timeout", 200, 100)}), [], None),
        (nvme(critical_warning=0x1D, available_spare=5, percentage_used=85, media_errors=2), [], None),
        (nvme(percentage_used=110, media_errors=3), history(nvme_media_errors=(1, 3)), None),
    ]
    out = {}
    for doc, hist, tests in docs:
        for f in dh.findings_for(dh.read_smartctl(doc), dh.growth(hist, NOW), tests, NOW):
            out.setdefault(f["key"], f)
    return out


def test_every_finding_reads_the_same_as_its_english_message():
    en = strings()
    found = every_finding()
    for key, f in found.items():
        for part in ("title", "detail", "action"):
            msg = en.get(f"dh.f.{key}.{part}")
            assert msg is not None, f"dh.f.{key}.{part} is missing from en.js"
            assert fill(msg, f["params"]) == f[part], (key, part)
    # and every message in the locale file belongs to a finding the rules can produce
    used = {k.split(".")[2] for k in en if k.startswith("dh.f.")} - {"fine", "unread"}
    assert used == set(found), used ^ set(found)


def test_every_language_has_every_drive_health_message():
    en = strings()
    for lang in ("de", "fr", "es", "zh"):
        other = strings(lang)
        assert set(other) == set(en), (lang, set(en) ^ set(other))
        for k, v in other.items():
            assert set(re.findall(r"\{(\w+)[,}]", v)) == set(re.findall(r"\{(\w+)[,}]", en[k])), (lang, k)


def test_verdicts_carry_their_label_and_summary_keys():
    en = strings()
    fine = verdict(ata())
    assert (fine["label_key"], fine["summary_key"]) == ("ok", "fine")
    assert en["dh.f.fine.title"] == fine["summary"]
    bad = verdict(ata({197: ("Current_Pending_Sector", 4, 100)}), history(pending_sectors=(0, 4)))
    assert bad["label_key"] == "now_replace" and bad["summary_key"] == "unreadable_sectors_worse"
    assert fill(en["dh.f.unreadable_sectors_worse.title"], bad["summary_params"]) == bad["summary"]
    unread = dh.assess(None)
    assert unread["label_key"] == "unknown" and en["dh.f.unread.title"] == unread["summary"]
    for key, label in dh.LABELS.items():
        assert en[f"dh.label.{key}"] == label


def test_timeouts_that_keep_coming_point_at_the_cable():
    doc = ata({188: ("Command_Timeout", 7, 100)})
    assert verdict(doc, history(command_timeouts=(7, 7)))["verdict"] == "ok"
    v = verdict(doc, history(command_timeouts=(2, 7)))
    f = v["findings"][0]
    assert v["verdict"] == "watch" and f["key"] == "command_timeouts_growing" and f["kind"] == "cable"


def test_the_history_keeps_timeouts_and_spin_retries():
    db.init_db()
    t0 = int(time.time()) - 3600
    db.log_smart_metrics(t0, "hist_dh", 35.0, {"timeouts": 3, "spin_retries": 1})
    db.log_smart_metrics(t0 + 30, "hist_dh", 35.0, {"timeouts": 4, "spin_retries": 1})  # a counter moved
    rows = db.get_smart_history_samples("hist_dh", days=1, bucket_secs=10)
    assert [(r["command_timeouts"], r["spin_retries"]) for r in rows] == [(3, 1), (4, 1)]
    # a sleeping drive is judged on them too
    readings = dh.from_history(rows[-1])
    assert readings["attributes"][188]["raw"] == 4 and readings["attributes"][10]["raw"] == 1
