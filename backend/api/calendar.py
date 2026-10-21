"""
ZettNAS Toolkit - Calendar, Reminders & External Provider Sync API
Provides storage for user notes/reminders, tasks, and Google Calendar / iCal feed synchronization.
Adheres strictly to AGENTS.md §1.2 Spindown-Safe and §1.4 Cryptographic Security & SSRF Invariants.
"""

import asyncio
import logging
import os
import re
import time
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.fsutil import atomic_write_json, read_json
from backend.services.ssrf_guard import validate_public_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar & Notes"])

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
CALENDAR_DATA_FILE = os.path.join(DATA_DIR, "calendar_data.json")

# In-memory lock for thread-safe access
_calendar_lock = asyncio.Lock()


# -------------------------------------------------------------------------
# Pydantic Models
# -------------------------------------------------------------------------
class CalendarNoteModel(BaseModel):
    id: Optional[str] = None
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date in YYYY-MM-DD format")
    time: Optional[str] = Field(default="", description="Optional time in HH:MM format")
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(default="", max_length=2048)
    type: str = Field(default="note", description="note | reminder | task | event")
    category: Optional[str] = Field(default="Personal", max_length=64)
    completed: bool = False
    created_at: Optional[float] = None
    updated_at: Optional[float] = None


class CalendarNotePatchModel(BaseModel):
    title: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2048)
    time: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    completed: Optional[bool] = None


class CalendarFeedModel(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=128)
    url: str = Field(..., min_length=5, max_length=1024, description="iCal / WebCal feed URL (e.g. Google Calendar)")
    color: str = Field(default="#00f0ff", max_length=32)
    enabled: bool = True
    provider: Optional[str] = Field(default="google", description="google | apple | outlook | nextcloud | generic")
    last_synced: Optional[float] = None
    event_count: int = 0
    error: Optional[str] = None


# -------------------------------------------------------------------------
# Helper Functions: Storage & Parsing
# -------------------------------------------------------------------------
def _load_calendar_store() -> Dict[str, Any]:
    default_store = {
        "notes": [],
        "feeds": [],
        "feed_events": [],  # Synced events from external feeds
    }
    return read_json(CALENDAR_DATA_FILE, default=default_store)


