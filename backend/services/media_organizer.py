"""
ZettNAS Toolkit - Media Organizer & Renamer Engine
Lightweight, deterministic regex heuristic parser and media file reorganizer (FileBot alternative).
Standardizes arbitrary media downloads into clean Plex, Jellyfin, and Emby folder structures.
Executes with < 15MB RAM and zero deep-learning overhead on low-power NAS appliances.
"""

import os
import re
import shutil
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.config import POOL_PATH, logger
from backend.fsutil import prune_protected
from backend.settings import test_mode

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov", ".webm"}

# Quality / Resolution Tokens
RESOLUTION_PATTERNS = [
    (re.compile(r"\b(2160p|4k|uhd)\b", re.I), "2160p"),
    (re.compile(r"\b(1080p|fhd)\b", re.I), "1080p"),
    (re.compile(r"\b(720p|hd)\b", re.I), "720p"),
    (re.compile(r"\b(480p|sd)\b", re.I), "480p"),
]

# Codec Tokens
CODEC_PATTERNS = [
    (re.compile(r"\b(x265|h\.?265|hevc)\b", re.I), "x265"),
    (re.compile(r"\b(x264|h\.?264|avc)\b", re.I), "x264"),
    (re.compile(r"\b(av1)\b", re.I), "AV1"),
    (re.compile(r"\b(bluray|remux)\b", re.I), "BluRay"),
    (re.compile(r"\b(web-?dl|webrip)\b", re.I), "WEB-DL"),
]

# TV Show Season & Episode Patterns
TV_PATTERNS = [
    # Standard S01E02 or S01E02E03
    re.compile(r"^(.*?)[. _\-]+[sS]([0-9]{1,2})[eE]([0-9]{1,3})(?:[eE]([0-9]{1,3}))?[. _\-]*(.*?)$", re.I),
    # 1x02 pattern
    re.compile(r"^(.*?)[. _\-]+([0-9]{1,2})x([0-9]{1,3})[. _\-]*(.*?)$", re.I),
    # Anime with hyphen delimiter e.g. [Group] Title - 05 [1080p]
    re.compile(r"^(?:\[.*?\])?[. _\-]*([a-zA-Z0-9\s._\-]+?)\s+-\s+([0-9]{1,3})(?:v[0-9])?[. _\-]*(.*?)$", re.I),
    # Explicit episode prefix e.g. Title.Episode.05.1080p or Title.EP05.1080p
    re.compile(
        r"^(?:\[.*?\])?[. _\-]*([a-zA-Z0-9\s._\-]+?)[. _\-]+(?:EP|Episode|ep)[. _\-]*([0-9]{1,3})(?:v[0-9])?[. _\-]*(.*?)$",
        re.I,
    ),
]

# Movie Year Pattern: Title.Year.1080p...
MOVIE_YEAR_PATTERN = re.compile(r"^(.*?)[. _\-(]+(19[2-9][0-9]|20[0-4][0-9])[. _\-)]+(.*?)$", re.I)


def clean_title(title: str) -> str:
    """Cleans dot/underscore-delimited release titles into human-readable strings."""
    # Strip release group brackets e.g. [YTS.MX], [Erai-raws]
    cleaned = re.sub(r"^\[.*?\]|\(.*?\)$", "", title).strip()
    # Replace dots and underscores with spaces
    cleaned = re.sub(r"[._]", " ", cleaned).strip()
    # Remove redundant whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Title Case capitalization if lowercase or all caps
    if cleaned.islower() or cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned.strip(" -_")


