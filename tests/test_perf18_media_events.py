"""PERF-18: the card slots are read after the kernel reports a change, not on every pass."""

from backend.hardware import media_events, media_slots

UEVENT = b"change@/devices/pci0000:00/usb2/2-1/2-1:1.0/host6/target6:0:0/6:0:0:1/block/sdc\0ACTION=change\0DEVPATH=/devices/x/block/sdc\0SUBSYSTEM=block\0DISK_MEDIA_CHANGE=1\0DEVNAME=sdc\0DEVTYPE=disk\0"


def test_a_uevent_is_read_as_fields():
    ev = media_events.parse(UEVENT)
    assert ev["ACTION"] == "change" and ev["DEVNAME"] == "sdc" and ev["DISK_MEDIA_CHANGE"] == "1"
    assert media_events.relevant(ev)


def test_other_events_are_ignored():
    assert not media_events.relevant({"SUBSYSTEM": "net", "ACTION": "change", "DEVNAME": "eth0"})
    assert not media_events.relevant({"SUBSYSTEM": "block", "ACTION": "change", "DEVNAME": "nvme0n1"})
    assert not media_events.relevant({"SUBSYSTEM": "block", "ACTION": "bind", "DEVNAME": "sdc"})


def test_without_the_listener_every_pass_reads(monkeypatch):
    monkeypatch.setitem(media_events._state, "listening", False)
    assert media_events.should_probe(100.0, now=101.0)


def test_with_the_listener_only_a_change_or_the_fallback_reads(monkeypatch):
    monkeypatch.setitem(media_events._state, "listening", True)
    monkeypatch.setitem(media_events._state, "changed", 50.0)
    assert media_events.should_probe(0.0, now=60.0)  # never read yet
    assert not media_events.should_probe(55.0, now=60.0)
    assert media_events.should_probe(55.0, now=55.0 + media_events.FALLBACK_S)
    monkeypatch.setitem(media_events._state, "changed", 58.0)
    assert media_events.should_probe(55.0, now=60.0)


def test_a_slot_is_probed_once_until_the_kernel_reports_a_change(tmp_path, monkeypatch):
    monkeypatch.setitem(media_events._state, "listening", True)
    monkeypatch.setitem(media_events._state, "changed", 0.0)
    monkeypatch.setattr(media_slots, "_SIZES", {})
    probed = []
    monkeypatch.setattr(media_slots, "probe_media_slot_capacity", lambda dev, **k: probed.append(dev) or 64_000_000_000)
    assert media_slots._slot_size(str(tmp_path), "sdc") == 64_000_000_000
    assert media_slots._slot_size(str(tmp_path), "sdc") == 64_000_000_000
    assert probed == ["sdc"]
    media_events.mark_changed()
    media_slots._slot_size(str(tmp_path), "sdc")
    assert probed == ["sdc", "sdc"]


def test_an_empty_slot_is_not_opened_while_the_kernel_events_are_heard(tmp_path, monkeypatch):
    block = tmp_path / "sdb"
    block.mkdir()
    (block / "events_poll_msecs").write_text("2000\n")
    monkeypatch.setitem(media_events._state, "listening", True)
    monkeypatch.setattr(media_slots, "_LAST_MEDIA_PROBE", 0.0)
    opened = []
    monkeypatch.setattr(media_slots.os, "open", lambda p, flags: opened.append(p) or 7)
    media_slots._ensure_slot_polling(str(block), "sdb", is_empty=True)
    assert opened == []


def test_no_uevent_socket_means_no_listener(monkeypatch):
    monkeypatch.setitem(media_events._state, "listening", False)

    def refuse(*a):
        raise OSError("not permitted")

    monkeypatch.setattr(media_events.socket, "socket", refuse)
    assert media_events.start() is False and not media_events.listening()


class _Sock:
    def __init__(self, frames):
        self.frames = list(frames)
        self.bound = None

    def bind(self, addr):
        self.bound = addr

    def recv(self, n):
        if not self.frames:
            raise OSError("closed")
        return self.frames.pop(0)


def test_the_listener_notes_card_events_and_stops_with_its_socket(monkeypatch):
    monkeypatch.setitem(media_events._state, "listening", True)
    monkeypatch.setitem(media_events._state, "changed", 0.0)
    media_events._listen(_Sock([b"add@/devices/x\0ACTION=add\0SUBSYSTEM=net\0DEVNAME=eth1\0"]))
    assert media_events._state["changed"] == 0.0 and not media_events.listening()
    monkeypatch.setitem(media_events._state, "listening", True)
    media_events._listen(_Sock([UEVENT]))
    assert media_events._state["changed"] > 0.0


def test_the_listener_starts_once(monkeypatch):
    monkeypatch.setitem(media_events._state, "listening", False)
    sock = _Sock([])
    started = []
    monkeypatch.setattr(media_events.socket, "socket", lambda *a: sock)
    monkeypatch.setattr(
        media_events.threading,
        "Thread",
        lambda **kw: type("T", (), {"start": lambda self: started.append(kw["name"])})(),
    )
    assert media_events.start() is True and media_events.start() is True
    assert sock.bound == (0, 1) and started == ["media-uevents"] and media_events.listening()


def test_the_slots_start_the_listener_outside_tests(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(media_slots, "test_mode", lambda: False)
    monkeypatch.setattr(media_events, "start", lambda: calls.append(1) or False)
    monkeypatch.setitem(media_events._state, "listening", False)
    monkeypatch.setattr(media_slots, "probe_media_slot_capacity", lambda dev, **k: 0)
    assert media_slots._slot_size(str(tmp_path), "sdc") == 0 and calls == [1]
