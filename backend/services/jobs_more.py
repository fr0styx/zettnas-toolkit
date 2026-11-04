"""More background work in the Jobs centre (NJOB-2): Docker clean-up, AI model and VM installer
downloads, drive self-tests and storage checks.

Each is read from where that work already keeps its progress; nothing here starts, wakes or asks a
disk anything. Imported by the Jobs API, which adds these sources to the list.
"""

import time

from backend.services.jobs import SOURCES, Job

_PRUNE = {"running": "running", "done": "done", "done_with_errors": "done", "cancelled": "cancelled"}
_MODEL = {
    "starting": "running",
    "downloading": "running",
    "verifying": "running",
    "done": "done",
    "failed": "error",
    "cancelled": "cancelled",
}
_ISO = {"downloading": "running", "completed": "done", "cancelled": "cancelled"}


def _docker_cleanup() -> list[Job]:
    from backend.services import docker_cleanup

    j = docker_cleanup.get_prune_job()
    if not j:
        return []
    status = _PRUNE.get(str(j.get("state")), "error")
    detail = " · ".join(x for x in (str(j.get("message") or ""), f"{j.get('freed_human') or '0 B'} freed") if x)
    if j.get("errors"):
        detail += f" · {len(j['errors'])} could not be removed"
    return [
        Job(
            id=f"prune:{j['id']}",
            kind="docker_cleanup",
            title="Cleaning up Docker",
            title_id="jobs.t.docker_cleanup",
            status=status,
            percent=j.get("percent"),
            detail=detail,
            started_at=j.get("started_at"),
            finished_at=j.get("finished_at"),
            can_cancel=status == "running",
        )
    ]


def _cancel_prune(job_id: str) -> bool:
    from backend.services import docker_cleanup

    return docker_cleanup.cancel_prune_job(job_id)


def _model_downloads() -> list[Job]:
    from backend.services import model_installer

    out = []
    for j in model_installer.list_jobs():
        status = _MODEL.get(str(j.get("state")), "running")
        total, done = int(j.get("total_bytes") or 0), int(j.get("completed_bytes") or 0)
        size = f" · {done / 1e9:.1f} of {total / 1e9:.1f} GB" if total else ""
        out.append(
            Job(
                id=f"model:{j['id']}",
                kind="model_download",
                title=f"Downloading the AI model {j.get('model')}",
                title_id="jobs.t.model",
                title_params={"model": j.get("model") or ""},
                status=status,
                owner=j.get("requested_by") or None,
                percent=j.get("percent"),
                detail=f"{j.get('status') or ''}{size}",
                started_at=j.get("started_at"),
                finished_at=j.get("finished_at"),
                error=j.get("error") or None,
                can_cancel=status == "running",
            )
        )
    return out


def _cancel_model(job_id: str) -> bool:
    from backend.services import model_installer

    return model_installer.cancel_job(job_id)


def _iso_downloads() -> list[Job]:
    from backend.services import vm_store

    out = []
    for t in list(vm_store._DOWNLOAD_TASKS.values()):
        status = _ISO.get(str(t.get("status")), "error")
        speed = t.get("speed_mb_s")
        out.append(
            Job(
                id=f"iso:{t['task_id']}",
                kind="vm_download",
                title=f"Downloading {t.get('name')}",
                title_id="jobs.t.iso",
                title_params={"name": t.get("name") or ""},
                status=status,
                percent=t.get("progress_pct"),
                detail=f"{speed} MB/s" if status == "running" and speed else "",
                started_at=t.get("started_at"),
                finished_at=None if status == "running" else time.time(),  # kept as first seen
                error=t.get("error") or None,
                can_cancel=status == "running",
            )
        )
    return out


def _cancel_iso(task_id: str) -> bool:
    from backend.services import vm_store

    if (vm_store._DOWNLOAD_TASKS.get(task_id) or {}).get("status") != "downloading":
        return False
    vm_store._ABORT_DOWNLOAD_TASKS.add(task_id)
    return True


def _smart_tests() -> list[Job]:
    """Drive self-tests while the drive runs them; the SMART poller updates how far they are."""
    from backend.state import Z_STATE

    out = []
    for dev, t in Z_STATE.smart.snapshot("active_tests").items():
        disk = f"{t.get('model') or 'disk'} ({dev})"
        test = str(t.get("test_type") or "")
        mins = t.get("expected_minutes")
        out.append(
            Job(
                id=f"smart:{dev}",
                kind="smart_test",
                title=f"SMART {test} test on {disk}",
                title_id="jobs.t.smart_test",
                title_params={"test": test, "disk": disk},
                percent=t.get("last_pct"),
                detail=f"About {mins} minutes in all" if mins else "",
                started_at=t.get("start_time"),
            )
        )
    return out


def _unraid_checks() -> list[Job]:
    from backend.hardware.unraid import read_unraid_status

    st = read_unraid_status() or {}
    out = []
    pc = st.get("parity_check") or {}
    if pc.get("active") or pc.get("paused"):
        out.append(
            Job(
                id="storage:parity",
                kind="storage_check",
                title="Parity check",
                title_id="jobs.t.parity",
                status="paused" if pc.get("paused") else "running",
                percent=pc.get("progress_pct"),
                detail=f"{int(pc.get('errors') or 0)} errors found so far",
            )
        )
    mv = st.get("mover") or {}
    if mv.get("active"):
        total, left = int(mv.get("total_files") or 0), int(mv.get("remain_files") or 0)
        out.append(
            Job(
                id="storage:mover",
                kind="mover",
                title="Moving files between the cache and the array",
                title_id="jobs.t.mover",
                percent=100.0 * max(0, total - left) / total if total else None,
                detail=f"{left:,} files left" if total else "",
            )
        )
    return out


def _storage_checks() -> list[Job]:
    """A parity check or the mover on Unraid; a scrub, resilver or balance elsewhere (the platform
    keeps that answer for 10 s)."""
    from backend.hardware.pal.base import PlatformType
    from backend.hardware.pal_storage import get_storage_platform

    adapter = get_storage_platform()
    if adapter.get_platform_type() == PlatformType.UNRAID:
        return _unraid_checks()
    if not adapter.is_storage_busy():
        return []
    return [
        Job(
            id="storage:check",
            kind="storage_check",
            title="Checking a storage pool for errors",
            title_id="jobs.t.scrub",
        )
    ]


SOURCES.update(
    {
        "prune": (_docker_cleanup, _cancel_prune),
        "model": (_model_downloads, _cancel_model),
        "iso": (_iso_downloads, _cancel_iso),
        "smart": (_smart_tests, None),
        "storage": (_storage_checks, None),
    }
)