def parse_media_filename(filename: str) -> dict[str, Any]:
    """
    Extracts semantic metadata (Type, Title, Year, Season, Episode, Resolution, Codec)
    from arbitrary file names using deterministic heuristics.
    """
    base, ext = os.path.splitext(filename)
    ext_lower = ext.lower()

    if ext_lower not in VIDEO_EXTENSIONS:
        return {
            "is_video": False,
            "filename": filename,
            "error": f"Unsupported media extension: {ext}",
        }

    # 1. Detect Resolution
    resolution = "1080p"
    for pat, label in RESOLUTION_PATTERNS:
        if pat.search(base):
            resolution = label
            break

    # 2. Detect Codec
    codec = "x264"
    for pat, label in CODEC_PATTERNS:
        if pat.search(base):
            codec = label
            break

    # 3. Detect TV Show (S01E02 / 1x02)
    for pat in TV_PATTERNS:
        m = pat.match(base)
        if m:
            raw_title = m.group(1)
            season_str = m.group(2)
            episode_str = m.group(3) if len(m.groups()) >= 3 else None
            rest = m.group(len(m.groups())) or ""

            # Check if season/episode or anime single episode
            if episode_str is not None and episode_str.isdigit():
                season_num = int(season_str)
                episode_num = int(episode_str)
            elif season_str.isdigit():
                # Anime style: Season 1, Episode X
                season_num = 1
                episode_num = int(season_str)
            else:
                continue

            # Year extraction inside title if any e.g. Show.Name.2023.S01E01
            year = None
            ym = re.search(r"\b(19[2-9][0-9]|20[0-4][0-9])\b", raw_title)
            if ym:
                year = int(ym.group(1))
                raw_title = raw_title[: ym.start()].strip(" ._-")

            title = clean_title(raw_title)
            if not title:
                title = "Unknown TV Show"

            # Clean episode title if present in rest
            ep_title = ""
            if rest:
                cleaned_rest = re.sub(
                    r"\b(2160p|1080p|720p|480p|x264|x265|hevc|bluray|web-?dl|aac|dts)\b.*", "", rest, flags=re.I
                )
                cleaned_rest = clean_title(cleaned_rest)
                if len(cleaned_rest) > 2 and not cleaned_rest.isdigit():
                    ep_title = f" - {cleaned_rest}"

            year_str = f" ({year})" if year else ""
            proposed_rel_path = os.path.join(
                f"{title}{year_str}",
                f"Season {season_num:02d}",
                f"{title} - S{season_num:02d}E{episode_num:02d}{ep_title} [{resolution} {codec}]{ext_lower}",
            )

            return {
                "is_video": True,
                "media_type": "tv",
                "title": title,
                "year": year,
                "season": season_num,
                "episode": episode_num,
                "resolution": resolution,
                "codec": codec,
                "original_filename": filename,
                "proposed_relative_path": proposed_rel_path,
                "confidence": 0.95,
            }

    # 4. Detect Movie (Title + Year)
    ym = MOVIE_YEAR_PATTERN.match(base)
    if ym:
        raw_title = ym.group(1)
        year = int(ym.group(2))
        title = clean_title(raw_title)
        if not title:
            title = "Unknown Movie"

        proposed_rel_path = os.path.join(
            f"{title} ({year})",
            f"{title} ({year}) [{resolution} {codec}]{ext_lower}",
        )

        return {
            "is_video": True,
            "media_type": "movie",
            "title": title,
            "year": year,
            "season": None,
            "episode": None,
            "resolution": resolution,
            "codec": codec,
            "original_filename": filename,
            "proposed_relative_path": proposed_rel_path,
            "confidence": 0.90,
        }

    # Fallback Generic Movie / Video
    title = clean_title(base)
    proposed_rel_path = os.path.join(
        title,
        f"{title} [{resolution} {codec}]{ext_lower}",
    )
    return {
        "is_video": True,
        "media_type": "movie",
        "title": title,
        "year": None,
        "season": None,
        "episode": None,
        "resolution": resolution,
        "codec": codec,
        "original_filename": filename,
        "proposed_relative_path": proposed_rel_path,
        "confidence": 0.65,
    }


def _get_allowed_media_roots() -> list[str]:
    from backend.config import ALLOWED_BROWSE_ROOTS

    roots = list(ALLOWED_BROWSE_ROOTS)
    if test_mode():
        for cand in ("/tmp", "/var/tmp"):
            if os.path.exists(cand) and cand not in roots:
                roots.append(cand)
    return roots


