"""Masked container views also hide passwords in URLs and secret flags (audit pass 2)."""

from backend.services import compose_synthesizer as cs

INSPECT = {
    "Name": "/app",
    "Id": "abc123456789",
    "Config": {
        "Env": ["DATABASE_URL=postgres://app:dummy-secret@db/app", "TZ=UTC"],
        "Entrypoint": ["/run"],
        "Cmd": ["--db-password=dummy-secret", "--port", "8080"],
        "Image": "x",
    },
    "HostConfig": {},
    "State": {},
    "NetworkSettings": {},
    "Mounts": [],
}


def test_details_hide_inline_secrets(monkeypatch):
    monkeypatch.setattr(cs, "fetch_container_raw_inspect", lambda cid: INSPECT)
    masked = cs.get_container_full_details("app")
    text = str(masked)
    assert "dummy-secret" not in text
    assert "postgres://app:" in text and "--port 8080" in text
    assert "dummy-secret" in str(cs.get_container_full_details("app", allow_unmasked=True))


def test_mask_inline_secrets():
    assert cs.mask_inline_secrets("redis://:pw@cache:6379") == "redis://:••••••••@cache:6379"
    assert cs.mask_inline_secrets("--token abc --name web") == "--token •••••••• --name web"
    assert cs.mask_inline_secrets("plain value") == "plain value"