def _save_calendar_store(store: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    atomic_write_json(CALENDAR_DATA_FILE, store)


def _parse_ical_datetime(dt_str: str) -> Dict[str, str]:
    """
    Parses iCal DTSTART/DTEND string (e.g. 20261019, 20261019T143000Z, TZID=...:20261019T103000).
    Returns {'date': 'YYYY-MM-DD', 'time': 'HH:MM' or ''}.
    """
    val = dt_str.split(":")[-1].strip()
    # Match YYYYMMDD
    m_date = re.match(r"^(\d{4})(\d{2})(\d{2})", val)
    if not m_date:
        return {"date": "", "time": ""}
    year, month, day = m_date.groups()
    date_str = f"{year}-{month}-{day}"

    time_str = ""
    m_time = re.search(r"T(\d{2})(\d{2})", val)
    if m_time:
        hr, mn = m_time.groups()
        time_str = f"{hr}:{mn}"

    return {"date": date_str, "time": time_str}


def _parse_ics_content(ics_text: str, feed_id: str, feed_name: str, feed_color: str) -> List[Dict[str, Any]]:
    """
    Parses standard RFC 5545 iCalendar content into event dictionaries.
    """
    events = []
    # Unfold lines (RFC 5545 §3.1)
    unfolded = re.sub(r"\r?\n[ \t]", "", ics_text)
    lines = unfolded.splitlines()

    in_event = False
    curr_event: Dict[str, Any] = {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line == "BEGIN:VEVENT":
            in_event = True
            curr_event = {
                "id": str(uuid.uuid4()),
                "feed_id": feed_id,
                "feed_name": feed_name,
                "feed_color": feed_color,
                "type": "event",
                "source": "synced",
                "completed": False,
            }
            continue

        if line == "END:VEVENT":
            if in_event and curr_event.get("date") and curr_event.get("title"):
                events.append(curr_event)
            in_event = False
            curr_event = {}
            continue

        if not in_event:
            continue

        if ":" not in line:
            continue

        prop, _, val = line.partition(":")
        prop_upper = prop.upper()

        if prop_upper.startswith("SUMMARY"):
            curr_event["title"] = val.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
        elif prop_upper.startswith("DESCRIPTION"):
            curr_event["description"] = val.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n")
        elif prop_upper.startswith("DTSTART"):
            dt = _parse_ical_datetime(line)
            if dt["date"]:
                curr_event["date"] = dt["date"]
                curr_event["time"] = dt["time"]
        elif prop_upper.startswith("DTEND"):
            dt = _parse_ical_datetime(line)
            if dt["time"]:
                curr_event["end_time"] = dt["time"]
        elif prop_upper.startswith("LOCATION"):
            curr_event["location"] = val.replace("\\,", ",").replace("\\;", ";")
        elif prop_upper.startswith("UID"):
            curr_event["uid"] = val

    return events


async def _sync_single_feed(feed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fetches and parses a single calendar feed securely.
    """
    raw_url = feed.get("url", "").strip()
    if not raw_url:
        feed["error"] = "Empty URL"
        return []

    # Handle webcal:// prefix
    if raw_url.startswith("webcal://"):
        raw_url = "https://" + raw_url[len("webcal://") :]

    is_safe, err_msg = validate_public_url(raw_url)
    if not is_safe:
        feed["error"] = f"Security blocked: {err_msg}"
        return []

    def _do_fetch() -> str:
        from backend.services.safe_fetch import safe_fetch

        status, hdrs, body = safe_fetch(
            raw_url,
            context="public",
            headers={
                "User-Agent": "ZettNAS-Calendar/1.0 (Home Cloud OS; +https://zettnas.local)",
                "Accept": "text/calendar, text/plain, */*",
            },
            timeout=12,
            max_bytes=10 * 1024 * 1024,
        )
        if status != 200:
            raise ValueError(f"HTTP {status}")
        ctype = hdrs.get("content-type", "")
        charset = ctype.split("charset=", 1)[1].split(";")[0].strip() if "charset=" in ctype else "utf-8"
        return body.decode(charset or "utf-8", errors="replace")

    try:
        ics_text = await asyncio.to_thread(_do_fetch)
        events = _parse_ics_content(
            ics_text,
            feed_id=feed["id"],
            feed_name=feed.get("name", "Calendar"),
            feed_color=feed.get("color", "#00f0ff"),
        )
        feed["last_synced"] = time.time()
        feed["event_count"] = len(events)
        feed["error"] = None
        return events
    except Exception as exc:
        logger.warning(f"[Calendar] Sync failed for feed {feed.get('name')}: {exc}")
        feed["error"] = f"Failed fetching calendar: {str(exc)[:120]}"
        return []


# -------------------------------------------------------------------------
# REST API Endpoints: Events, Notes & Reminders
# -------------------------------------------------------------------------
@router.get("/events")
async def get_calendar_events(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """
    Returns user notes/reminders combined with synced external calendar events.
    Optionally filters by date range.
    """
    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)

    notes = store.get("notes", [])
    feed_events = store.get("feed_events", [])

    all_items = list(notes) + list(feed_events)

    if start_date:
        all_items = [it for it in all_items if it.get("date", "") >= start_date]
    if end_date:
        all_items = [it for it in all_items if it.get("date", "") <= end_date]

    # Sort primarily by date, then time
    all_items.sort(key=lambda x: (x.get("date", ""), x.get("time", "") or "99:99"))

    return {
        "status": "ok",
        "events": all_items,
        "count": len(all_items),
        "notes_count": len(notes),
        "synced_count": len(feed_events),
    }


@router.post("/notes", dependencies=[Depends(require_scope("system:config", "shares:user_write"))])
async def create_calendar_note(note: CalendarNoteModel):
    """
    Creates a new note, reminder, or task for a given date.
    """
    note_id = note.id or str(uuid.uuid4())
    now = time.time()
    item = {
        "id": note_id,
        "date": note.date,
        "time": note.time or "",
        "title": note.title.strip(),
        "description": (note.description or "").strip(),
        "type": note.type,
        "category": note.category or "Personal",
        "completed": note.completed,
        "source": "local",
        "created_at": now,
        "updated_at": now,
    }

    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
        notes = store.get("notes", [])
        notes.append(item)
        store["notes"] = notes
        await asyncio.to_thread(_save_calendar_store, store)

    return {"status": "ok", "message": "Note created", "note": item}


@router.patch("/notes/{note_id}", dependencies=[Depends(require_scope("system:config", "shares:user_write"))])
async def update_calendar_note(note_id: str, patch: CalendarNotePatchModel):
    """
    Updates or toggles completed status of a note/reminder.
    """
    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
        notes = store.get("notes", [])
        found = None
        for n in notes:
            if n.get("id") == note_id:
                found = n
                break

        if not found:
            raise HTTPException(status_code=404, detail="Note not found")

        if patch.title is not None:
            found["title"] = patch.title.strip()
        if patch.description is not None:
            found["description"] = patch.description.strip()
        if patch.time is not None:
            found["time"] = patch.time
        if patch.type is not None:
            found["type"] = patch.type
        if patch.category is not None:
            found["category"] = patch.category
        if patch.completed is not None:
            found["completed"] = patch.completed
        found["updated_at"] = time.time()

        store["notes"] = notes
        await asyncio.to_thread(_save_calendar_store, store)

    return {"status": "ok", "message": "Note updated", "note": found}


@router.delete("/notes/{note_id}", dependencies=[Depends(require_scope("system:config", "shares:user_write"))])
async def delete_calendar_note(note_id: str):
    """
    Deletes a user note or reminder.
    """
    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
        notes = store.get("notes", [])
        new_notes = [n for n in notes if n.get("id") != note_id]
        if len(new_notes) == len(notes):
            raise HTTPException(status_code=404, detail="Note not found")

        store["notes"] = new_notes
        await asyncio.to_thread(_save_calendar_store, store)

    return {"status": "ok", "message": "Note deleted"}


# -------------------------------------------------------------------------
# REST API Endpoints: Calendar Provider Sync (Google, Apple, Outlook, CalDAV)
# -------------------------------------------------------------------------
@router.get("/feeds")
async def list_calendar_feeds():
    """
    Lists configured external calendar feeds and their sync status.
    """
    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
    return {"status": "ok", "feeds": store.get("feeds", [])}


@router.post("/feeds", dependencies=[Depends(require_scope("system:config", "shares:user_write"))])
async def add_or_update_calendar_feed(feed: CalendarFeedModel):
    """
    Adds a new calendar provider feed (e.g. Google Calendar iCal URL) or updates an existing one.
    """
    # Quick sanity check for valid URL format
    test_url = feed.url.strip()
    if test_url.startswith("webcal://"):
        test_url = "https://" + test_url[len("webcal://") :]

    is_safe, err_msg = validate_public_url(test_url)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"Invalid or disallowed calendar URL: {err_msg}")

    feed_id = feed.id or str(uuid.uuid4())
    feed_item = {
        "id": feed_id,
        "name": feed.name.strip(),
        "url": feed.url.strip(),
        "color": feed.color or "#00f0ff",
        "enabled": feed.enabled,
        "provider": feed.provider or "google",
        "last_synced": feed.last_synced,
        "event_count": feed.event_count,
        "error": None,
    }

    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
        feeds = store.get("feeds", [])
        idx = next((i for i, f in enumerate(feeds) if f.get("id") == feed_id), None)
        if idx is not None:
            feeds[idx] = feed_item
        else:
            feeds.append(feed_item)
        store["feeds"] = feeds
        await asyncio.to_thread(_save_calendar_store, store)

    # Automatically trigger sync for the new/updated feed
    if feed.enabled:
        events = await _sync_single_feed(feed_item)
        async with _calendar_lock:
            store = await asyncio.to_thread(_load_calendar_store)
            # Remove previous events for this feed
            other_events = [ev for ev in store.get("feed_events", []) if ev.get("feed_id") != feed_id]
            store["feed_events"] = other_events + events
            # Update feed in list
            for f in store.get("feeds", []):
                if f.get("id") == feed_id:
                    f["last_synced"] = feed_item.get("last_synced")
                    f["event_count"] = len(events)
                    f["error"] = feed_item.get("error")
                    break
            await asyncio.to_thread(_save_calendar_store, store)

    return {"status": "ok", "message": "Calendar feed saved", "feed": feed_item}


@router.delete("/feeds/{feed_id}", dependencies=[Depends(require_scope("system:config", "shares:user_write"))])
async def delete_calendar_feed(feed_id: str):
    """
    Removes a calendar provider feed and cleans up all its cached events.
    """
    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
        feeds = store.get("feeds", [])
        store["feeds"] = [f for f in feeds if f.get("id") != feed_id]
        store["feed_events"] = [ev for ev in store.get("feed_events", []) if ev.get("feed_id") != feed_id]
        await asyncio.to_thread(_save_calendar_store, store)

    return {"status": "ok", "message": "Calendar feed removed"}


@router.post("/sync", dependencies=[Depends(require_scope("system:config", "shares:user_write"))])
async def sync_all_calendar_feeds():
    """
    Syncs all enabled calendar provider feeds and updates the cached events.
    """
    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
        feeds = list(store.get("feeds", []))

    all_feed_events = []
    synced_count = 0

    for feed in feeds:
        if not feed.get("enabled", True):
            continue
        events = await _sync_single_feed(feed)
        all_feed_events.extend(events)
        synced_count += 1

    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)
        store["feeds"] = feeds
        store["feed_events"] = all_feed_events
        await asyncio.to_thread(_save_calendar_store, store)

    return {
        "status": "ok",
        "message": f"Successfully synced {synced_count} calendar feed(s)",
        "total_events": len(all_feed_events),
        "feeds": feeds,
    }


# -------------------------------------------------------------------------
# Export & Import
# -------------------------------------------------------------------------
@router.get("/export")
async def export_calendar_ics():
    """
    Exports all user notes and reminders as an RFC 5545 .ics calendar file.
    """
    async with _calendar_lock:
        store = await asyncio.to_thread(_load_calendar_store)

    notes = store.get("notes", [])

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ZettNAS Toolkit//Desktop Calendar 1.0//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:ZettNAS Reminders & Notes",
    ]

    for n in notes:
        d_raw = (n.get("date") or "").replace("-", "")
        t_raw = (n.get("time") or "").replace(":", "")
        dtstart = f"{d_raw}T{t_raw}00" if t_raw else d_raw
        uid = n.get("id") or str(uuid.uuid4())
        summary = (n.get("title") or "Note").replace("\n", " ")
        desc = (n.get("description") or "").replace("\n", "\\n")

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}@zettnas.local",
                f"DTSTART:{dtstart}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{desc}",
                f"CATEGORIES:{n.get('category', 'Personal')}",
                f"STATUS:{'COMPLETED' if n.get('completed') else 'CONFIRMED'}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    content = "\r\n".join(lines) + "\r\n"

    return Response(
        content=content,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=zettnas_calendar.ics"},
    )
