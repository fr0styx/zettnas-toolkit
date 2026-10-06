import time
from backend.state import add_event

_active_alerts = {}

def evaluate_system_alerts(unraid_data, ups_data):
    """Evaluates built-in rules for system alerts and debounces them."""
    now = time.time()
    
    # 1. Unraid Array
    if unraid_data.get("available"):
        state = unraid_data.get("state", "").upper()
        if state == "ERROR":
            _trigger_alert("unraid_error", "Unraid Array Error", "The Unraid array has encountered an error state.", "error", now)
        else:
            _resolve_alert("unraid_error")
            
    # 2. UPS Power
    if ups_data.get("available"):
        status = ups_data.get("status", "").upper()
        if "OB" in status or "ONBATT" in status or "ON BATT" in status:
            _trigger_alert("ups_onbatt", "UPS On Battery", f"The system is running on battery power. Estimated runtime: {ups_data.get('time_left_min', '?')} min", "warning", now)
        elif "OL" in status or "ONLINE" in status:
            _resolve_alert("ups_onbatt", "UPS power restored.")
            
def _trigger_alert(alert_id, title, message, level, now):
    from backend.services.notifications import send_notification
    last_triggered = _active_alerts.get(alert_id, 0)
    # Re-alert every 15 minutes while active
    if now - last_triggered > 900:
        _active_alerts[alert_id] = now
        add_event(level, title, message)
        send_notification({"type": "system", "title": title, "message": message, "level": level})
        
def _resolve_alert(alert_id, resolve_msg=None):
    from backend.services.notifications import send_notification
    if alert_id in _active_alerts:
        del _active_alerts[alert_id]
        if resolve_msg:
            add_event("info", "Alert Resolved", resolve_msg)
            send_notification({"type": "system", "title": "Alert Resolved", "message": resolve_msg, "level": "info"})
