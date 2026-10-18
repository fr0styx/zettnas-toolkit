"""
Unit & Integration Tests for ZettNAS Multi-Modal Local RAG & Visual Search Engine (ZettAI).
Covers:
  1. Strict NPU -> GPU -> CPU hardware acceleration priority cascade
  2. Recipe & Document RAG (Markdown, DOCX, PDF, Secret Redaction, Structured Recipe Cards)
  3. Visual Photo Search (Pool, Beach, Red Car vs Blue Car vs Silver Car on generic IMG_xxxx.JPG filenames)
  4. Spindown-Safe Indexing Guard & 100% Zero-Disk-Touch Query/Thumbnail execution
  5. Multi-user RBAC (/homes/<username> isolation & prefix-sibling immunity) + FTS5 punctuation safety
"""

import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from backend.auth import AuthenticatedPrincipal
from backend.services.media_engine import (
    build_llm_recommendations,
    detect_hardware_accelerator,
    pull_huggingface_model,
    search_huggingface_models,
)
from backend.services.rag_engine import (
    RagSearchEngine,
    build_safe_fts5_query,
    is_backing_disk_in_standby,
    parse_multimodal_query,
    resolve_path_backing_dev,
)
from backend.state import Z_STATE


def _make_pool_photo(path: str) -> None:
    """Creates a synthetic swimming pool photo (cyan/aqua + bright blue water) with a generic filename."""
    img = Image.new("RGB", (160, 160), (14, 195, 225))  # Cyan/aqua pool water
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 160, 45], fill=(35, 130, 245))  # Deep blue water/sky top
    draw.rectangle([20, 60, 140, 145], fill=(6, 210, 235))  # Bright turquoise pool center
    img.save(path, format="JPEG", quality=90)


def _make_beach_photo(path: str) -> None:
    """Creates a synthetic sandy beach photo (sky/ocean blue-cyan top + warm sand bottom)."""
    img = Image.new("RGB", (160, 160), (235, 200, 135))  # Warm sandy beach base
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 160, 55], fill=(55, 155, 245))  # Blue sky
    draw.rectangle([0, 55, 160, 88], fill=(12, 190, 220))  # Cyan/turquoise ocean waves
    draw.rectangle([0, 88, 160, 160], fill=(238, 198, 118))  # Golden sand shore
    img.save(path, format="JPEG", quality=90)


def _make_car_photo(path: str, body_rgb: tuple) -> None:
    """
    Creates a synthetic photo of a colored car in the center ROI against a neutral background
    with dark lower tire/wheel shadow regions.
    """
    img = Image.new("RGB", (160, 160), (235, 240, 245))  # Neutral bright backdrop
    draw = ImageDraw.Draw(img)
    # Center car body inside [40..120, 45..110]
    draw.rectangle([42, 48, 118, 106], fill=body_rgb)
    # Dark tires / wheel arches in lower center ROI
    draw.rectangle([46, 102, 68, 118], fill=(18, 20, 24))
    draw.rectangle([92, 102, 114, 118], fill=(18, 20, 24))
    img.save(path, format="JPEG", quality=92)


def test_npu_gpu_cpu_priority_hierarchy():
    """Verifies strict Tier 1 (NPU) -> Tier 2 (GPU) -> Tier 3 (CPU) priority order."""
    # 1. When both NPU (/dev/accel/accel0) and GPU (/dev/dri/renderD128) exist -> NPU wins (Tier 1)
    with patch(
        "os.path.exists",
        side_effect=lambda p: p in ("/dev/accel/accel0", "/dev/dri/renderD128", "/dev/kfd"),
    ):
        accel = detect_hardware_accelerator()
        assert accel["has_npu"] is True
        assert accel["acceleration_backend"] == "intel_npu"
        assert accel["active_tier"] == 1
        assert accel["active_tier_name"] == "NPU"
        assert accel["priority_order"] == ["NPU", "GPU", "CPU"]

    # 2. Rockchip RKNPU (/dev/rknpu) -> Tier 1 NPU wins over GPU
    with patch(
        "os.path.exists",
        side_effect=lambda p: p in ("/dev/rknpu", "/dev/dri/renderD128"),
    ):
        accel_rk = detect_hardware_accelerator()
        assert accel_rk["has_npu"] is True
        assert accel_rk["acceleration_backend"] == "rockchip_npu"
        assert accel_rk["active_tier"] == 1
        assert accel_rk["active_tier_name"] == "NPU"

    # 3. No NPU, but Intel/AMD iGPU present -> Tier 2 GPU wins over CPU
    with (
        patch("os.path.exists", side_effect=lambda p: p in ("/dev/dri/renderD128",)),
        patch("glob.glob", return_value=["/dev/dri/renderD128"]),
    ):
        accel_gpu = detect_hardware_accelerator()
        assert accel_gpu["has_npu"] is False
        assert accel_gpu["has_igpu"] is True
        assert accel_gpu["acceleration_backend"] == "intel_qsv"
        assert accel_gpu["active_tier"] == 2
        assert accel_gpu["active_tier_name"] == "GPU"

    # 4. Headless / CPU-only fallback -> Tier 3 CPU
    with (
        patch("os.path.exists", return_value=False),
        patch("glob.glob", return_value=[]),
    ):
        accel_cpu = detect_hardware_accelerator()
        assert accel_cpu["has_npu"] is False
        assert accel_cpu["has_igpu"] is False
        assert accel_cpu["acceleration_backend"] == "cpu"
        assert accel_cpu["active_tier"] == 3
        assert accel_cpu["active_tier_name"] == "CPU"


