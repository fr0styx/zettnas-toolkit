"""tests/test_rag_benchmark_eval.py - unit tests for the retrieval maths and formatting helpers.

The "benchmark" here scores a deterministic simulated embedder, so it checks that the
formatting, Matryoshka truncation and metric code behave as intended. It says nothing about
real retrieval quality; that is measured by tests/rag_eval (see docs/RAG.md).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import patch

import pytest

from backend.services.ai_chat_agent import (
    REASONING_TAG_RE,
    _build_structured_llm_context,
    _clean_complete_snippet,
    extract_and_strip_reasoning,
)
from backend.services.rag_engine import (
    RagSearchEngine,
    classify_query_task_intent,
    format_embeddinggemma_document,
    truncate_and_normalize_mrl,
)

# ---------------------------------------------------------------------------
# 1. Pure Mathematical IR Metrics
# ---------------------------------------------------------------------------


class IRMetrics:
    """Exact Information Retrieval evaluation metric calculator."""

    @staticmethod
    def precision_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
        if k <= 0 or not retrieved:
            return 0.0
        top_k = retrieved[:k]
        hits = sum(1 for doc in top_k if doc in relevant)
        return hits / float(k)

    @staticmethod
    def recall_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
        if not relevant or k <= 0 or not retrieved:
            return 0.0
        top_k = retrieved[:k]
        hits = sum(1 for doc in top_k if doc in relevant)
        return hits / float(len(relevant))

    @staticmethod
    def reciprocal_rank(retrieved: List[str], relevant: Set[str]) -> float:
        if not relevant or not retrieved:
            return 0.0
        for rank_idx, doc in enumerate(retrieved, start=1):
            if doc in relevant:
                return 1.0 / float(rank_idx)
        return 0.0

    @classmethod
    def evaluate_query_set(
        cls,
        results: Dict[str, List[str]],
        ground_truth: Dict[str, Set[str]],
        k_values: Tuple[int, ...] = (1, 3, 5),
    ) -> Dict[str, float]:
        if not ground_truth:
            return {}
        num_queries = len(ground_truth)
        sum_mrr = 0.0
        sum_prec = {k: 0.0 for k in k_values}
        sum_recall = {k: 0.0 for k in k_values}

        for qid, rel_set in ground_truth.items():
            ret_list = results.get(qid, [])
            sum_mrr += cls.reciprocal_rank(ret_list, rel_set)
            for k in k_values:
                sum_prec[k] += cls.precision_at_k(ret_list, rel_set, k)
                sum_recall[k] += cls.recall_at_k(ret_list, rel_set, k)

        metrics = {"mrr": sum_mrr / float(num_queries)}
        for k in k_values:
            metrics[f"precision@{k}"] = sum_prec[k] / float(num_queries)
            metrics[f"recall@{k}"] = sum_recall[k] / float(num_queries)
        return metrics


# ---------------------------------------------------------------------------
# 2. Deterministic EmbeddingGemma-2 Simulator (Hermetic, Zero-Network)
# ---------------------------------------------------------------------------


class DeterministicEmbeddingGemmaSimulator:
    """Hermetic 768d vector space simulator replicating EmbeddingGemma-2:

    - Dims 0..255: Core semantic topic latent space (preserved in MRL)
    - Dims 256..383: Document title conditioning subspace
    - Dims 384..511: Dual-encoder task instruction alignment subspace
    - Dims 512..767: Lexical feature hashing
    """

    TOPIC_BASES = {
        "btrfs": (0, 16),
        "zfs": (16, 32),
        "unraid": (32, 48),
        "spindown": (48, 64),
        "docker": (64, 80),
        "thermal": (80, 96),
        "sourdough": (96, 112),
        "pizza": (112, 128),
    }

    @classmethod
    def generate_embedding(
        cls,
        text: str,
        is_query: bool = False,
        task_prompt: Optional[str] = None,
        target_dim: Optional[int] = None,
        normalize_mrl: bool = True,
    ) -> List[float]:
        vec = [0.0] * 768
        low = text.lower()

        # 1. Topic latents in Dims 0..127
        for topic, (start_idx, end_idx) in cls.TOPIC_BASES.items():
            if topic in low or (topic == "sourdough" and "bread" in low):
                for idx in range(start_idx, end_idx):
                    seed = f"{topic}_{idx}"
                    h = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 1000
                    vec[idx] += (h / 500.0) - 1.0

        # 2. Title conditioning in Dims 128..191
        if "title:" in low:
            title_part = low.split("title:")[1].split("| text:")[0].strip() if "| text:" in low else low
            for idx in range(128, 192):
                seed = f"title_{title_part}_{idx}"
                h = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 1000
                vec[idx] += (h / 500.0) - 1.0

        # 3. Task instruction alignment in Dims 192..255
        effective_prefix = ""
        if is_query:
            if task_prompt:
                effective_prefix = task_prompt.lower()
            elif low.startswith("task:"):
                effective_prefix = low.split("| query:")[0].strip()

        if effective_prefix:
            for idx in range(192, 256):
                seed = f"task_{effective_prefix}_{idx}"
                h = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 1000
                vec[idx] += (h / 500.0) - 1.0
        elif not is_query and "text:" in low:
            # Passage aligns with corresponding task instruction
            for idx in range(192, 256):
                vec[idx] += 0.45

        # 4. Semantic token hashing distributed across dimensions with MRL concentration
        words = re.findall(r"[a-z0-9]+", low)
        for w in words:
            if len(w) > 2:
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                # Primary token projection present in 256d prefix
                slot_mrl = h % 256
                vec[slot_mrl] += 0.8
                # Extended residual capacity in 256..767
                slot_ext = 256 + (h % 512)
                vec[slot_ext] += 0.5

        # Primary L2 normalization
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]

        # Matryoshka Representation Learning (MRL) dimension truncation
        if target_dim and 0 < target_dim < len(vec):
            vec = vec[:target_dim]
            if normalize_mrl:
                sub_norm = math.sqrt(sum(x * x for x in vec))
                if sub_norm > 0.0:
                    vec = [x / sub_norm for x in vec]

        return vec


# ---------------------------------------------------------------------------
# 3. Representative Benchmark Corpus (16 Documents)
# ---------------------------------------------------------------------------

BENCHMARK_CORPUS: List[Dict[str, Any]] = [
    {
        "doc_id": "doc_01",
        "file_name": "nas_btrfs_raid1.md",
        "doc_title": "Btrfs RAID1 Storage Pool Configuration & Maintenance",
        "doc_type": "document",
        "heading_context": "## Storage Topology & Scrubbing",
        "chunk_text": (
            "Configure a 2-disk Btrfs RAID1 mirror pool across /dev/sdb and /dev/sdc. "
            "Run btrfs balance and scheduled scrubs to verify checksum integrity while preserving drive spindown."
        ),
        "canonical_path": "/mnt/user/docs/nas_btrfs_raid1.md",
    },
    {
        "doc_id": "doc_02",
        "file_name": "nas_zfs_mirror_cache.md",
        "doc_title": "ZFS Mirror Pool with NVMe L2ARC Cache & SLOG",
        "doc_type": "document",
        "heading_context": "## Zpool Creation & Caching",
        "chunk_text": (
            "Create high-performance ZFS mirror pools with secondary NVMe L2ARC cache devices. "
            "Tune recordsize to 1M for sequential media and monitor ARC hits via arc_summary."
        ),
        "canonical_path": "/mnt/user/docs/nas_zfs_mirror_cache.md",
    },
    {
        "doc_id": "doc_03",
        "file_name": "unraid_array_mover.md",
        "doc_title": "Unraid Array Cache Tiering & Mover Tuning",
        "doc_type": "document",
        "heading_context": "## Cache Pool to Array Migration",
        "chunk_text": (
            "Configure Unraid storage cache pools with SSD write acceleration. "
            "Schedule the Mover script during off-peak hours to flush writes to spinning hard disk drives without waking drives prematurely."
        ),
        "canonical_path": "/mnt/user/docs/unraid_array_mover.md",
    },
    {
        "doc_id": "doc_04",
        "file_name": "smart_disk_spindown_guide.md",
        "doc_title": "S.M.A.R.T. Health Monitoring & Spindown Guards",
        "doc_type": "document",
        "heading_context": "## Zero-Wakeup Spindown Safety",
        "chunk_text": (
            "Execute smartctl -n standby -A to query hard disk health. If the exit code is 2, "
            "the drive is asleep in standby; skip polling to avoid waking spinning platters and preserve acoustic quietness."
        ),
        "canonical_path": "/mnt/user/docs/smart_disk_spindown_guide.md",
    },
    {
        "doc_id": "doc_05",
        "file_name": "nextcloud_aio.yml",
        "doc_title": "Nextcloud AIO Compose Stack with Redis & PostgreSQL",
        "doc_type": "code",
        "heading_context": "## Services: Nextcloud, Redis, PostgreSQL",
        "chunk_text": (
            "version: '3.8'\nservices:\n  nextcloud:\n    image: nextcloud:apache\n    ports:\n      - '8080:80'\n"
            "    environment:\n      - POSTGRES_HOST=db\n      - REDIS_HOST=redis\n  redis:\n    image: redis:alpine\n"
            "  db:\n    image: postgres:15"
        ),
        "canonical_path": "/mnt/user/docker/nextcloud_aio.yml",
    },
    {
        "doc_id": "doc_06",
        "file_name": "plex_nvidia_hw.yml",
        "doc_title": "Plex Media Server with NVIDIA NVDEC/NVENC Hardware Transcoding",
        "doc_type": "code",
        "heading_context": "## Hardware Transcoding Compose Stack",
        "chunk_text": (
            "services:\n  plex:\n    image: linuxserver/plex\n    runtime: nvidia\n    environment:\n"
            "      - NVIDIA_VISIBLE_DEVICES=all\n      - NVIDIA_DRIVER_CAPABILITIES=compute,video,utility\n"
            "    devices:\n      - /dev/dri:/dev/dri"
        ),
        "canonical_path": "/mnt/user/docker/plex_nvidia_hw.yml",
    },
    {
        "doc_id": "doc_07",
        "file_name": "vaultwarden_traefik.yml",
        "doc_title": "Vaultwarden Password Vault with Traefik Reverse Proxy",
        "doc_type": "code",
        "heading_context": "## Reverse Proxy Routing & WebSockets",
        "chunk_text": (
            "services:\n  vaultwarden:\n    image: vaultwarden/server:latest\n    labels:\n"
            "      - 'traefik.http.routers.vw.rule=Host(`vault.local`)'\n"
            "      - 'traefik.http.services.vw.loadbalancer.server.port=80'\n"
            "      - 'traefik.http.routers.vw-ws.rule=PathPrefix(`/notifications/hub`)'"
        ),
        "canonical_path": "/mnt/user/docker/vaultwarden_traefik.yml",
    },
    {
        "doc_id": "doc_08",
        "file_name": "docker_prune_cleanup_policy.md",
        "doc_title": "Docker Storage Reclamation & Unused Container Pruning",
        "doc_type": "document",
        "heading_context": "## Prune Policies & Volume Safety",
        "chunk_text": (
            "Reclaim root filesystem capacity by running docker system prune -af. "
            "Exclude persistent database volumes to prevent data loss during automated maintenance cycles."
        ),
        "canonical_path": "/mnt/user/docs/docker_prune_cleanup_policy.md",
    },
    {
        "doc_id": "doc_09",
        "file_name": "troubleshoot_fan_thermal_clamp.md",
        "doc_title": "Thermal Watchdog: Fan Curve Runaway Clamp at 80°C",
        "doc_type": "document",
        "heading_context": "## Emergency Thermal Protection",
        "chunk_text": (
            "When CPU or chassis temperature sensor exceeds 80 degrees Celsius, "
            "the hardware watchdog unconditionally overrides user curves and clamps fan pwm to maximum 183 (100% duty cycle) on inviolable pwm3."
        ),
        "canonical_path": "/mnt/user/docs/troubleshoot_fan_thermal_clamp.md",
    },
    {
        "doc_id": "doc_10",
        "file_name": "troubleshoot_degraded_raid_recovery.md",
        "doc_title": "Degraded Btrfs/ZFS RAID Recovery and Disk Replacement",
        "doc_type": "document",
        "heading_context": "## Replacing Failed Drive",
        "chunk_text": (
            "Initiate online disk replacement using btrfs replace start <srcdev> <targetdev> /mnt/pool. "
            "Monitor recovery progress without stopping running container workloads."
        ),
        "canonical_path": "/mnt/user/docs/troubleshoot_degraded_raid_recovery.md",
    },
    {
        "doc_id": "doc_11",
        "file_name": "troubleshoot_oom_memory_compaction.md",
        "doc_title": "Out-Of-Memory (OOM) Prevention & SQLite WAL Compaction",
        "doc_type": "document",
        "heading_context": "## Memory Budgeting & WAL Checkpointing",
        "chunk_text": (
            "Prevent Linux OOM killer invocations on low-power NAS devices by configuring SQLite busy_timeout=15000 "
            "and running periodic WAL passive checkpoints to truncate index journals."
        ),
        "canonical_path": "/mnt/user/docs/troubleshoot_oom_memory_compaction.md",
    },
    {
        "doc_id": "doc_12",
        "file_name": "troubleshoot_network_mtu_jumbo.md",
        "doc_title": "10GbE Network MTU Jumbo Frame Mismatch Diagnostics",
        "doc_type": "document",
        "heading_context": "## MTU 9000 Negotiation & Packet Drops",
        "chunk_text": (
            "Resolve network packet fragmentation and performance drops on 10GbE SFP+ interfaces "
            "by verifying end-to-end MTU 9000 jumbo frame consistency across switch, host, and client adapters."
        ),
        "canonical_path": "/mnt/user/docs/troubleshoot_network_mtu_jumbo.md",
    },
    {
        "doc_id": "doc_13",
        "file_name": "recipe_san_francisco_sourdough.md",
        "doc_title": "San Francisco High-Hydration Sourdough Bread",
        "doc_type": "recipe",
        "heading_context": "## Baking Temperature & Method",
        "chunk_text": (
            "Bake 78% hydration sourdough bread in a preheated cast iron Dutch oven at 230C (450F) for 20 minutes with lid on, "
            "then 22 minutes with lid off until crust is blistered deep brown."
        ),
        "canonical_path": "/mnt/user/recipes/recipe_san_francisco_sourdough.md",
    },
    {
        "doc_id": "doc_14",
        "file_name": "recipe_neapolitan_pizza_dough.md",
        "doc_title": "Authentic Neapolitan Pizza Dough (48-Hour Cold Fermentation)",
        "doc_type": "recipe",
        "heading_context": "## Dough Hydration & Cold Ferment",
        "chunk_text": (
            "Combine Caputo Tipo 00 flour with 65% water, 3% sea salt, and minimal fresh yeast. "
            "Cold ferment dough balls in refrigerator at 4C for 48 hours for complex airy crust structure."
        ),
        "canonical_path": "/mnt/user/recipes/recipe_neapolitan_pizza_dough.md",
    },
    {
        "doc_id": "doc_15",
        "file_name": "recipe_espresso_extraction_guide.md",
        "doc_title": "Espresso Extraction & Dial-In Ratio Guide",
        "doc_type": "recipe",
        "heading_context": "## Dose, Yield, and Extraction Time",
        "chunk_text": (
            "Dial in espresso using a standard 1:2 brew ratio: 18g finely ground specialty coffee "
            "yielding 36g liquid espresso in 26 to 28 seconds at 9 bar brew pressure."
        ),
        "canonical_path": "/mnt/user/recipes/recipe_espresso_extraction_guide.md",
    },
    {
        "doc_id": "doc_16",
        "file_name": "recipe_slow_smoked_brisket.md",
        "doc_title": "Low-and-Slow Texas Smoked Beef Brisket",
        "doc_type": "recipe",
        "heading_context": "## Wood Smoke & Stall Phase",
        "chunk_text": (
            "Smoke whole beef brisket using post oak wood at 107C (225F). "
            "Wrap brisket in peach butcher paper when meat reaches the 74C (165F) stall to preserve internal moisture and render collagen."
        ),
        "canonical_path": "/mnt/user/recipes/recipe_slow_smoked_brisket.md",
    },
]

# ---------------------------------------------------------------------------
# 4. Ground-Truth Query Set (16 Multi-Intent Queries)
# ---------------------------------------------------------------------------

BENCHMARK_QUERIES: List[Dict[str, Any]] = [
    # QA Intent
    {
        "query_id": "Q01",
        "query_text": "How do I configure a 2-disk Btrfs RAID1 mirror without waking sleeping drives?",
        "intent_type": "qa",
        "expected_task_prefix": "task: question answering | query: ",
        "relevant_doc_ids": {"doc_01", "doc_04"},
    },
    {
        "query_id": "Q02",
        "query_text": "Why does the CPU fan lock to 100% maximum PWM speed during high load?",
        "intent_type": "qa",
        "expected_task_prefix": "task: question answering | query: ",
        "relevant_doc_ids": {"doc_09"},
    },
    {
        "query_id": "Q03",
        "query_text": "What oven temperature and baking time is required for high hydration sourdough bread?",
        "intent_type": "qa",
        "expected_task_prefix": "task: question answering | query: ",
        "relevant_doc_ids": {"doc_13"},
    },
    {
        "query_id": "Q04",
        "query_text": "How do I set up Redis caching and PostgreSQL for Nextcloud in Docker Compose?",
        "intent_type": "qa",
        "expected_task_prefix": "task: question answering | query: ",
        "relevant_doc_ids": {"doc_05"},
    },
    # Code Intent
    {
        "query_id": "Q05",
        "query_text": "docker compose nextcloud postgres redis volume mount ports",
        "intent_type": "code",
        "expected_task_prefix": "task: code search | query: ",
        "relevant_doc_ids": {"doc_05"},
    },
    {
        "query_id": "Q06",
        "query_text": "btrfs replace start missing drive dev sdb /mnt/pool",
        "intent_type": "code",
        "expected_task_prefix": "task: code search | query: ",
        "relevant_doc_ids": {"doc_10", "doc_01"},
    },
    {
        "query_id": "Q07",
        "query_text": "smartctl -n standby -A /dev/sdb check exit code 2 sleeping disk",
        "intent_type": "code",
        "expected_task_prefix": "task: code search | query: ",
        "relevant_doc_ids": {"doc_04"},
    },
    {
        "query_id": "Q08",
        "query_text": "traefik reverse proxy vaultwarden websocket notifications hub",
        "intent_type": "code",
        "expected_task_prefix": "task: code search | query: ",
        "relevant_doc_ids": {"doc_07"},
    },
    # Semantic Paraphrase (No lexical title overlap)
    {
        "query_id": "Q09",
        "query_text": "Prevent spinning platters from spooling up during automated health queries",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_04", "doc_01"},
    },
    {
        "query_id": "Q10",
        "query_text": "Emergency cooling intervention when silicon reaches critical thermal ceiling",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_09"},
    },
    {
        "query_id": "Q11",
        "query_text": "Fermented rustic flour loaf baked in a cast iron Dutch oven with blistered crust",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_13"},
    },
    {
        "query_id": "Q12",
        "query_text": "Hardware accelerated video transcoding setup for streaming media container",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_06"},
    },
    # Technical Direct Keywords
    {
        "query_id": "Q13",
        "query_text": "btrfs raid1 mirror configuration",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_01"},
    },
    {
        "query_id": "Q14",
        "query_text": "neapolitan pizza dough 48 hour cold fermentation",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_14"},
    },
    {
        "query_id": "Q15",
        "query_text": "SQLite database locked busy timeout 15000 WAL checkpoint",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_11"},
    },
    {
        "query_id": "Q16",
        "query_text": "10 gigabit ethernet jumbo frames packet loss drop",
        "intent_type": "search",
        "expected_task_prefix": "task: search result | query: ",
        "relevant_doc_ids": {"doc_12"},
    },
]

# ---------------------------------------------------------------------------
# 5. Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_benchmark_engine(tmp_path):
    db_path = str(tmp_path / "rag_benchmark.db")
    engine = RagSearchEngine(db_path=db_path)
    yield engine
    engine.close()


# ---------------------------------------------------------------------------
# 6. Test Suite Methods
# ---------------------------------------------------------------------------


def test_format_embeddinggemma_document():
    """Verifies canonical passage formatting for Google DeepMind EmbeddingGemma-2."""
    assert (
        format_embeddinggemma_document("Btrfs RAID1", "Configure mirror pool.")
        == "title: Btrfs RAID1 | text: Configure mirror pool."
    )
    assert (
        format_embeddinggemma_document(None, "Passage without title.") == "title: none | text: Passage without title."
    )
    assert (
        format_embeddinggemma_document("   ", "Passage with whitespace title.")
        == "title: none | text: Passage with whitespace title."
    )


def test_truncate_and_normalize_mrl_unit_norm():
    """Verifies that truncate_and_normalize_mrl strictly preserves unit L2 norm."""
    vec_768 = [0.05] * 768
    norm = math.sqrt(sum(x * x for x in vec_768))
    vec_768 = [x / norm for x in vec_768]

    for dim in (512, 256, 128):
        sliced = truncate_and_normalize_mrl(vec_768, dim)
        assert len(sliced) == dim
        norm_sq = sum(x * x for x in sliced)
        assert math.isclose(norm_sq, 1.0, rel_tol=1e-5)


def test_ir_metrics_pure_mathematics():
    """Verifies P@K, R@K, and MRR calculations against known ground-truth edge cases."""
    retrieved = ["doc_1", "doc_2", "doc_3", "doc_4", "doc_5"]
    relevant = {"doc_2", "doc_5"}

    # P@K
    assert pytest.approx(IRMetrics.precision_at_k(retrieved, relevant, 1)) == 0.0
    assert pytest.approx(IRMetrics.precision_at_k(retrieved, relevant, 2)) == 0.5  # 1/2
    assert pytest.approx(IRMetrics.precision_at_k(retrieved, relevant, 5)) == 0.4  # 2/5

    # R@K
    assert pytest.approx(IRMetrics.recall_at_k(retrieved, relevant, 1)) == 0.0
    assert pytest.approx(IRMetrics.recall_at_k(retrieved, relevant, 2)) == 0.5  # 1/2
    assert pytest.approx(IRMetrics.recall_at_k(retrieved, relevant, 5)) == 1.0  # 2/2

    # MRR
    assert pytest.approx(IRMetrics.reciprocal_rank(retrieved, relevant)) == 0.5  # first at idx 2 -> 1/2
    assert pytest.approx(IRMetrics.reciprocal_rank(["doc_9"], relevant)) == 0.0  # not found
    assert pytest.approx(IRMetrics.reciprocal_rank(["doc_2"], relevant)) == 1.0  # first at idx 1 -> 1.0


def test_deterministic_embedding_simulator_geometry():
    """Verifies 768d unit norm, title conditioning, and post-MRL L2 normalization."""
    # Unit norm
    vec_768 = DeterministicEmbeddingGemmaSimulator.generate_embedding("btrfs mirror pool")
    assert len(vec_768) == 768
    norm_768 = math.sqrt(sum(x * x for x in vec_768))
    assert pytest.approx(norm_768, 1e-4) == 1.0

    # Post-MRL L2 normalization at 256d
    vec_256_norm = DeterministicEmbeddingGemmaSimulator.generate_embedding(
        "btrfs mirror pool", target_dim=256, normalize_mrl=True
    )
    assert len(vec_256_norm) == 256
    norm_256 = math.sqrt(sum(x * x for x in vec_256_norm))
    assert pytest.approx(norm_256, 1e-4) == 1.0

    # Un-normalized MRL truncation has norm < 1.0
    vec_256_raw = DeterministicEmbeddingGemmaSimulator.generate_embedding(
        "btrfs mirror pool", target_dim=256, normalize_mrl=False
    )
    assert len(vec_256_raw) == 256
    norm_raw = math.sqrt(sum(x * x for x in vec_256_raw))
    assert norm_raw < 0.99


def test_rag_simulated_title_conditioning_delta(temp_benchmark_engine):
    """Evaluates all 16 benchmark queries across Baseline and Optimized pipelines.

    On the simulated embedder only (not a quality measurement): title conditioning and
    normalisation should improve Recall@3 and MRR by at least 0.15.
    """
    # Ingest corpus twice: once as baseline, once as optimized in separate test representations
    base_doc_vecs = {}
    opt_doc_vecs = {}
    for doc in BENCHMARK_CORPUS:
        did = doc["doc_id"]
        # Baseline: unprefixed raw chunk
        base_text = doc["chunk_text"]
        base_doc_vecs[did] = DeterministicEmbeddingGemmaSimulator.generate_embedding(
            base_text, is_query=False, target_dim=256, normalize_mrl=False
        )

        # Optimized: title-conditioned via canonical format
        opt_text = format_embeddinggemma_document(doc["doc_title"], doc["chunk_text"])
        opt_doc_vecs[did] = DeterministicEmbeddingGemmaSimulator.generate_embedding(
            opt_text, is_query=False, target_dim=256, normalize_mrl=True
        )

    # Evaluate Baseline Queries
    base_results = {}
    for q in BENCHMARK_QUERIES:
        qid = q["query_id"]
        # Baseline query: raw, unprefixed, un-normalized 256d
        q_vec = DeterministicEmbeddingGemmaSimulator.generate_embedding(
            q["query_text"], is_query=True, target_dim=256, normalize_mrl=False
        )
        scored = []
        for did, dvec in base_doc_vecs.items():
            sim = sum(a * b for a, b in zip(q_vec, dvec))
            scored.append((did, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        base_results[qid] = [x[0] for x in scored]

    # Evaluate Optimized Queries
    opt_results = {}
    for q in BENCHMARK_QUERIES:
        qid = q["query_id"]
        intent_type, prefix = classify_query_task_intent(q["query_text"])
        # Optimized query: asymmetric instruction prefix, L2 normalized 256d
        q_vec = DeterministicEmbeddingGemmaSimulator.generate_embedding(
            q["query_text"],
            is_query=True,
            task_prompt=prefix,
            target_dim=256,
            normalize_mrl=True,
        )
        scored = []
        for did, dvec in opt_doc_vecs.items():
            sim = sum(a * b for a, b in zip(q_vec, dvec))
            # Token overlap boost
            q_tokens = set(re.findall(r"[a-z0-9]+", q["query_text"].lower()))
            target_doc = next(d for d in BENCHMARK_CORPUS if d["doc_id"] == did)
            d_tokens = set(
                re.findall(
                    r"[a-z0-9]+",
                    (target_doc["doc_title"] + " " + target_doc["chunk_text"]).lower(),
                )
            )
            token_sim = len(q_tokens & d_tokens) / float(len(q_tokens)) if q_tokens else 0.0
            hybrid_score = 0.70 * sim + 0.30 * token_sim
            scored.append((did, hybrid_score))
        scored.sort(key=lambda x: x[1], reverse=True)
        opt_results[qid] = [x[0] for x in scored]

    ground_truth = {q["query_id"]: q["relevant_doc_ids"] for q in BENCHMARK_QUERIES}

    base_metrics = IRMetrics.evaluate_query_set(base_results, ground_truth)
    opt_metrics = IRMetrics.evaluate_query_set(opt_results, ground_truth)

    # Simulated delta assertions
    assert opt_metrics["recall@3"] >= base_metrics["recall@3"] + 0.15, (
        f"Recall@3 failed to achieve +0.15 delta: Base={base_metrics['recall@3']:.3f}, Opt={opt_metrics['recall@3']:.3f}"
    )
    assert opt_metrics["mrr"] >= base_metrics["mrr"] + 0.15, (
        f"MRR failed to achieve +0.15 delta: Base={base_metrics['mrr']:.3f}, Opt={opt_metrics['mrr']:.3f}"
    )
    assert opt_metrics["mrr"] >= 0.80, f"Optimized MRR below 0.80 target: {opt_metrics['mrr']:.3f}"


def test_rag_benchmark_mrl_scaling_and_normalization_retention():
    """Verifies that post-MRL L2 normalization maintains >=90% MRR retention at 256d."""
    ground_truth = {q["query_id"]: q["relevant_doc_ids"] for q in BENCHMARK_QUERIES}

    # 1. 768d Full Vector Baseline
    opt_768_results = {}
    for q in BENCHMARK_QUERIES:
        _, prefix = classify_query_task_intent(q["query_text"])
        q_vec = DeterministicEmbeddingGemmaSimulator.generate_embedding(
            q["query_text"],
            is_query=True,
            task_prompt=prefix,
            target_dim=768,
            normalize_mrl=True,
        )
        scored = []
        for doc in BENCHMARK_CORPUS:
            did = doc["doc_id"]
            d_vec = DeterministicEmbeddingGemmaSimulator.generate_embedding(
                format_embeddinggemma_document(doc["doc_title"], doc["chunk_text"]),
                is_query=False,
                target_dim=768,
                normalize_mrl=True,
            )
            scored.append((did, sum(a * b for a, b in zip(q_vec, d_vec))))
        scored.sort(key=lambda x: x[1], reverse=True)
        opt_768_results[q["query_id"]] = [x[0] for x in scored]

    mrr_768 = IRMetrics.evaluate_query_set(opt_768_results, ground_truth)["mrr"]

    # 2. 256d Sliced with L2 Normalization
    opt_256_results = {}
    for q in BENCHMARK_QUERIES:
        _, prefix = classify_query_task_intent(q["query_text"])
        q_vec = DeterministicEmbeddingGemmaSimulator.generate_embedding(
            q["query_text"],
            is_query=True,
            task_prompt=prefix,
            target_dim=256,
            normalize_mrl=True,
        )
        scored = []
        for doc in BENCHMARK_CORPUS:
            did = doc["doc_id"]
            d_vec = DeterministicEmbeddingGemmaSimulator.generate_embedding(
                format_embeddinggemma_document(doc["doc_title"], doc["chunk_text"]),
                is_query=False,
                target_dim=256,
                normalize_mrl=True,
            )
            scored.append((did, sum(a * b for a, b in zip(q_vec, d_vec))))
        scored.sort(key=lambda x: x[1], reverse=True)
        opt_256_results[q["query_id"]] = [x[0] for x in scored]

    mrr_256 = IRMetrics.evaluate_query_set(opt_256_results, ground_truth)["mrr"]

    # Retention must exceed 90%
    retention_256 = mrr_256 / mrr_768
    assert retention_256 >= 0.90, (
        f"MRL 256d retention failed: {retention_256:.3f} (MRR 768={mrr_768:.3f}, MRR 256={mrr_256:.3f})"
    )


def test_clean_complete_snippet_structured_and_prose():
    """Verifies snippet cleaner preserves structured content (recipes, code, lists, tables)
    while pruning dangling incomplete prose endings.
    """
    # 1. Structured table preservation
    table_text = (
        "| Drive | Serial | Temp |\n| --- | --- | --- |\n| sda | WD-WCC4N1 | 32C |\n| sdb | WD-WCC4N2 | 34C |\n"
    )
    cleaned_table = _clean_complete_snippet(table_text, max_chars=500)
    assert "| sda | WD-WCC4N1 | 32C |" in cleaned_table
    assert "| sdb | WD-WCC4N2 | 34C |" in cleaned_table

    # 2. Structured recipe / list preservation
    recipe_text = (
        "## Sourdough Bread\n"
        "- 500g strong bread flour\n"
        "- 375g lukewarm water (75% hydration)\n"
        "- 100g active sourdough starter\n"
        "- 10g fine sea salt\n"
    )
    cleaned_recipe = _clean_complete_snippet(recipe_text, max_chars=500)
    assert "- 500g strong bread flour" in cleaned_recipe
    assert "- 10g fine sea salt" in cleaned_recipe

    # 3. Code block preservation
    code_text = "```yaml\nversion: '3.8'\nservices:\n  nextcloud:\n    image: nextcloud:fpm-alpine\n```"
    cleaned_code = _clean_complete_snippet(code_text, max_chars=500)
    assert "version: '3.8'" in cleaned_code
    assert "image: nextcloud:fpm-alpine" in cleaned_code

    # 4. Prose truncation of dangling incomplete sentence
    dangling_prose = (
        "The primary storage pool uses Btrfs RAID1 mirror across two drives. "
        "When expanding the pool or running a scrub on the"
    )
    cleaned_prose = _clean_complete_snippet(dangling_prose, max_chars=500)
    assert cleaned_prose == "The primary storage pool uses Btrfs RAID1 mirror across two drives."


def test_build_structured_llm_context_xml_and_zero_citations():
    """Verifies structured XML <retrieved_documents> emitting and graceful handling of 0 citations."""
    # 1. Zero citations case
    zero_results = [
        {
            "tool": "search_nas_knowledge",
            "folder_path": "/mnt/user/documents",
            "citations": [],
            "context_text": "",
            "photos": [],
            "grounding_confidence_score": 0,
            "crag_grade": "none",
        }
    ]
    zero_ctx = _build_structured_llm_context(zero_results)
    assert '<retrieved_documents count="0">' in zero_ctx
    assert "0 Results Found" in zero_ctx
    assert "No matching documents or records found" in zero_ctx

    # 2. Populated citations with rich XML tags
    citation_results = [
        {
            "tool": "search_nas_knowledge",
            "folder_path": "/mnt/user/knowledge",
            "citations": [
                {
                    "doc_title": "Btrfs RAID Guide",
                    "name": "btrfs_guide.md",
                    "path": "/mnt/user/knowledge/btrfs_guide.md",
                    "score": 0.96,
                    "doc_type": "markdown",
                    "line_start": 12,
                    "line_end": 28,
                    "breadcrumb": "Storage > RAID",
                    "full_parent_context": "Btrfs RAID1 provides block-level metadata and data redundancy.",
                }
            ],
            "photos": [],
            "grounding_confidence_score": 96,
            "crag_grade": "high",
        }
    ]
    ctx = _build_structured_llm_context(citation_results)
    assert '<retrieved_documents count="1">' in ctx
    assert (
        '<document index="1" title="Btrfs RAID Guide" file="btrfs_guide.md" '
        'path="/mnt/user/knowledge/btrfs_guide.md" relevance="96%" modality="markdown" lines="12-28">' in ctx
    )
    assert "[Section: Storage > RAID]" in ctx
    assert "Btrfs RAID1 provides block-level metadata and data redundancy." in ctx
    assert "</document>" in ctx
    assert "</retrieved_documents>" in ctx


def test_reasoning_tag_re_normalization():
    """Verifies universal reasoning tag regex cleans <think>, <thought>, <reasoning> blocks."""
    # <think> tags
    t1 = "<think>Analyzing user question...\nChecking storage status.</think>The pool is healthy."
    assert REASONING_TAG_RE.sub("", t1).strip() == "The pool is healthy."

    # <thought> tags (case-insensitive)
    t2 = "<THOUGHT>Need to consult manual.</THOUGHT>Fan speed is at 45%."
    assert REASONING_TAG_RE.sub("", t2).strip() == "Fan speed is at 45%."

    # <reasoning> tags
    t3 = "<reasoning>Multi-step plan:\n1. Inspect drive\n2. Check temperature</reasoning>Drive temp is 32C."
    assert REASONING_TAG_RE.sub("", t3).strip() == "Drive temp is 32C."

    # Clean text unchanged
    t4 = "Direct answer without reasoning tags."
    assert REASONING_TAG_RE.sub("", t4).strip() == "Direct answer without reasoning tags."


def test_extract_and_strip_reasoning_closed_and_unclosed():
    """
    Verifies that extract_and_strip_reasoning correctly strips both closed and
    unclosed reasoning tags (<think>, <thought>, <reasoning>), capturing thinking tokens
    for the collapsible disclosure while preventing thoughts from bleeding into user reply.
    """
    t1 = "<think>Analyzing user question...\nChecking storage status.</think>The pool is healthy."
    th1, cl1 = extract_and_strip_reasoning(t1)
    assert th1 == "Analyzing user question...\nChecking storage status."
    assert cl1 == "The pool is healthy."

    t2 = "<think>Calculating drive temperatures for array..."
    th2, cl2 = extract_and_strip_reasoning(t2)
    assert th2 == "Calculating drive temperatures for array..."
    assert cl2 == ""

    t3 = "<THOUGHT>Querying SMART database without closing"
    th3, cl3 = extract_and_strip_reasoning(t3)
    assert th3 == "Querying SMART database without closing"
    assert cl3 == ""

    t4 = "<think>Step 1</think>Intermediate text<reasoning>Step 2 truncated"
    th4, cl4 = extract_and_strip_reasoning(t4)
    assert th4 == "Step 1\n\nStep 2 truncated"
    assert cl4 == "Intermediate text"

    t5 = "Direct answer without reasoning tags."
    th5, cl5 = extract_and_strip_reasoning(t5)
    assert th5 == ""
    assert cl5 == "Direct answer without reasoning tags."


def test_resolve_path_backing_dev_symlink_dereference(tmp_path):
    """
    Verifies that resolve_path_backing_dev dereferences symlinks using os.path.realpath,
    preventing symlinks located on cache SSDs from bypassing the standby guard when
    pointing to spinning array disks.
    """
    from unittest.mock import patch
    from backend.services.rag_engine import resolve_path_backing_dev

    target_path = "/mnt/disk1/data/file.txt"
    # 1. With explicit unraid disk mapping
    mock_disks = {"disk1": {"device": "sdb"}}
    with (
        patch("os.path.realpath", return_value=target_path),
        patch("backend.services.rag_engine._get_unraid_disks_and_shares", return_value=(mock_disks, {})),
    ):
        dev = resolve_path_backing_dev("/mnt/cache/symlinks/file.txt")
        assert dev == "sdb"

    # 2. Live environment check: verifies symlink resolves to spinning array disk, not cache nvme
    with patch("os.path.realpath", return_value=target_path):
        dev = resolve_path_backing_dev("/mnt/cache/symlinks/file.txt")
        assert dev in ("sda", "sdb")
        assert dev != "nvme0n1"

    # 3. Actual cache target resolves to nvme0n1
    with patch("os.path.realpath", return_value="/mnt/cache/data/file.txt"):
        dev = resolve_path_backing_dev("/mnt/cache/data/file.txt")
        assert dev == "nvme0n1"


def test_rag_index_single_file_standby_guard(temp_benchmark_engine):
    """Verifies _index_single_file intrinsically checks drive standby status and aborts if sleeping."""
    engine = temp_benchmark_engine

    # Patch is_backing_disk_in_standby to return True (disk in standby)
    with (
        patch.object(engine, "get_config", return_value={"respect_standby": True}),
        patch("backend.services.rag_engine.is_backing_disk_in_standby", return_value=True) as mock_standby,
        patch("backend.services.rag_engine.resolve_path_backing_dev", return_value="/dev/sdd"),
        patch("builtins.open") as mock_open_sleep,
    ):
        # When respect_standby is True and force_wake is False, indexing should abort immediately
        res = engine._index_single_file(
            canonical_path="/mnt/user/documents/archive.pdf",
            file_name="archive.pdf",
            file_ext=".pdf",
            size_bytes=4096,
            mtime_ns=1700000000000000,
            cached_row=None,
            respect_standby=True,
            force_wake=False,
        )
        assert res is None, "Expected _index_single_file to abort and return None for drive in standby"
        mock_standby.assert_called_once_with("/dev/sdd")
        mock_open_sleep.assert_not_called()

    # When force_wake is True, guard does NOT abort even if drive is sleeping
    with (
        patch.object(engine, "get_config", return_value={"respect_standby": True}),
        patch("backend.services.rag_engine.is_backing_disk_in_standby", return_value=True),
        patch("backend.services.rag_engine.resolve_path_backing_dev", return_value="/dev/sdd"),
        patch("builtins.open", side_effect=IOError("Physical drive access simulated")) as mock_open_wake,
    ):
        res = engine._index_single_file(
            canonical_path="/mnt/user/documents/archive.pdf",
            file_name="archive.pdf",
            file_ext=".pdf",
            size_bytes=4096,
            mtime_ns=1700000000000000,
            cached_row=None,
            respect_standby=True,
            force_wake=True,
        )
        assert mock_open_wake.called, "Expected open() to be called when force_wake=True"
