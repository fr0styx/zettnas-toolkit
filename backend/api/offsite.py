"""Offsite backup with restic: repositories, versions, browse, restore and checks (Batch 6)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.services import offsite_backup as ob

router = APIRouter(tags=["Offsite backup"])
READ = Depends(require_scope("backup:read", "backup:manage", "system:config"))
MANAGE = Depends(require_scope("backup:manage", "system:config"))


class RepoIn(BaseModel):
    id: str = Field(min_length=1, max_length=41)
    name: str = Field(default="", max_length=80)
    location: str = Field(min_length=2, max_length=1024)
    paths: list[str] = Field(min_length=1, max_length=50)
    keep: dict[str, int] = Field(default_factory=dict)
    hour: int | None = Field(default=2, ge=0, le=23)


class RestoreIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    target: str = Field(min_length=2, max_length=4096)


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'")) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ob.ResticError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None


@router.get("/offsite", dependencies=[READ])
def overview():
    return {"available": ob.restic_available(), "repos": ob.list_repos()}


@router.put("/offsite/repos", dependencies=[MANAGE])
def put_repo(req: RepoIn):
    return _errors(ob.save_repo, req.id, req.name, req.location, req.paths, req.keep, req.hour)


@router.delete("/offsite/repos/{repo_id}", dependencies=[MANAGE])
def delete_repo(repo_id: str):
    if not ob.delete_repo(repo_id):
        raise HTTPException(status_code=404, detail="No such backup.")
    return {"status": "forgotten", "id": repo_id}


@router.post("/offsite/repos/{repo_id}/init", dependencies=[MANAGE])
def init_repo(repo_id: str):
    return _errors(ob.init, repo_id)


@router.get("/offsite/repos/{repo_id}/key", dependencies=[MANAGE])
def get_key(repo_id: str):
    """The repository key: without it nobody, including you, can read the backup."""
    return {"key": _errors(ob.recovery_key, repo_id)}


@router.post("/offsite/repos/{repo_id}/backup", dependencies=[MANAGE])
def run_backup(repo_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return _errors(ob.backup, repo_id, owner=principal.username if principal else None)


@router.post("/offsite/repos/{repo_id}/check", dependencies=[MANAGE])
def run_check(repo_id: str, read_percent: int = 5):
    return _errors(ob.check, repo_id, read_percent)


@router.get("/offsite/repos/{repo_id}/snapshots", dependencies=[READ])
def list_versions(repo_id: str):
    return {"snapshots": _errors(ob.snapshots, repo_id)}


@router.get("/offsite/repos/{repo_id}/snapshots/{snapshot_id}/browse", dependencies=[READ])
def browse(repo_id: str, snapshot_id: str, path: str = "/"):
    return {"entries": _errors(ob.browse, repo_id, snapshot_id, path)}


@router.post("/offsite/repos/{repo_id}/snapshots/{snapshot_id}/restore", dependencies=[MANAGE])
def restore(repo_id: str, snapshot_id: str, req: RestoreIn):
    return _errors(ob.restore, repo_id, snapshot_id, req.path, req.target)