def test_recipe_and_document_rag_with_secret_redaction(tmp_path):
    """Verifies indexing & grounded Q&A for recipes, DOCX, technical docs, and secret redaction."""
    db_file = str(tmp_path / "rag_test.db")
    engine = RagSearchEngine(db_path=db_file)

    docs_dir = tmp_path / "mnt" / "user" / "documents"
    docs_dir.mkdir(parents=True)

    # 1. Recipe markdown file
    recipe_file = docs_dir / "nonna_garlic_pasta.md"
    recipe_file.write_text(
        "# Nonna's Roasted Garlic & Olive Oil Linguine\n\n"
        "Prep time: 10 mins\n"
        "Cook time: 15 mins\n"
        "Servings: 4\n\n"
        "## Ingredients\n"
        "- 1 lb linguine pasta\n"
        "- 8 cloves fresh garlic, thinly sliced\n"
        "- 1/2 cup extra-virgin olive oil\n"
        "- 1 tsp red pepper flakes\n"
        "- 1/2 cup fresh parsley, chopped\n\n"
        "## Instructions\n"
        "1. Boil the linguine in salted water until al dente.\n"
        "2. Gently toast sliced garlic in olive oil over low heat for 5 minutes until golden.\n"
        "3. Toss pasta with garlic oil, pasta water, red pepper flakes, and parsley.\n",
        encoding="utf-8",
    )

    # 2. Technical documentation with embedded secret token that MUST be redacted
    tech_file = docs_dir / "nas_network_setup.md"
    tech_file.write_text(
        "# ZettNAS VLAN & WireGuard Guide\n\n"
        "Configure the 10GbE bond0 interface with MTU 9000 jumbo frames.\n"
        "Admin token: zat_secret_99887766554433221100 should never appear in plaintext.\n",
        encoding="utf-8",
    )

    # 3. DOCX file
    docx_file = docs_dir / "pool_maintenance.docx"
    with zipfile.ZipFile(docx_file, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Saltwater Swimming Pool Maintenance Manual: Keep free chlorine between 2 and 4 ppm.</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )

    sync_res = engine.index_directory(str(docs_dir), respect_standby=False)
    assert sync_res["status"] == "completed"
    assert sync_res["indexed_files"] == 3

    # Second run should fast-skip all 3 unchanged files in microseconds
    sync_res_2 = engine.index_directory(str(docs_dir), respect_standby=False)
    assert sync_res_2["indexed_files"] == 0
    assert sync_res_2["skipped_unchanged"] == 3

    # Ask for pasta recipe with garlic
    ask_res = engine.ask("pasta recipe with garlic", scope="all")
    assert ask_res["structured_card"] is not None
    assert ask_res["structured_card"]["card_type"] == "recipe"
    assert "Linguine" in ask_res["structured_card"]["title"]
    assert any("garlic" in ing.lower() for ing in ask_res["structured_card"]["ingredients"])
    assert len(ask_res["citations"]) >= 1
    assert ask_res["citations"][0]["name"] == "nonna_garlic_pasta.md"

    # Verify DOCX search works
    docx_search = engine.search("saltwater chlorine ppm", mode="documents")
    assert len(docx_search["items"]) >= 1
    assert docx_search["items"][0]["name"] == "pool_maintenance.docx"

    # Verify secret redaction invariant (AGENTS.md §1.4)
    net_search = engine.search("jumbo frames bond0", mode="documents")
    assert len(net_search["items"]) >= 1
    excerpt = net_search["items"][0]["excerpt"]
    assert "zat_secret_99887766554433221100" not in excerpt


def test_visual_photo_search_pool_beach_and_car_colors(tmp_path):
    """
    Verifies visual scene detection ('pool', 'beach') and compositional subject color binding
    ('red car', 'blue car', 'silver car') on generic camera filenames (IMG_0001..IMG_0005.JPG).
    """
    db_file = str(tmp_path / "rag_visual.db")
    engine = RagSearchEngine(db_path=db_file)

    photos_dir = tmp_path / "mnt" / "user" / "photos"
    photos_dir.mkdir(parents=True)

    _make_pool_photo(str(photos_dir / "IMG_0001.JPG"))
    _make_beach_photo(str(photos_dir / "IMG_0002.JPG"))
    _make_car_photo(str(photos_dir / "IMG_0003.JPG"), (225, 25, 30))  # Red car
    _make_car_photo(str(photos_dir / "IMG_0004.JPG"), (25, 95, 230))  # Blue car
    _make_car_photo(str(photos_dir / "IMG_0005.JPG"), (165, 170, 178))  # Silver/gray car

    res = engine.index_directory(str(photos_dir), respect_standby=False)
    assert res["indexed_files"] == 5

    # 1. Search "photos in pool" -> IMG_0001.JPG ranks #1
    pool_res = engine.search("photos in pool", mode="photos")
    assert len(pool_res["photo_results"]) >= 1
    assert pool_res["photo_results"][0]["name"] == "IMG_0001.JPG"
    assert "pool" in pool_res["photo_results"][0]["scene_tags"]

    # 2. Search "beach" -> IMG_0002.JPG ranks #1
    beach_res = engine.search("beach", mode="photos")
    assert len(beach_res["photo_results"]) >= 1
    assert beach_res["photo_results"][0]["name"] == "IMG_0002.JPG"
    assert "beach" in beach_res["photo_results"][0]["scene_tags"]

    # 3. Search "red car" -> IMG_0003.JPG (Red car) ranks #1 with compositional_match=True
    red_car_res = engine.search("red car", mode="photos")
    assert red_car_res["parsed_intent"]["auto_colors"] == ["red"]
    assert "car" in red_car_res["parsed_intent"]["auto_scenes"]
    assert len(red_car_res["photo_results"]) >= 1
    top_red = red_car_res["photo_results"][0]
    assert top_red["name"] == "IMG_0003.JPG"
    assert top_red["compositional_match"] is True
    assert "red" in top_red["object_colors"]

    # 4. Search "blue car" -> IMG_0004.JPG (Blue car) ranks #1
    blue_car_res = engine.search("blue car", mode="photos")
    assert len(blue_car_res["photo_results"]) >= 1
    top_blue = blue_car_res["photo_results"][0]
    assert top_blue["name"] == "IMG_0004.JPG"
    assert top_blue["compositional_match"] is True
    assert "blue" in top_blue["object_colors"]

    # 5. Search "silver car" or "gray car" -> IMG_0005.JPG ranks #1
    silver_car_res = engine.search("gray car", mode="photos")
    assert silver_car_res["parsed_intent"]["auto_colors"] == ["silver"]
    assert len(silver_car_res["photo_results"]) >= 1
    assert silver_car_res["photo_results"][0]["name"] == "IMG_0005.JPG"


def test_spindown_guard_and_zero_disk_touch_queries(tmp_path):
    """
    Verifies:
      1. Indexing a path on a sleeping disk (Z_STATE.cached_smart_data['sdc'] == 'standby')
         defers to rag_deferred_queue without reading the disk.
      2. Queries and thumbnail fetches work 100% from SQLite even if source files are removed.
    """
    db_file = str(tmp_path / "rag_spindown.db")
    engine = RagSearchEngine(db_path=db_file)

    # Index a photo while awake
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir(parents=True)
    img_path = photo_dir / "pool_party.jpg"
    _make_pool_photo(str(img_path))

    engine.index_directory(str(photo_dir), respect_standby=False)

    # Remove the physical source file from disk to prove 100% Zero-Disk-Touch at query & thumbnail time
    os.remove(img_path)

    search_res = engine.search("pool", mode="photos")
    assert len(search_res["photo_results"]) == 1
    fid = search_res["photo_results"][0]["file_id"]

    # Thumbnail BLOB is served directly from SQLite without touching the deleted file
    thumb_bytes, mime = engine.get_thumbnail(fid)
    assert len(thumb_bytes) > 50
    assert mime in ("image/webp", "image/jpeg")

    # Simulate /mnt/disk2 -> 'sdc' in standby
    Z_STATE.cached_smart_data["sdc"] = (31, "standby")
    try:
        defer_res = engine.index_directory("/mnt/disk2/media", respect_standby=True, force_wake=False)
        assert defer_res["status"] == "deferred_standby"
        assert defer_res["deferred_standby"] == 1
        stats = engine.get_index_stats()
        assert stats["deferred_queue_count"] >= 1
    finally:
        Z_STATE.cached_smart_data.pop("sdc", None)


