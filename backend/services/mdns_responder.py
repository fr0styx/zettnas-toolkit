"""Find the NAS by name (NFEAT-8): a small multicast DNS responder (RFC 6762, DNS-SD RFC 6763).

Runs in its own container on the host's network (the app's own container can't reach the LAN's
multicast), started by nas_name.py with the app's image. Standard library only.

It answers "<name>.local" with the NAS's address, so http://<name>.local:<port> works in a
browser on macOS, iOS, Windows 10+, Android and Linux, and \\\\<name>.local in Windows Explorer.
It advertises the web page (_http._tcp) and, when the host shares files over SMB, the file
server (_smb._tcp, with a server icon in Finder's sidebar). Older names (after a rename or the
rebrand) answer too, so bookmarks keep working. It shares port 5353 with a responder the host
may already run (Unraid's avahi).

Arguments: --names (first is the name, the rest still answer), --label (shown in Finder),
--http-port, --ip (else the address of the default route).
"""

import argparse
import signal
import socket
import struct
import sys
import time

GROUP, PORT = "224.0.0.251", 5353
A, PTR, TXT, AAAA, SRV, NSEC, ANY = 1, 12, 16, 28, 33, 47, 255
IN, CACHE_FLUSH = 1, 0x8000
TTL_HOST, TTL_OTHER = 120, 4500
SERVICES = "_services._dns-sd._udp.local"
MAX_PACKET = 9000


