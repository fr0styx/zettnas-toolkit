from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backend.state import Z_STATE

router = APIRouter(tags=["Metrics"])

def _safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus exposition format for ZettNAS telemetry."""
    if not Z_STATE.cached_stats:
        return "# ZettNAS metrics not ready yet\n"
        
    stats = Z_STATE.cached_stats
    lines = []
    
    def add_gauge(name, help_text, val, labels=None):
        if val is None: return
        label_str = ""
        if labels:
            parts = [f'{k}="{v}"' for k, v in labels.items()]
            label_str = "{" + ",".join(parts) + "}"
            
        if name not in lines_by_metric:
            lines_by_metric[name] = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
        lines_by_metric[name].append(f"{name}{label_str} {_safe_float(val)}")

    lines_by_metric = {}
    
    # CPU
    cpu = stats.get("cpu", {})
    add_gauge("zettnas_cpu_temp_celsius", "CPU Temperature", cpu.get("temp"))
    add_gauge("zettnas_cpu_usage_percent", "CPU Usage", cpu.get("usage"))
    add_gauge("zettnas_cpu_power_watts", "CPU Power Consumption", cpu.get("power_w"))
    
    # RAM
    mem = stats.get("mem", {})
    add_gauge("zettnas_memory_total_bytes", "Total RAM", mem.get("total"))
    add_gauge("zettnas_memory_used_bytes", "Used RAM", mem.get("used"))
    add_gauge("zettnas_memory_free_bytes", "Free RAM", mem.get("free"))
    add_gauge("zettnas_memory_usage_percent", "RAM Usage", mem.get("percent"))
    
    # Network
    net = stats.get("net", {})
    add_gauge("zettnas_network_rx_bytes", "Network Bytes Received", net.get("rx_bytes"))
    add_gauge("zettnas_network_tx_bytes", "Network Bytes Transmitted", net.get("tx_bytes"))
    
    # Disks
    for d in stats.get("disks", []):
        labels = {"device": d.get("name"), "role": d.get("role", "data")}
        add_gauge("zettnas_disk_temp_celsius", "Disk Temperature", d.get("temp"), labels)
        add_gauge("zettnas_disk_io_ticks", "Disk IO Ticks", d.get("io_ticks"), labels)
        
    # Fans
    fans = stats.get("fans", [])
    for i, f in enumerate(fans):
        labels = {"fan_id": str(i)}
        add_gauge("zettnas_fan_rpm", "Fan RPM", f, labels)
        
    # UPS
    ups = stats.get("ups", {})
    if ups.get("available"):
        add_gauge("zettnas_ups_charge_percent", "UPS Battery Charge", ups.get("battery_charge_pct"))
        add_gauge("zettnas_ups_time_left_minutes", "UPS Time Left", ups.get("time_left_min"))
        add_gauge("zettnas_ups_load_percent", "UPS Load", ups.get("load_pct"))
        add_gauge("zettnas_ups_line_volts", "UPS Line Voltage", ups.get("line_volts"))
        add_gauge("zettnas_ups_battery_volts", "UPS Battery Voltage", ups.get("battery_volts"))
        
    # Unraid
    unraid = stats.get("unraid", {})
    if unraid.get("available"):
        add_gauge("zettnas_unraid_disk_count", "Unraid Disk Count", unraid.get("disk_count"))
        add_gauge("zettnas_unraid_parity_status", "Unraid Parity Checks (0=Idle, 1=Checking)", 1 if unraid.get("parity_check_running") else 0)
        
    out = []
    for metric_name, metric_lines in lines_by_metric.items():
        out.extend(metric_lines)
        
    return "\n".join(out) + "\n"