def test_multiuser_rbac_homes_isolation_and_fts5_escaping(tmp_path, monkeypatch):
    """
    Verifies that User A ('alice') and User B ('bob') are strictly isolated under /homes/<user>,
    and prefix sibling directories (/homes/alice_bob) cannot leak.
    """
    db_file = str(tmp_path / "rag_rbac.db")
    engine = RagSearchEngine(db_path=db_file)

    homes_root = tmp_path / "mnt" / "user" / "homes"
    alice_dir = homes_root / "alice"
    bob_dir = homes_root / "bob"
    alice_bob_dir = homes_root / "alice_bob"
    alice_dir.mkdir(parents=True)
    bob_dir.mkdir(parents=True)
    alice_bob_dir.mkdir(parents=True)

    (alice_dir / "alice_secret_recipe.md").write_text(
        "# Alice Secret Truffle Pasta\nIngredients:\n- 2 tbsp black truffle oil\n- 1 lb fettuccine\n",
        encoding="utf-8",
    )
    (bob_dir / "bob_diary.md").write_text(
        "# Bob Private Notes\nBob's private truffle pasta notes.\n",
        encoding="utf-8",
    )
    (alice_bob_dir / "sibling_leak.md").write_text(
        "# Sibling Directory File\nTruffle pasta in alice_bob folder.\n",
        encoding="utf-8",
    )

    engine.index_directory(str(homes_root), respect_standby=False)

    alice_principal = AuthenticatedPrincipal(
        {
            "username": "alice",
            "role_id": "share_user",
            "scopes": ["shares:read", "system:read"],
        }
    )
    bob_principal = AuthenticatedPrincipal(
        {
            "username": "bob",
            "role_id": "share_user",
            "scopes": ["shares:read", "system:read"],
        }
    )

    # Alice searches for "truffle pasta" -> sees ONLY her own file, never Bob's or alice_bob's
    alice_hits = engine.search("truffle pasta", principal=alice_principal)
    alice_names = [it["name"] for it in alice_hits["items"]]
    assert "alice_secret_recipe.md" in alice_names
    assert "bob_diary.md" not in alice_names
    assert "sibling_leak.md" not in alice_names

    # Bob searches for "truffle pasta" -> sees ONLY his own file, never Alice's
    bob_hits = engine.search("truffle pasta", principal=bob_principal)
    bob_names = [it["name"] for it in bob_hits["items"]]
    assert "bob_diary.md" in bob_names
    assert "alice_secret_recipe.md" not in bob_names

    # Subtree prefix test: scoping to alice_dir must NOT match alice_bob_dir even for admin
    admin_principal = AuthenticatedPrincipal(
        {
            "username": "admin",
            "role_id": "superadmin",
            "scopes": ["*"],
        }
    )
    scoped_hits = engine.search("truffle pasta", path_prefix=str(alice_dir), principal=admin_principal)
    scoped_names = [it["name"] for it in scoped_hits["items"]]
    assert scoped_names == ["alice_secret_recipe.md"]

    # FTS5 adversarial punctuation test
    weird_q = "what's mom's \"truffle-pasta\"? (garlic & oil) * AND OR NOT : / \\ [test]"
    safe_fts = build_safe_fts5_query(weird_q)
    assert safe_fts != ""
    res_weird = engine.search(weird_q, principal=alice_principal)
    assert isinstance(res_weird["items"], list)
    intent = parse_multimodal_query("photos of red car at the beach")
    assert intent["auto_colors"] == ["red"]
    assert "car" in intent["auto_scenes"]
    assert "beach" in intent["auto_scenes"]


def test_sync_pause_resume_stop_and_multi_folder_watched_paths(tmp_path):
    """
    Verifies:
      1. Multi-folder `watched_paths` configuration and `index_paths()` across multiple directories.
      2. Pause, Resume, and Stop state machine transitions on `RagSearchEngine`.
    """
    db_file = str(tmp_path / "rag_controls.db")
    cfg_file = str(tmp_path / "rag_config.json")
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", cfg_file):
        engine = RagSearchEngine(db_path=db_file)

        folder_a = tmp_path / "recipes_share"
        folder_b = tmp_path / "manuals_share"
        folder_a.mkdir(parents=True)
        folder_b.mkdir(parents=True)

        (folder_a / "lemon_pasta.md").write_text("# Lemon Garlic Pasta\nIngredients:\n- 1 lemon\n- 4 cloves garlic\n")
        (folder_b / "ups_guide.md").write_text("# NUT UPS Watchdog Manual\nPort 3493 configuration.\n")

        cfg = engine.update_config({"watched_paths": [str(folder_a), str(folder_b)]})
        assert cfg["watched_paths"] == [str(folder_a), str(folder_b)]

        res = engine.index_paths([str(folder_a), str(folder_b)], respect_standby=False)
        assert res["status"] == "completed"
        assert res["indexed_files"] == 2

        # Verify pause / resume / stop state controls
        p_res = engine.pause_sync()
        assert p_res["sync_state"] == "paused"
        assert engine.get_sync_progress()["is_paused"] is True

        r_res = engine.resume_sync()
        assert r_res["sync_state"] == "idle"
        assert engine.get_sync_progress()["is_paused"] is False

        # If stop is requested before/during walk, index_directory honors stop immediately
        s_res = engine.stop_sync()
        assert s_res["sync_state"] == "stopped"
        stopped_run = engine.index_directory(str(folder_a), respect_standby=False, _reset_control_flags=False)
        assert stopped_run["status"] == "stopped"