# --- wire format --------------------------------------------------------------------------------
def encode_name(name: str) -> bytes:
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("utf-8")[:63]
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def read_name(buf: bytes, off: int) -> tuple[str, int]:
    """A name at `off` (following compression pointers); returns it and the offset after it."""
    labels, end, jumps = [], None, 0
    while True:
        if off >= len(buf):
            raise ValueError("name runs past the packet")
        n = buf[off]
        if n & 0xC0 == 0xC0:
            if off + 1 >= len(buf) or jumps > 16:
                raise ValueError("bad pointer")
            if end is None:
                end = off + 2
            off = ((n & 0x3F) << 8) | buf[off + 1]
            jumps += 1
            continue
        if n == 0:
            return ".".join(labels), (end if end is not None else off + 1)
        if n > 63 or off + 1 + n > len(buf):
            raise ValueError("bad label")
        labels.append(buf[off + 1 : off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n


def parse_query(buf: bytes) -> tuple[int, list[tuple[str, int, int]]] | None:
    """(id, [(name, type, class)]) of a query; None for a response or a broken packet."""
    try:
        qid, flags, qd = struct.unpack("!HHH", buf[:6])
        if flags & 0x8000:
            return None
        off, out = 12, []
        for _ in range(min(qd, 64)):
            name, off = read_name(buf, off)
            qtype, qclass = struct.unpack("!HH", buf[off : off + 4])
            off += 4
            out.append((name.lower(), qtype, qclass))
        return qid, out
    except (ValueError, struct.error):
        return None


def answer_names(buf: bytes) -> list[tuple[str, int, bytes]]:
    """The (name, type, rdata) of a response's answers (for spotting another device with our name)."""
    try:
        _qid, flags, qd, an = struct.unpack("!HHHH", buf[:8])
        if not flags & 0x8000:
            return []
        off = 12
        for _ in range(qd):
            _name, off = read_name(buf, off)
            off += 4
        out = []
        for _ in range(min(an, 64)):
            name, off = read_name(buf, off)
            rtype, _cls, _ttl, rdlen = struct.unpack("!HHIH", buf[off : off + 10])
            off += 10
            out.append((name.lower(), rtype, buf[off : off + rdlen]))
            off += rdlen
        return out
    except (ValueError, struct.error):
        return []


def record(name: str, rtype: int, ttl: int, rdata: bytes, flush: bool = True) -> bytes:
    cls = IN | (CACHE_FLUSH if flush else 0)
    return encode_name(name) + struct.pack("!HHIH", rtype, cls, ttl, len(rdata)) + rdata


def txt(*items: str) -> bytes:
    return b"".join(bytes([len(i.encode())]) + i.encode() for i in items) or b"\x00"


# --- what we answer -----------------------------------------------------------------------------
class Responder:
    def __init__(self, names: list[str], ip: str, http_port: int, instance: str, smb: bool = False):
        self.names = [n.lower().removesuffix(".local") for n in names if n]
        self.host = f"{self.names[0]}.local"
        self.ip = ip
        self.http_port = http_port
        self.instance = instance
        self.smb = smb

    def _a(self, host: str, ttl: int, flush: bool = True) -> bytes:
        return record(host, A, ttl, socket.inet_aton(self.ip), flush)

    def services(self) -> dict[str, tuple[str, int, bytes]]:
        """service type -> (instance name, port, TXT)"""
        out = {"_http._tcp.local": (f"{self.instance}._http._tcp.local", self.http_port, txt("path=/"))}
        if self.smb:
            out["_smb._tcp.local"] = (f"{self.instance}._smb._tcp.local", 445, txt())
            out["_device-info._tcp.local"] = (f"{self.instance}._device-info._tcp.local", 0, txt("model=Xserve"))
        return out

    def _no_ipv6(self, host: str, ttl: int, flush: bool = True) -> bytes:
        """NSEC saying the name has an IPv4 address and nothing else, so a resolver asking for
        IPv6 hears "none" at once instead of waiting (RFC 6762 6.1)."""
        return record(host, NSEC, ttl, encode_name(host) + bytes([0, 1, 0x40]), flush)

    def _service_records(self, stype: str, ttl: int, flush: bool = True) -> tuple[list[bytes], list[bytes]]:
        inst, port, text = self.services()[stype]
        answers = [record(stype, PTR, ttl, encode_name(inst), flush=False)]
        extra = [record(inst, TXT, ttl, text, flush)]
        if port:
            srv = struct.pack("!HHH", 0, 0, port) + encode_name(self.host)
            extra.insert(0, record(inst, SRV, ttl, srv, flush))
            extra.append(self._a(self.host, min(ttl, TTL_HOST), flush))
        return answers, extra

    def answers(
        self, questions: list[tuple[str, int, int]], ttl_cap: int | None = None
    ) -> tuple[list[bytes], list[bytes]]:
        """(answers, additional records) for a query's questions. With `ttl_cap` (a one-shot
        resolver) the TTLs are capped and no record carries the cache-flush bit (RFC 6762 6.7)."""
        flush = ttl_cap is None

        def ttl(t: int) -> int:
            return min(t, ttl_cap) if ttl_cap is not None else t

        answers: list[bytes] = []
        extra: list[bytes] = []
        services = self.services()
        for name, qtype, _qclass in questions:
            host = name.removesuffix(".local")
            if name.endswith(".local") and host in self.names and qtype in (A, ANY):
                answers.append(self._a(name, ttl(TTL_HOST), flush))
                extra.append(self._no_ipv6(name, ttl(TTL_HOST), flush))
            elif name.endswith(".local") and host in self.names and qtype == AAAA:
                answers.append(self._no_ipv6(name, ttl(TTL_HOST), flush))
                extra.append(self._a(name, ttl(TTL_HOST), flush))
            elif name == SERVICES and qtype in (PTR, ANY):
                answers += [record(SERVICES, PTR, ttl(TTL_OTHER), encode_name(s), flush=False) for s in services]
            elif name in services and qtype in (PTR, ANY):
                a, x = self._service_records(name, ttl(TTL_OTHER), flush)
                answers += a
                extra += x
            else:
                for inst, port, text in services.values():
                    if name != inst.lower():
                        continue
                    if qtype in (SRV, ANY) and port:
                        srv = struct.pack("!HHH", 0, 0, port) + encode_name(self.host)
                        answers.append(record(inst, SRV, ttl(TTL_OTHER), srv, flush))
                        extra.append(self._a(self.host, ttl(TTL_HOST), flush))
                    if qtype in (TXT, ANY):
                        answers.append(record(inst, TXT, ttl(TTL_OTHER), text, flush))
        return answers, [x for x in dict.fromkeys(extra) if x not in answers]

    def reply(self, packet: bytes, src_port: int) -> bytes | None:
        """The response to a query packet, or None when it asks nothing of ours. A query from a port
        other than 5353 is a one-shot (legacy) resolver, e.g. Windows: it gets its id and question
        back and short TTLs, sent to it directly (RFC 6762 6.7)."""
        q = parse_query(packet)
        if not q:
            return None
        qid, questions = q
        legacy = src_port != PORT
        answers, extra = self.answers(questions, ttl_cap=10 if legacy else None)
        if not answers:
            return None
        head_q = b""
        if legacy:
            head_q = b"".join(encode_name(n) + struct.pack("!HH", t, IN) for n, t, _c in questions)
        qd = len(questions) if legacy else 0
        header = struct.pack("!HHHHHH", qid if legacy else 0, 0x8400, qd, len(answers), 0, len(extra))
        return header + head_q + b"".join(answers) + b"".join(extra)

    def announcement(self, goodbye: bool = False) -> bytes:
        """Everything we own, sent unasked at start (and with TTL 0 when going away)."""
        t_host, t_other = (0, 0) if goodbye else (TTL_HOST, TTL_OTHER)
        recs = [self._a(f"{n}.local", t_host) for n in self.names]
        for stype in self.services():
            a, x = self._service_records(stype, t_other)
            recs += a + [r for r in x if r not in recs]
        return struct.pack("!HHHHHH", 0, 0x8400, 0, len(recs), 0, 0) + b"".join(recs)

    def taken_by_other(self, packet: bytes) -> bool:
        """Another device answering for our name with another address (RFC 6762 9)."""
        mine = socket.inet_aton(self.ip)
        return any(
            rtype == A and name.removesuffix(".local") in self.names and rdata != mine
            for name, rtype, rdata in answer_names(packet)
        )


# --- the network side ---------------------------------------------------------------------------
def default_ip() -> str:
    """The address of the interface with the default route (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]


def smb_open(ip: str) -> bool:
    try:
        with socket.create_connection((ip, 445), timeout=1.0):
            return True
    except OSError:
        return False


def open_socket(ip: str) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:  # the host's responder may not allow it; SO_REUSEADDR is enough for multicast
            print("[mdns] sharing port 5353 without SO_REUSEPORT", flush=True)
    s.bind(("", PORT))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GROUP) + socket.inet_aton(ip))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    return s


def probe(sock: socket.socket, r: Responder) -> bool:
    """Asks three times whether anyone else answers for our name; True when it is free."""
    query = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0) + encode_name(r.host) + struct.pack("!HH", ANY, IN | 0x8000)
    sock.settimeout(0.25)
    for _ in range(3):
        sock.sendto(query, (GROUP, PORT))
        deadline = time.time() + 0.25
        while time.time() < deadline:
            try:
                data, _addr = sock.recvfrom(MAX_PACKET)
            except TimeoutError:
                break
            if r.taken_by_other(data):
                return False
    sock.settimeout(None)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Answers <name>.local on the home network.")
    ap.add_argument("--names", default="zettnas", help="the name, then older names that still answer")
    ap.add_argument("--label", default="ZettNAS", help="how Finder lists the NAS")
    ap.add_argument("--http-port", type=int, default=80)
    ap.add_argument("--ip", default="")
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    ip = args.ip or default_ip()
    port = args.http_port
    r = Responder(names, ip, port, args.label, smb=smb_open(ip))
    sock = open_socket(ip)
    if not probe(sock, r):
        base = r.names[0]
        print(f"[mdns] {base}.local is taken by another device; answering as {base}-2.local", flush=True)
        r.names[0] = f"{base}-2"
        r.host = f"{base}-2.local"
    sock.settimeout(None)
    for _ in range(2):
        sock.sendto(r.announcement(), (GROUP, PORT))
        time.sleep(1)
    print(f"[mdns] {', '.join(n + '.local' for n in r.names)} -> {ip}, web on port {port}, smb={r.smb}", flush=True)

    def bye(*_a: object) -> None:
        try:
            sock.sendto(r.announcement(goodbye=True), (GROUP, PORT))
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    while True:
        try:
            data, (addr, src_port) = sock.recvfrom(MAX_PACKET)
        except OSError:
            continue
        out = r.reply(data, src_port)
        if out:
            sock.sendto(out, (addr, src_port) if src_port != PORT else (GROUP, PORT))


if __name__ == "__main__":
    sys.exit(main())
