"""AI-12: web searches carry no private data; risky Compose settings are pointed out."""

from backend.services.ai_safeguards import compose_risks, compose_warning_for_reply, safe_web_query


def test_web_query_drops_private_details():
    q, _ = safe_web_query(
        "why does 192.168.1.20 refuse ssh from me@example.com in /mnt/user/appdata/x key sk-abcdefghijkl1234"
    )
    assert q == "why does refuse ssh from in key"


def test_web_query_keeps_ordinary_numbers():
    q, _ = safe_web_query("jellyfin 10.10.7 release notes 2025")
    assert q == "jellyfin 10.10.7 release notes 2025"


def test_model_search_that_quotes_a_file_is_refused():
    private = ["Tarjeta sanitaria RUIZ CAR 0458 paciente Carmen Ruiz centro de salud Benimaclet"]
    q, why = safe_web_query("paciente Carmen Ruiz centro de salud Benimaclet", private)
    assert q is None and "files" in why
    assert safe_web_query("centro de salud opening hours", private)[0] == "centro de salud opening hours"


def test_compose_risks():
    yml = """services:
  app:
    image: x
    privileged: true
    network_mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - DB_PASSWORD=${DB_PASSWORD:-changeme_user}
"""
    risks = compose_risks(yml)
    assert len(risks) == 4
    assert compose_risks("services:\n  web:\n    image: nginx\n    ports: [8080:80]\n") == []


def test_reply_with_a_risky_compose_file_gets_a_note():
    reply = "Here you go:\n```yaml\nservices:\n  a:\n    image: x\n    privileged: true\n```"
    assert "Check before running" in compose_warning_for_reply(reply)
    assert compose_warning_for_reply("No compose here.") == ""