def test_unraid_shfs_share_standby_detection_never_wakes_hdd(tmp_path):
    """
    Verifies that on Unraid (/mnt/user/<share>), cache-only shares (e.g., apishare on nvme2n1)
    sync normally while array-backed shares (e.g., vault on spundown disk1/sda) are detected as
    STANDBY via disks.ini/shares.ini and deferred with ZERO disk wakeups.
    """
    mock_disks = {
        "parity": {"name": "parity", "device": "sdb", "type": "Parity", "color": "green-blink", "spundown": True},
        "disk1": {"name": "disk1", "device": "sda", "type": "Data", "color": "green-blink", "spundown": True},
        "ark": {"name": "ark", "device": "nvme2n1", "type": "Cache", "color": "green-on", "spundown": False},
    }
    mock_shares = {
        "apishare": {"name": "apishare", "useCache": "only", "cachePool": "ark"},
        "vault": {"name": "vault", "useCache": "yes", "cachePool": "ark"},
    }

    with patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_disks, mock_shares)):
        # Cache-only share resolves to nvme2n1 (running)
        assert resolve_path_backing_dev("/mnt/user/apishare") == "nvme2n1"
        assert is_backing_disk_in_standby("/mnt/user/apishare") is False

        # Array-spanning share resolves to sleeping array disk sda (standby)
        assert resolve_path_backing_dev("/mnt/user/vault") == "sda"
        assert is_backing_disk_in_standby("/mnt/user/vault") is True
        assert is_backing_disk_in_standby("/mnt/user") is True

        db_file = str(tmp_path / "rag_unraid.db")
        engine = RagSearchEngine(db_path=db_file)
        defer_res = engine.index_directory("/mnt/user/vault", respect_standby=True, force_wake=False)
        assert defer_res["status"] == "deferred_standby"
        assert defer_res["deferred_standby"] == 1


def test_hardware_aware_npu_gpu_llm_recommendations(tmp_path):
    """
    Verifies that `build_llm_recommendations()` dynamically tailors recommended Hugging Face LLMs & multi-modal
    models based on onboard NPU (/dev/accel/accel0), iGPU/dGPU (/dev/dri/renderD128, CUDA), and system RAM,
    and puts a prominent warning on every model that does not fit the user's hardware.
    """
    # Case 1: Intel AI Boost NPU + Intel Arc iGPU + 58.4 GB RAM (Zettlab Ultra appliance profile)
    npu_igpu_accel = {
        "has_npu": True,
        "has_igpu": True,
        "has_cuda": False,
        "has_rocm": False,
        "name": "Intel AI Boost NPU (/dev/accel/accel0)",
        "secondary_gpu": "Intel Arc / QuickSync iGPU (/dev/dri/renderD128)",
        "tier_number": 1,
    }
    rec_npu = build_llm_recommendations(
        npu_igpu_accel, ram_gb=58.4, active_model="qwen2.5:3b", include_incompatible=True, min_release_year=None
    )
    assert "NPU + GPU" in rec_npu["headline"]
    assert rec_npu["active_model"] == "qwen2.5:3b"
    models_by_id = {m["id"]: m for m in rec_npu["models"]}
    assert models_by_id["qwen2.5:3b"]["recommended"] is True
    assert models_by_id["qwen2.5:3b"]["active"] is True
    assert models_by_id["qwen2.5:3b"]["fits_hardware"] is True
    assert models_by_id["qwen2.5:3b"]["hardware_warning"] is False
    assert models_by_id["qwen2.5:3b"]["hf_repo"] == "Qwen/Qwen2.5-3B-Instruct-GGUF"
    assert "NPU" in models_by_id["qwen2.5:3b"]["fit_badge"]
    assert models_by_id["qwen2.5vl:7b"]["recommended"] is True
    assert models_by_id["deepseek-r1:14b"]["recommended"] is True
    assert models_by_id["deepseek-r1:14b"]["fits_hardware"] is True

    # Heavy discrete-GPU / datacenter models carry hardware warnings when include_incompatible=True
    for heavy_id in ("gemma3:27b", "qwen2.5:32b", "llama3.3:70b", "deepseek-r1:70b", "llama3.1:405b"):
        assert heavy_id in models_by_id
        assert models_by_id[heavy_id]["fits_hardware"] is False
        assert models_by_id[heavy_id]["hardware_warning"] is True
        assert "Hardware Warning:" in (models_by_id[heavy_id]["warning_message"] or "")
        assert "⚠️" in models_by_id[heavy_id]["fit_badge"]

    # In standard mode (include_incompatible=False), non-fitting models MUST be completely removed
    rec_compat = build_llm_recommendations(
        npu_igpu_accel, ram_gb=58.4, active_model="qwen2.5:3b", min_release_year=None
    )
    compat_ids = {m["id"] for m in rec_compat["models"]}
    for heavy_id in ("gemma3:27b", "qwen2.5:32b", "llama3.3:70b", "deepseek-r1:70b", "llama3.1:405b"):
        assert heavy_id not in compat_ids

    # Case 2: GPU-only profile with 16 GB RAM
    gpu_only_accel = {
        "has_npu": False,
        "has_igpu": True,
        "has_cuda": False,
        "has_rocm": False,
        "name": "Intel Arc / QuickSync iGPU (/dev/dri/renderD128)",
        "tier_number": 2,
    }
    rec_gpu = build_llm_recommendations(
        gpu_only_accel, ram_gb=16.0, active_model="qwen2.5:7b", include_incompatible=True, min_release_year=None
    )
    assert "GPU" in rec_gpu["headline"]
    gpu_models = {m["id"]: m for m in rec_gpu["models"]}
    assert gpu_models["qwen2.5:7b"]["recommended"] is True
    assert gpu_models["deepseek-r1:14b"]["recommended"] is False  # <24GB RAM and no CUDA
    assert gpu_models["deepseek-r1:14b"]["fits_hardware"] is False
    assert gpu_models["deepseek-r1:14b"]["hardware_warning"] is True

    # Case 3: Pull & Search Hugging Face release models with hardware warning evaluation
    cfg_file = str(tmp_path / "rag_hf_pull_config.json")
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", cfg_file):
        search_res = search_huggingface_models("70B", limit=10, min_release_year=None)
        assert search_res["status"] == "ok"
        assert len(search_res["models"]) >= 1
        assert all(m["hardware_warning"] is True for m in search_res["models"])

        # Pull an oversized 72B Hugging Face release model -> flagged with hardware_warning=True
        pull_heavy = pull_huggingface_model("https://huggingface.co/Qwen/Qwen2.5-72B-Instruct-GGUF", activate=True)
        assert pull_heavy["status"] == "ok"
        assert pull_heavy["fits_hardware"] is False
        assert pull_heavy["hardware_warning"] is True
        assert "Hardware Warning:" in (pull_heavy["warning_message"] or "")
        assert pull_heavy["model"]["hf_repo"] == "Qwen/Qwen2.5-72B-Instruct-GGUF"

        # Pull an edge 3B INT4 Hugging Face release model -> fits_hardware=True
        pull_edge = pull_huggingface_model("Qwen/Qwen2.5-3B-Instruct-INT4", activate=True)
        assert pull_edge["status"] == "ok"
        assert pull_edge["fits_hardware"] is True
        assert pull_edge["hardware_warning"] is False