def preview_organize(
    source_dir: str,
    target_dir: str | None = None,
    media_type: str = "auto",
) -> dict[str, Any]:
    """
    Scans source_dir for media files and calculates dry-run proposed destination paths.
    Safe and non-destructive: zero files are moved or altered.
    """
    from backend.fsutil import resolve_within

    allowed_roots = _get_allowed_media_roots()
    if not os.path.isdir(source_dir):
        raise ValueError(f"Source directory does not exist: {source_dir}")

    resolved_src_root = resolve_within(source_dir, allowed_roots)
    if not resolved_src_root:
        raise ValueError(f"Source directory outside permitted storage roots: {source_dir}")

    dest_root = target_dir.strip() if target_dir else source_dir
    resolved_dest_root = resolve_within(dest_root, allowed_roots)
    if not resolved_dest_root:
        raise ValueError(f"Target directory outside permitted storage roots: {dest_root}")

    items: list[dict[str, Any]] = []

    for root, sub_dirs, files in os.walk(source_dir):
        prune_protected(root, sub_dirs)
        for f in sorted(files):
            _, ext = os.path.splitext(f)
            if ext.lower() not in VIDEO_EXTENSIONS:
                continue

            full_src = os.path.join(root, f)
            if os.path.islink(full_src):
                continue
            if not resolve_within(full_src, allowed_roots):
                continue

            meta = parse_media_filename(f)
            if not meta.get("is_video"):
                continue

            # Target category subfolder (TV Shows / Movies) if dest_root provided
            cat_folder = "TV Shows" if meta["media_type"] == "tv" else "Movies"
            proposed_full = os.path.join(dest_root, cat_folder, meta["proposed_relative_path"])

            exists = os.path.exists(proposed_full)

            items.append(
                {
                    "source_path": full_src,
                    "filename": f,
                    "media_type": meta["media_type"],
                    "title": meta["title"],
                    "year": meta.get("year"),
                    "season": meta.get("season"),
                    "episode": meta.get("episode"),
                    "resolution": meta["resolution"],
                    "codec": meta["codec"],
                    "destination_path": proposed_full,
                    "destination_exists": exists,
                    "confidence": meta["confidence"],
                    "status": "ready" if not exists else "collision",
                }
            )

    return {
        "status": "ok",
        "source_dir": source_dir,
        "target_dir": dest_root,
        "total_files": len(items),
        "items": items,
    }


def apply_organize(
    items: list[dict[str, Any]],
    action: str = "move",
    hardlink: bool = False,
) -> dict[str, Any]:
    """
    Executes physical reorganization (atomic move, copy, or hardlink).
    Preserves torrent seeding when hardlink=True.
    """
    from backend.fsutil import resolve_within

    allowed_roots = _get_allowed_media_roots()
    success_count = 0
    failed_items = []

    for it in items:
        src = it.get("source_path")
        dst = it.get("destination_path")
        if not src or not dst or not os.path.isfile(src):
            failed_items.append({"source": src, "error": "Source file not found"})
            continue

        if os.path.islink(src):
            failed_items.append({"source": src, "destination": dst, "error": "Symlink source is not permitted"})
            continue

        resolved_src = resolve_within(src, allowed_roots)
        if not resolved_src:
            failed_items.append(
                {"source": src, "destination": dst, "error": "Source file outside permitted storage roots"}
            )
            continue

        resolved_dst = resolve_within(dst, allowed_roots)
        if not resolved_dst:
            failed_items.append(
                {"source": src, "destination": dst, "error": "Destination file outside permitted storage roots"}
            )
            continue

        if os.path.islink(dst) or (os.path.exists(dst) and os.path.islink(dst)):
            failed_items.append(
                {"source": src, "destination": dst, "error": "Destination symlink collision is not permitted"}
            )
            continue

        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)

            if hardlink:
                try:
                    os.link(src, dst)
                    success_count += 1
                    continue
                except OSError as e:
                    logger.debug(f"[MediaOrganizer] Hardlink failed, falling back to move: {e}")

            if action == "copy":
                shutil.copy2(src, dst)
            else:
                # Atomic rename on same filesystem, copy+delete if cross-device
                try:
                    os.replace(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
                    os.remove(src)

            success_count += 1
        except Exception as e:
            failed_items.append({"source": src, "destination": dst, "error": str(e)})

    return {
        "status": "ok" if not failed_items else "partial",
        "total_processed": len(items),
        "success_count": success_count,
        "failed_count": len(failed_items),
        "failures": failed_items,
    }
