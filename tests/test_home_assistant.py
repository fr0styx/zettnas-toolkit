"""Home Assistant over MQTT discovery (RES-5): the packets, the sensors, the API."""

import json
import socket
import threading

import pytest

from backend.services import home_assistant as ha
from backend.services import mqtt_lite


def test_remaining_length_is_mqtts_variable_length():
    assert mqtt_lite.remaining_length(0) == b"\x00"
    assert mqtt_lite.remaining_length(127) == b"\x7f"
    assert mqtt_lite.remaining_length(128) == b"\x80\x01"
    assert mqtt_lite.remaining_length(16383) == b"\xff\x7f"
    assert mqtt_lite.remaining_length(16384) == b"\x80\x80\x01"


def test_connect_and_publish_packets():
    p = mqtt_lite.connect_packet("kib", "user", "pw")
    assert p[0] == 0x10 and p[2:8] == b"\x00\x04MQTT" and p[8] == 4 and p[9] == 0xC2
    assert p.endswith(b"\x00\x04user\x00\x02pw")
    assert mqtt_lite.connect_packet("kib")[9] == 0x02  # no user: clean session only
    pub = mqtt_lite.publish_packet("a/b", "x", retain=True)
    assert pub == b"\x31\x06\x00\x03a/bx"
    assert mqtt_lite.publish_packet("a/b", "x", retain=False)[0] == 0x30


class Broker:
    """A broker that answers CONNECT with the given code and records what is published."""

    def __init__(self, code=0):
        self.code, self.topics, self.login = code, {}, None
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _read_packet(self, conn):
        head = conn.recv(1)
        if not head:
            return None, b""
        mult, length = 1, 0
        while True:
            b = conn.recv(1)[0]
            length += (b & 0x7F) * mult
            mult *= 128
            if not b & 0x80:
                break
        body = b""
        while len(body) < length:
            body += conn.recv(length - len(body))
        return head[0], body

    def _serve(self):
        conn, _ = self.server.accept()
        with conn:
            kind, body = self._read_packet(conn)
            assert kind == 0x10
            self.login = body
            conn.sendall(bytes([0x20, 2, 0, self.code]))
            while True:
                kind, body = self._read_packet(conn)
                if kind is None or kind == 0xE0:
                    break
                n = int.from_bytes(body[:2], "big")
                self.topics[body[2 : 2 + n].decode()] = (body[2 + n :].decode(), bool(kind & 1))
        self.server.close()


STATS = {
    "cpu": {"util": 12.5, "temp": 48},
    "mem": {"pct": 40.1},
    "disks": [{"name": "sda", "temp": 35}, {"name": "sdb", "temp": 41}, {"name": "nvme0n1", "temp": None}],
    "ups": {"available": True, "battery_charge_pct": 100, "time_left_min": 42, "load_pct": 18, "on_battery": False},
}


def test_the_sensors_come_from_the_live_stats():
    found = {s["key"]: s for s in ha.sensors(STATS)}
    assert found["cpu_usage"]["value"] == 12.5 and found["cpu_temperature"]["device_class"] == "temperature"
    assert found["disk_sda_temperature"]["value"] == 35 and "disk_nvme0n1_temperature" not in found
    assert found["hottest_disk_temperature"]["value"] == 41
    assert found["ups_on_battery"]["component"] == "binary_sensor" and found["ups_on_battery"]["value"] is False
    assert "ups_battery" not in {s["key"] for s in ha.sensors({"ups": {"available": False}})}


def test_discovery_announces_each_sensor_and_one_state_message(monkeypatch):
    monkeypatch.setattr(ha, "node_id", lambda: "nas")
    msgs = ha.messages({"discovery_prefix": "homeassistant", "interval_s": 60}, STATS)
    topics = [t for t, _, _ in msgs]
    assert "homeassistant/sensor/kiboto_nas/cpu_usage/config" in topics
    assert "homeassistant/binary_sensor/kiboto_nas/ups_on_battery/config" in topics
    conf = json.loads(dict((t, p) for t, p, _ in msgs)["homeassistant/sensor/kiboto_nas/cpu_temperature/config"])
    assert conf["state_topic"] == "kiboto/nas/state" and conf["expire_after"] == 180
    assert conf["unique_id"] == "kiboto_nas_cpu_temperature" and conf["device"]["manufacturer"] == "Kiboto"
    state = json.loads(msgs[-1][1])
    assert msgs[-1][0] == "kiboto/nas/state" and state["cpu_usage"] == 12.5 and state["ups_on_battery"] is False
    assert all(retain for _, _, retain in msgs)
    assert len(ha.messages({}, STATS, announce=False)) == 1  # after the first send, only the values


def test_it_publishes_to_a_broker_and_says_why_one_refuses(monkeypatch):
    monkeypatch.setattr(ha, "node_id", lambda: "nas")
    broker = Broker()
    out = ha.publish_once({"host": "127.0.0.1", "port": broker.port, "username": "u", "password": "p"}, STATS)
    assert out["sensors"] >= 8
    deadline = __import__("time").time() + 5
    while "kiboto/nas/state" not in broker.topics and __import__("time").time() < deadline:
        __import__("time").sleep(0.02)
    assert broker.topics["kiboto/nas/state"][1] is True
    assert b"\x00\x01u\x00\x01p" in broker.login
    refusing = Broker(code=4)
    with pytest.raises(mqtt_lite.MqttError, match="wrong user name or password"):
        ha.publish_once({"host": "127.0.0.1", "port": refusing.port}, STATS)
    assert ha.public_config()["status"]["last_ok"] is False


def test_the_api_keeps_the_password_sealed(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "CONFIG_FILE", str(tmp_path / "ha.json"))
    r = client.put("/api/integrations/home-assistant", json={"enabled": True}, headers=auth_headers)
    assert r.status_code == 400
    r = client.put(
        "/api/integrations/home-assistant",
        json={"host": "mqtt.lan", "username": "kib", "password": "s3cret"},
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["has_password"] is True and "password" not in r.json()
    assert "s3cret" not in (tmp_path / "ha.json").read_text()
    r = client.put("/api/integrations/home-assistant", json={"port": 8883, "tls": True}, headers=auth_headers)
    assert r.json()["has_password"] is True and r.json()["port"] == 8883  # left out: kept
    assert ha.load_config()["password"] == "s3cret"
    assert (
        client.put("/api/integrations/home-assistant", json={"password": ""}, headers=auth_headers).json()[
            "has_password"
        ]
        is False
    )
    assert (
        client.put("/api/integrations/home-assistant", json={"interval_s": 5}, headers=auth_headers).status_code == 422
    )