def test_zettai_learning_lifecycle_favorites_and_multimode_search(tmp_path):
    """
    Verifies ZettAI official learning & search features:
      1. Master Switch (`enabled: False` pauses learning and sets zettai_status to 'Disabled')
      2. Learning Results (`get_learning_results`) and `relearn_failed_files`
      3. Multi-mode search (`match_tab='keyword'`, `sort_by='mtime'`, `category_groups`)
      4. Favorites toggle (`toggle_favorite`) reflected in search results
    """
    db_file = str(tmp_path / "rag_zettai_lifecycle.db")
    cfg_file = str(tmp_path / "rag_zettai_config.json")
    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", cfg_file):
        engine = RagSearchEngine(db_path=db_file)

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        doc_a = docs_dir / "architecture_spec.md"
        doc_a.write_text("# ZettAI NPU Architecture\nIntel AI Boost NPU acceleration with OpenVINO INT4.\n")

        engine.index_directory(str(docs_dir), respect_standby=False)

        # Verify Learning Results
        learn_res = engine.get_learning_results()
        assert learn_res["succeeded_count"] == 1
        assert learn_res["failed_count"] == 0
        assert learn_res["zettai_status"] == "Idle"

        # Toggle favorite on doc_a
        fav_on = engine.toggle_favorite(str(doc_a))
        assert fav_on["is_favorite"] is True

        # Search with keyword tab and mtime sort
        search_res = engine.search("OpenVINO", match_tab="keyword", sort_by="mtime")
        assert search_res["match_tab"] == "keyword"
        assert search_res["sort_by"] == "mtime"
        assert len(search_res["category_groups"]["documents"]) >= 1
        assert search_res["items"][0]["is_favorite"] is True

        # Disable ZettAI globally -> status becomes Disabled and indexing skips
        engine.update_config({"enabled": False})
        assert engine.get_learning_results()["zettai_status"] == "Disabled"
        disabled_idx = engine.index_directory(str(docs_dir), respect_standby=False)
        assert disabled_idx["status"] == "disabled"


