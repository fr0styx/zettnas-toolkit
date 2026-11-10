"""Just enough MQTT 3.1.1 to publish: connect, send retained messages at QoS 0, disconnect.

Home Assistant's MQTT discovery needs nothing more, and a short connection per update leaves no
socket to babysit. Plain TCP or TLS; a user name and password when the broker asks for them.
"""

from __future__ import annotations

import socket
import ssl

CONNACK_REFUSED = {
    1: "the broker doesn't speak MQTT 3.1.1",
    2: "the broker refused the client id",
    3: "the broker is unavailable",
    4: "wrong user name or password",
    5: "not allowed to connect",
}


class MqttError(OSError):
    pass


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > 65535:
        raise MqttError("a field is longer than MQTT allows")
    return len(raw).to_bytes(2, "big") + raw


def remaining_length(n: int) -> bytes:
    out = bytearray()
    while True:
        digit, n = n % 128, n // 128
        out.append(digit | (0x80 if n else 0))
        if not n:
            return bytes(out)


def packet(kind: int, body: bytes) -> bytes:
    return bytes([kind]) + remaining_length(len(body)) + body


def connect_packet(client_id: str, username: str = "", password: str = "", keepalive: int = 60) -> bytes:
    flags = 0x02  # a clean session: nothing is kept between updates
    if username:
        flags |= 0x80
        if password:
            flags |= 0x40
    body = _string("MQTT") + bytes([4, flags]) + keepalive.to_bytes(2, "big") + _string(client_id)
    if username:
        body += _string(username)
        if password:
            body += _string(password)
    return packet(0x10, body)


def publish_packet(topic: str, payload: str, retain: bool = True) -> bytes:
    return packet(0x30 | (0x01 if retain else 0), _string(topic) + payload.encode("utf-8"))


def _read(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise MqttError("the broker closed the connection")
        data += chunk
    return data


def publish(
    host: str,
    port: int,
    messages: list[tuple[str, str, bool]],
    username: str = "",
    password: str = "",
    client_id: str = "kiboto",
    tls: bool = False,
    timeout: float = 10.0,
) -> int:
    """Sends (topic, payload, retain) messages; returns how many. Raises MqttError."""
    raw = socket.create_connection((host, int(port)), timeout=timeout)
    sock: socket.socket = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if tls else raw
    try:
        sock.settimeout(timeout)
        sock.sendall(connect_packet(client_id, username, password))
        ack = _read(sock, 4)
        if ack[0] != 0x20:
            raise MqttError("the broker didn't answer like an MQTT broker")
        if ack[3] != 0:
            raise MqttError(CONNACK_REFUSED.get(ack[3], f"the broker refused the connection ({ack[3]})"))
        for topic, payload, retain in messages:
            sock.sendall(publish_packet(topic, payload, retain))
        sock.sendall(b"\xe0\x00")  # DISCONNECT
        return len(messages)
    finally:
        sock.close()
