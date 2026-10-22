"""
Unit tests for backend/fast_json.py
Verifies orjson acceleration, fallback handling, integer dict key sanitization,
and non-serializable object conversion.
"""

import math
import warnings

from backend.fast_json import FastJSONResponse, dumps, dumps_bytes, loads


def test_fast_json_roundtrip():
    data = {
        "status": "healthy",
        "cpu_temp": 42.5,
        "active_disks": ["sda", "sdb", "sdc"],
        "nested": {"fans": [1200, 1500], "zero_rpm": True},
    }
    serialized = dumps(data)
    assert isinstance(serialized, str)
    deserialized = loads(serialized)
    assert deserialized == data


def test_fast_json_integer_dict_keys():
    # SMART metrics attribute maps have integer IDs (e.g. 194, 5, 197)
    smart_map = {
        194: {"name": "Temperature_Celsius", "raw": 38},
        5: {"name": "Reallocated_Sector_Ct", "raw": 0},
        197: {"name": "Current_Pending_Sector", "raw": 0},
    }
    serialized = dumps(smart_map)
    assert isinstance(serialized, str)
    deserialized = loads(serialized)
    # Integer keys are safely converted to strings by fast_json
    assert deserialized["194"]["raw"] == 38
    assert deserialized["5"]["raw"] == 0


def test_fast_json_set_and_bytes_handling():
    data = {
        "tags": {"nas", "storage", "zettlab"},
        "signature": b"header_magic",
    }
    raw_bytes = dumps_bytes(data)
    assert isinstance(raw_bytes, bytes)
    deserialized = loads(raw_bytes)
    assert sorted(deserialized["tags"]) == ["nas", "storage", "zettlab"]
    assert deserialized["signature"] == "header_magic"


def test_fast_json_response_matches_orjson_response():
    """FastJSONResponse gives the same bytes FastAPI's ORJSONResponse did."""
    import orjson

    payload = {
        "cpu": {"temp": math.nan, "util": 12.25, "load_avg": [0.5, math.inf, -math.inf]},
        194: {"raw": 38},
        "name": "Zettlab D8 \u00fc",
        "big": 2**40,
    }
    body = FastJSONResponse(payload).body
    assert body == orjson.dumps(payload, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY)
    assert loads(body)["cpu"] == {"temp": None, "util": 12.25, "load_avg": [0.5, None, None]}
    assert loads(body)["194"] == {"raw": 38}


def test_app_default_response_is_not_deprecated(client, auth_headers):
    """No FastAPI deprecation warning from the default response class (issue #29)."""
    import app as app_module

    assert app_module.app.router.default_response_class is FastJSONResponse
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        r = client.get("/api/lcd_status", headers=auth_headers)
    assert r.status_code == 200
    assert not [w for w in caught if "ORJSONResponse" in str(w.message)]
