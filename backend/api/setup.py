"""First-run help: the Getting started checklist (UX-1)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import AuthenticatedPrincipal, get_current_principal
from backend.services.getting_started import checklist

router = APIRouter(tags=["Setup"])


class ChecklistItem(BaseModel):
    id: str
    open: str
    done: bool


class Checklist(BaseModel):
    items: list[ChecklistItem]
    done: int
    total: int
    complete: bool


@router.get("/setup/checklist", response_model=Checklist)
def get_checklist(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    is_admin = bool(principal and (principal.has_scope("*") or principal.has_scope("system:manage")))
    return checklist(principal.username if principal else "", is_admin)
