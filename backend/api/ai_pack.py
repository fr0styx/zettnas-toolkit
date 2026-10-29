"""The AI pack (AI-40): status, install and "use it". See backend/services/ai_pack.py."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services import ai_pack

router = APIRouter(tags=["AI pack"])


class PackInstallRequest(BaseModel):
    preset: str | None = Field(default=None, pattern="^(small|standard|large)$")
    storage_root: str = "/mnt/user/appdata"


@router.get("/ai/pack", dependencies=[Depends(require_scope("system:config"))])
async def pack_status():
    """The box, the recommended preset, and the pack's state (absent, warming, ready, stopped)."""
    from backend.services.rag_engine import get_rag_engine

    return await asyncio.to_thread(lambda: ai_pack.status(get_rag_engine().get_config()))


@router.post("/ai/pack/install", dependencies=[Depends(require_scope("containers:manage"))])
def pack_install(req: PackInstallRequest | None = None):
    req = req or PackInstallRequest()

    def events():
        for e in ai_pack.stream_install(req.preset, req.storage_root):
            yield json.dumps(e) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.post("/ai/pack/use", dependencies=[Depends(require_scope("system:config"))])
async def pack_use():
    """Chat through the pack; the answer says how to move the embeddings."""
    try:
        from backend.services.rag_engine import get_rag_engine

        cfg = await asyncio.to_thread(ai_pack.use_pack, get_rag_engine())
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {"status": "ok", "llm_endpoint": cfg.get("llm_endpoint"), "reindex": ai_pack.reindex_request()}