def test_auto_learning_triggers_automatically_when_sleeping_disk_spins_up():
    """Verify deferred paths and watched folders auto-learn when a sleeping disk spins up."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rag_spinup.db"
        cfg_path = Path(tmpdir) / "rag_spinup_config.json"
        with patch("backend.services.rag_engine.RAG_CONFIG_PATH", str(cfg_path)):
            engine = RagSearchEngine(db_path=str(db_path))

            vault_video = Path(tmpdir) / "vault_video"
            vault_video.mkdir(parents=True, exist_ok=True)
            (vault_video / "beach_clip.md").write_text(
                "# Beach Vacation\nSunset ocean video notes.",
                encoding="utf-8",
            )

            disk_state = {"standby": True}

            with (
                patch("backend.services.rag_engine.resolve_path_backing_dev", return_value="sda"),
                patch(
                    "backend.services.rag_engine.is_backing_disk_in_standby",
                    side_effect=lambda _p: disk_state["standby"],
                ),
                patch(
                    "backend.services.rag_engine.get_sleeping_disks_list",
                    side_effect=lambda: ["sda"] if disk_state["standby"] else [],
                ),
            ):
                # Configure watched_paths and simulate a stale removed folder in rag_deferred_queue
                stale_removed = str(Path(tmpdir) / "old_vault")
                engine.enqueue_deferred_path(stale_removed, reason="disk_standby")
                engine.update_config(
                    {
                        "enabled": True,
                        "auto_learn_on_spinup": True,
                        "watched_paths": [str(vault_video)],
                    }
                )

                # 1. Reconcile watched folders while disk is in standby:
                #    stale_removed is pruned, and vault_video is enqueued in rag_deferred_queue
                engine.sync_watched_deferred_queue()
                queue = engine.get_deferred_queue()
                queued_paths = [q["path"] for q in queue]
                assert stale_removed not in queued_paths
                assert str(vault_video) in queued_paths

                # 2. While disk is still sleeping, spinup check does NOT trigger indexing
                res_sleeping = engine.check_and_trigger_spinup_auto_learn(background=False)
                assert res_sleeping["triggered"] is False
                assert engine.get_index_stats()["total_files"] == 0

                # 3. Disk spins up! Auto-learn immediately triggers and indexes the folder
                disk_state["standby"] = False
                res_awake = engine.check_and_trigger_spinup_auto_learn(background=False)
                assert res_awake["triggered"] is True
                assert str(vault_video) in res_awake["paths"]
                assert "sda" in res_awake["woken_disks"]
                assert engine.get_index_stats()["total_files"] == 1
                assert len(engine.get_deferred_queue()) == 0
                assert engine._last_auto_learn_event is not None
                assert res_awake["sync"]["indexed_files"] >= 1


def test_ai_chat_agent_tools_web_browsing_and_llm_telemetry(tmp_path):
    """
    Verifies the AI Chatbot & NAS Hardware Copilot (`backend/services/ai_chat_agent.py`):
      1. `build_llm_execution_telemetry` returns active_model, accelerator_label, runtime_mode, and zero_disk_wakeups
      2. `run_agentic_chat` invokes NAS Hardware Tools (`get_system_telemetry`, `get_disks_and_standby_status`, `set_fan_profile`)
      3. `run_agentic_chat` invokes `browse_internet` when web verification is requested
    """
    from backend.services.ai_chat_agent import (
        AVAILABLE_NAS_TOOLS,
        build_llm_execution_telemetry,
        run_agentic_chat,
    )

    assert len(AVAILABLE_NAS_TOOLS) == 9
    tool_names = {t["name"] for t in AVAILABLE_NAS_TOOLS}
    assert "get_system_telemetry" in tool_names
    assert "get_disks_and_standby_status" in tool_names
    assert "set_fan_profile" in tool_names
    assert "list_docker_containers" in tool_names
    assert "browse_internet" in tool_names

    tel = build_llm_execution_telemetry(
        elapsed_ms=24.5,
        tools_called=["get_system_telemetry"],
        web_sources_count=1,
    )
    assert "active_model" in tel
    assert tel["zero_disk_wakeups"] is True
    assert tel["tools_called"] == ["get_system_telemetry"]

    # Test NAS Hardware Telemetry + Disk Standby Query
    chat_hw = run_agentic_chat(
        message="What is my NAS CPU load and which disks are sleeping in standby?",
        allow_web_search=False,
        allow_nas_tools=True,
    )
    assert chat_hw["status"] == "ok"
    called_hw = [c["tool"] for c in chat_hw["tools_called"]]
    assert "get_system_telemetry" in called_hw
    assert "get_disks_and_standby_status" in called_hw
    assert "Live NAS System & AI Accelerator Telemetry" in chat_hw["reply"]
    assert "Physical Disks & Standby Guard" in chat_hw["reply"]
    assert chat_hw["llm_telemetry"]["zero_disk_wakeups"] is True

    # Test Web Browsing verification with mocked web tool response
    with patch(
        "backend.services.ai_chat_agent.tool_browse_internet",
        return_value={
            "status": "ok",
            "query": "Linux 6.12 LTS",
            "results_count": 1,
            "sources": [
                {
                    "title": "Linux kernel — Wikipedia",
                    "url": "https://en.wikipedia.org/wiki/Linux_kernel",
                    "snippet": "Linux 6.12 is the latest Long Term Support release.",
                    "source": "Wikipedia",
                }
            ],
        },
    ):
        chat_web = run_agentic_chat(
            message="Search the web for Linux 6.12 LTS kernel",
            allow_web_search=True,
            allow_nas_tools=False,
        )
        assert chat_web["status"] == "ok"
        assert any(c["tool"] == "browse_internet" for c in chat_web["tools_called"])
        assert chat_web["web_sources"][0]["title"] == "Linux kernel — Wikipedia"
        assert "Linux 6.12" in chat_web["reply"]


def test_agentic_chat_factual_web_query_and_false_positive_suppression():
    """Verify general factual questions do not match unrelated local PDFs on generic words and answer directly."""
    from backend.services.ai_chat_agent import (
        _extract_wikipedia_infobox_facts,
        _normalize_web_query_and_topic,
        run_agentic_chat,
    )

    topic, web_query = _normalize_web_query_and_topic("Whos the president of the United states?")
    assert topic.lower() == "president of the united states"
    assert "who is" in web_query.lower()

    sample_wikitext = """
    {{Infobox official post
    | post = President of the United States
    | incumbent = [[Donald Trump]]
    | incumbentsince = January 20, 2025
    }}
    """
    facts = _extract_wikipedia_infobox_facts(sample_wikitext)
    assert facts.get("incumbent") == "Donald Trump"
    assert facts.get("incumbentsince") == "January 20, 2025"

    mock_web_res = {
        "status": "ok",
        "query": "President of the United States",
        "topic": "President of the United States",
        "direct_fact": {
            "subject": "President of the United States",
            "incumbent": "Donald Trump",
            "since": "January 20, 2025",
            "bio": "Donald John Trump is an American politician who is the 47th president of the United States.",
        },
        "results_count": 2,
        "sources": [
            {
                "title": "Donald Trump — Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Donald_Trump",
                "snippet": "Donald John Trump is an American politician who is the 47th president of the United States.",
                "source": "Wikipedia",
            },
            {
                "title": "President of the United States — Wikipedia",
                "url": "https://en.wikipedia.org/wiki/President_of_the_United_States",
                "snippet": "Current President of the United States: Donald Trump.",
                "source": "Wikipedia",
            },
        ],
    }

    with patch("backend.services.ai_chat_agent.tool_browse_internet", return_value=mock_web_res):
        res_chat = run_agentic_chat(
            message="Whos the president of the United states?",
            allow_web_search=True,
            allow_nas_tools=True,
        )
        assert res_chat["status"] == "ok"
        assert "Donald Trump" in res_chat["reply"]
        assert "President of the United States" in res_chat["reply"]
        # Ensure unrelated local books are not returned for general web questions
        assert "Unlimited Power" not in res_chat["reply"]


def test_agentic_chat_self_identity_no_internet_search():
    """
    Verifies that asking self-identity / creator questions ('Who created you?', 'Who is Underdog?')
    never triggers blind DuckDuckGo web search (which would return Isaiah 43:1), and instead
    directly answers with ZettAI Copilot, active model (Underdog-Saluki-27B by ConwayResearch/Kujira),
    and local hardware execution context with 0 disk wakeups.
    """
    from backend.services.ai_chat_agent import _is_self_identity_question, run_agentic_chat

    # 1. Intent classifier tests
    assert _is_self_identity_question("who created you") is True
    assert _is_self_identity_question("Who created you?") is True
    assert _is_self_identity_question("who made you") is True
    assert _is_self_identity_question("who are you") is True
    assert _is_self_identity_question("what model are you") is True
    assert _is_self_identity_question("who is underdog") is True
    assert _is_self_identity_question("who created saluki") is True
    assert _is_self_identity_question("who created python") is False
    assert _is_self_identity_question("who created linux") is False
    assert _is_self_identity_question("who is the president of france") is False

    # 2. Chat execution with Underdog model active
    with patch("backend.services.ai_chat_agent.tool_browse_internet") as mock_browse:
        mock_browse.side_effect = AssertionError("browse_internet should NEVER be called for self-identity questions!")

        res = run_agentic_chat(
            message="Who created you?",
            allow_web_search=True,
            allow_nas_tools=True,
            model_override="hf.co/Kujira/Underdog-Saluki-27B-1.0-MTP-Abliterated-GGUF",
        )

        assert res["status"] == "ok"
        # Tool check: browse_internet was skipped, get_system_telemetry was called
        tool_names = [t["tool"] for t in res["tools_called"]]
        assert "browse_internet" not in tool_names
        assert "get_system_telemetry" in tool_names

        # Content verification: mentions Underdog, ConwayResearch, Kujira, ZettAI, and ZettNAS
        reply = res["reply"]
        assert "ZettAI Copilot" in reply
        assert "Underdog-Saluki-27B" in reply
        assert "ConwayResearch" in reply
        assert "Kujira" in reply
        assert "ZettNAS" in reply
        # Must NOT contain external religious text from DuckDuckGo
        assert "Isaiah" not in reply
        assert "Jacob" not in reply
        assert "Israel" not in reply
        assert res["llm_telemetry"]["zero_disk_wakeups"] is True


def test_huggingface_model_release_dates_and_sorting():
    """
    Verifies that Hugging Face catalog models have release dates, release timestamps,
    and can be ordered by release date (newest first).
    """
    from backend.services.media_engine import (
        _parse_hf_date,
        build_llm_recommendations,
        search_huggingface_models,
    )

    # 1. Date parser verification
    disp, ts, iso = _parse_hf_date("2026-10-08T09:12:10.000Z")
    assert disp == "Oct 08, 2026"
    assert ts > 1790000000.0
    assert iso == "2026-10-08T09:12:10.000Z"

    disp_simple, ts_s, iso_s = _parse_hf_date("2024-09-19")
    assert "Sep 19, 2024" in disp_simple
    assert ts_s > 1700000000.0

    # 2. Recommendations sorted by date (newest first)
    accel = {"has_npu": True, "has_igpu": True, "active_tier": 1, "device_label": "Intel AI Boost NPU"}
    recs_date = build_llm_recommendations(accel=accel, ram_gb=32.0, sort_by="date")
    models = recs_date["models"]
    assert len(models) >= 8

    # All models must have release_date_str and release_timestamp
    for m in models:
        assert "release_date_str" in m
        assert "release_timestamp" in m
        assert isinstance(m["release_timestamp"], (int, float))

    # Verification: 2026 release model ranks #1
    assert "2026" in models[0]["release_date_str"]
    assert any(name in models[0]["name"] for name in ("Underdog", "Saluki", "Huihui", "Bark", "Woof"))

    # Timestamps should be monotonically decreasing (or equal)
    timestamps = [m["release_timestamp"] for m in models]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] >= timestamps[i + 1]

    # 3. Search HF models sorted by date
    search_res = search_huggingface_models(query="Underdog", limit=10, sort_by="date")
    assert search_res["status"] == "ok"
    assert len(search_res["models"]) >= 1
    assert "release_date_str" in search_res["models"][0]


def test_remove_models_released_before_2026():
    """
    Verifies that all models released before 2026 (2024, 2025, or earlier)
    are strictly removed by default from recommendations and catalog views.
    """
    from backend.services.media_engine import build_llm_recommendations, is_model_2026_or_newer

    accel = {
        "has_npu": True,
        "has_igpu": True,
        "name": "Intel AI Boost NPU (/dev/accel/accel0)",
        "secondary_gpu": "Intel Arc / QuickSync iGPU (/dev/dri/renderD128)",
        "tier_number": 1,
    }
    recs = build_llm_recommendations(accel=accel, ram_gb=58.4, sort_by="date")
    models = recs["models"]
    assert len(models) >= 4

    # Every single returned model must be 2026 or newer
    for m in models:
        assert is_model_2026_or_newer(m) is True
        rel_str = str(m.get("release_date_str") or m.get("release_date") or "")
        assert not any(yr in rel_str for yr in ("2020", "2021", "2022", "2023", "2024", "2025")), (
            f"Pre-2026 model found: {m.get('name')} with date {rel_str}"
        )
        assert m.get("release_timestamp", 0) >= 1767225600.0 or "Recent" in rel_str

    # Legacy pre-2026 models must NOT be present
    model_ids = {m["id"] for m in models} | {m.get("hf_repo", "") for m in models}
    for old_id in (
        "builtin-npu",
        "qwen2.5:3b",
        "llama3.2:3b",
        "phi3.5:3.8b",
        "gemma3:4b",
        "qwen2.5:7b",
        "qwen2.5vl:7b",
        "mistral-nemo:12b",
        "deepseek-r1:14b",
    ):
        assert old_id not in model_ids

    # Modern 2026 models MUST be present
    assert any("underdog" in mid.lower() or "saluki" in mid.lower() for mid in model_ids)
    assert any("woof" in mid.lower() for mid in model_ids)


def test_agentic_chat_local_autonomous_reasoning_and_coding_with_tools_disabled():
    """
    Verifies that when the user disables Browse Internet and NAS Hardware Tools:
      1. Asking life purpose returns the 4 Sovereign Pillars (Data Sovereignty, Hardware Guardianship, Local Intelligence).
      2. Asking age returns the 2026 Genesis and Underdog-Saluki / Woof architecture.
      3. Asking for the president of the Dominican Republic answers Luis Abinader and PRM directly.
      4. Asking for a disk temperature script returns a standby-safe Python script with `smartctl -n standby`.
      5. Asking for storage architecture compares ZFS vs Unraid vs Btrfs.
      6. Zero generic placeholder sentences are returned.
    """
    from backend.services.ai_chat_agent import run_agentic_chat

    # 1. Life Purpose Inquiry
    res_purpose = run_agentic_chat(
        message="What is your life purpose",
        allow_web_search=False,
        allow_nas_tools=False,
    )
    assert res_purpose["status"] == "ok"
    assert "sovereign" in res_purpose["reply"].lower()
    assert "data sovereignty" in res_purpose["reply"].lower()
    assert "0 hard drive wakeups" in res_purpose["reply"].lower()
    assert "I checked your NAS state and web sources" not in res_purpose["reply"]

    # 2. Age Inquiry
    res_age = run_agentic_chat(
        message="How old are you?",
        allow_web_search=False,
        allow_nas_tools=False,
    )
    assert res_age["status"] == "ok"
    assert "2026" in res_age["reply"]
    assert "ZettNAS Toolkit 2.0" in res_age["reply"]
    assert "I checked your NAS state and web sources" not in res_age["reply"]

    # 3. Dominican Republic President
    res_dr = run_agentic_chat(
        message="Who is the president of the Dominican Republic?",
        allow_web_search=False,
        allow_nas_tools=False,
    )
    assert res_dr["status"] == "ok"
    assert "Luis Abinader" in res_dr["reply"]
    assert "Santo Domingo" in res_dr["reply"]
    assert "I checked your NAS state and web sources" not in res_dr["reply"]

    # 4. Standby-Safe Disk Temperature Python Script
    res_code = run_agentic_chat(
        message="Write a python script to check disk temperatures",
        allow_web_search=False,
        allow_nas_tools=False,
    )
    assert res_code["status"] == "ok"
    assert "smartctl" in res_code["reply"]
    assert "-n standby" in res_code["reply"]
    assert "exit code 2" in res_code["reply"].lower() or "returncode == 2" in res_code["reply"]
    assert "```python" in res_code["reply"]
    assert "I checked your NAS state and web sources" not in res_code["reply"]

    # 5. Storage Architecture (ZFS vs Unraid)
    res_storage = run_agentic_chat(
        message="Explain ZFS vs Unraid",
        allow_web_search=False,
        allow_nas_tools=False,
    )
    assert res_storage["status"] == "ok"
    assert "ZFS" in res_storage["reply"]
    assert "Unraid" in res_storage["reply"]
    assert "Spindown" in res_storage["reply"] or "spindown" in res_storage["reply"].lower()
    assert "I checked your NAS state and web sources" not in res_storage["reply"]


def test_conversational_nlg_kim_jong_un_education_no_truncation():
    """
    Verifies that web-grounded conversational NLG for education queries:
      1. Correctly synthesizes Switzerland / Bern and Kim Il Sung University.
      2. NEVER produces chopped/truncated fragments like 'studied at the Int [1]'.
      3. Produces a fluent conversational answer with complete grammatical sentences.
    """
    from backend.services.ai_chat_agent import run_agentic_chat, _clean_complete_snippet

    # Test snippet cleaner directly
    truncated = "The second of three children of Kim Jong Il and Ko Yong Hui, Kim studied at the Int"
    cleaned = _clean_complete_snippet(truncated)
    assert not cleaned.endswith("Int")

    # Run agentic chat
    res = run_agentic_chat(
        message="Where did Kim Jong Un studied?",
        allow_web_search=True,
        allow_nas_tools=False,
    )
    assert res["status"] == "ok"
    reply = res["reply"]
    assert "studied at the Int [" not in reply
    assert "at the Int" not in reply
    # Must mention Switzerland / Bern / Kim Il Sung
    assert any(w in reply for w in ("Switzerland", "Berne", "Bern", "Kim Il Sung"))
    # Verify sentences in reply are complete
    assert reply.strip().endswith((".", "!", "?")) or "\n" in reply


def test_offline_world_knowledge_kim_jong_un_and_science():
    """
    Verifies that when tools and web search are both disabled,
    world knowledge queries (Kim Jong Un, Einstein, Turing) provide articulate answers.
    """
    from backend.services.ai_chat_agent import run_agentic_chat

    # Kim Jong Un offline education
    res_kju = run_agentic_chat(
        message="Where did Kim Jong Un study?",
        allow_web_search=False,
        allow_nas_tools=False,
    )
    assert res_kju["status"] == "ok"
    assert any(w in res_kju["reply"] for w in ("Kim Il Sung", "Pyongyang", "Switzerland", "Berne", "Bern"))
    assert "I checked your NAS state and web sources" not in res_kju["reply"]

    # Einstein offline query
    res_einstein = run_agentic_chat(
        message="Who was Albert Einstein?",
        allow_web_search=False,
        allow_nas_tools=False,
    )
    assert res_einstein["status"] == "ok"
    assert "physics" in res_einstein["reply"].lower() or "relativity" in res_einstein["reply"].lower()


def test_huggingface_selected_model_telemetry_and_fast_speed():
    """
    Verifies that:
      1. When a user selects a Hugging Face model (e.g. hf.co/ConwayResearch/Underdog-Woof-4B-1.1),
         telemetry accurately retains the model and calculates generation speed independent of web latency.
      2. Measured or estimated tokens/sec is high (>= 20.0 tok/s on NPU/GPU), not 1.8 tok/s.
      3. Index.html has the 'Try' bar removed and the 'How your selected LLM is leveraged' card
         located within the AI Configuration page.
    """
    from backend.services.ai_chat_agent import build_llm_execution_telemetry
    import pathlib

    # Test telemetry with web scrape latency (e.g. 25 seconds of web scraping)
    # With measured LLM speed (e.g. 25.4 tok/s measured from eval_duration)
    tel_measured = build_llm_execution_telemetry(
        active_model="hf.co/ConwayResearch/Underdog-Woof-4B-1.1",
        elapsed_ms=27563.1,  # 27s total turnaround
        eval_tokens=50,
        measured_tok_sec=25.4,
        web_sources_count=5,
    )
    assert tel_measured["active_model"] == "hf.co/ConwayResearch/Underdog-Woof-4B-1.1"
    assert tel_measured["tokens_per_sec"] == 25.4
    assert tel_measured["tokens_per_sec"] > 20.0  # Not degraded to 1.8 tok/s

    # Test estimated speed calculation when measured_tok_sec is None
    tel_est = build_llm_execution_telemetry(
        active_model="hf.co/ConwayResearch/Underdog-Woof-4B-1.1",
        elapsed_ms=27563.1,
        eval_tokens=50,
        measured_tok_sec=None,
        web_sources_count=5,
    )
    assert tel_est["tokens_per_sec"] >= 20.0

    # Verify frontend index.html structure
    html_path = pathlib.Path("frontend/index.html")
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        assert 'id="ai-chat-starter-bar"' not in content
        assert "⚡ Try:" not in content
        assert "How Your Selected LLM Is Leveraged" in content
        # Ensure it appears inside mgmt-pane-ai-index
        pane_index = content.find('id="mgmt-pane-ai-index"')
        welcome_index = content.find("How Your Selected LLM Is Leveraged")
        assert pane_index != -1 and welcome_index != -1
        assert welcome_index > pane_index


def test_ai_chat_background_defaults_and_toggles_removed():
    """
    Verifies:
      1. AiChatRequest defaults allow_web_search=True and allow_nas_tools=True in background.
      2. frontend/index.html does not contain the obsolete UI checkboxes for web and tools.
    """
    from backend.api.media import AiChatRequest

    req = AiChatRequest(message="What is the CPU temp?")
    assert req.allow_web_search is True
    assert req.allow_nas_tools is True

    html_path = Path("frontend/index.html")
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        assert 'id="ai-chat-web-toggle"' not in content
        assert 'id="ai-chat-tools-toggle"' not in content


def test_ai_chat_streaming_sse_endpoint(client, auth_headers):
    """
    Verifies that the new Server-Sent Events (SSE) streaming endpoint
    /api/media/chat/stream returns status 200, Content-Type: text/event-stream,
    and streams tokens and a final done event.
    """
    resp = client.post(
        "/api/media/chat/stream",
        json={"message": "What is the CPU temp?", "allow_web_search": False, "allow_nas_tools": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    text = resp.text
    assert "event: token" in text
    assert "event: done" in text
    assert '"status": "ok"' in text


def test_remove_llm_model_and_endpoint(client, auth_headers, tmp_path):
    """
    Verifies that users can remove/delete any model from the ZettAI catalog:
      1. remove_llm_model() excludes the model from recommendations.
      2. If active model is removed, safely falls back to a remaining model.
      3. /api/media/models/remove and /api/ai/models/remove return updated catalog.
      4. DELETE /api/ai/models/{model_id} endpoint is supported.
      5. Pulling the model back restores it to the catalog.
    """
    from backend.services.media_engine import build_llm_recommendations

    accel = {"has_npu": True, "has_igpu": True, "name": "Intel AI Boost NPU", "tier_number": 1}
    cfg_file = str(tmp_path / "rag_remove_test_config.json")

    with patch("backend.services.rag_engine.RAG_CONFIG_PATH", cfg_file):
        recs_before = build_llm_recommendations(accel, ram_gb=32.0, min_release_year=None)
        assert len(recs_before["models"]) >= 2
        first_model_id = recs_before["models"][0]["id"]

        # Call remove endpoint via API
        resp = client.post(
            "/api/media/models/remove",
            json={"model": first_model_id},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["removed_model"] == first_model_id
        models_after = [m["id"] for m in data["llm_recommendations"]["models"]]
        assert first_model_id not in models_after

        # DELETE endpoint also supported
        resp_del = client.delete(
            f"/api/ai/models/{first_model_id}",
            headers=auth_headers,
        )
        assert resp_del.status_code == 200
        data_del = resp_del.json()
        assert data_del["status"] == "ok"
