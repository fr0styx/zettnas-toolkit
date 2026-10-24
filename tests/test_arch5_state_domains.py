"""ARCH-5: typed state per domain, each with its own lock; the flat names still work."""

import threading

from backend.state import CopyState, ZettState


def test_flat_names_read_and_write_the_domain():
    s = ZettState()
    s.copy_active = True
    s.copy_status = "copying"
    assert s.copy.active is True and s.copy.status == "copying"
    s.lcd.current_page = 2
    assert s.current_lcd_page == 2
    s.ai_model = "qwen3:4b"
    assert s.ai.model == "qwen3:4b"


def test_each_domain_has_its_own_lock():
    s = ZettState()
    locks = {id(s.lock), id(s.copy.lock), id(s.fans.lock), id(s.lcd.lock), id(s.ai.lock), id(s.smart.lock)}
    assert len(locks) == 6
    assert isinstance(CopyState().lock, type(threading.RLock()))


def test_lcd_paging_uses_the_lcd_lock():
    s = ZettState()
    assert s.cycle_lcd_page(count=3) == 1
    assert s.set_lcd_page(7, count=3) == 2 and s.current_lcd_page == 2


def test_fan_tracker_has_all_channels():
    s = ZettState()
    assert set(s.fan_state_tracker) == {"pwm1", "pwm2", "pwm3"}
    assert s.fans.tracker is s.fan_state_tracker
