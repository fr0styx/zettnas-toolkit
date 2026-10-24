"""Model catalog helpers in backend/services/media_engine.py: Hugging Face dates, the
release-year filter, size and memory estimates, and embedding-only detection."""

import pytest

from backend.services.media_engine import (
    _estimate_hf_model_specs,
    _parse_hf_date,
    is_embedding_only_model,
    is_model_2026_or_newer,
)


def test_parse_hf_date():
    disp, ts, raw = _parse_hf_date("2026-10-08T09:12:10.000Z")
    assert disp == "Oct 08, 2026" and ts > 1.79e9 and raw == "2026-10-08T09:12:10.000Z"
    assert _parse_hf_date("2024-09-19")[0] == "Sep 19, 2024"
    assert _parse_hf_date("") == ("Recent", 0.0, "")
    assert _parse_hf_date("2025-13-99") == ("Dec 2025", 0.0, "2025-13-99")  # month clamped
    assert _parse_hf_date("yesterday") == ("Recent", 0.0, "yesterday")
    assert _parse_hf_date("not a date at all")[0] == "not a date"


@pytest.mark.parametrize(
    ("model", "new"),
    [
        ({"release_timestamp": 1790000000}, True),
        ({"release_timestamp": 1700000000}, False),
        ({"release_date": "2026-03-01"}, True),
        ({"created_at": "2025-12-31T23:59:59Z"}, False),
        ({"release_date_str": "Mar 01, 2027"}, True),
        ({"release_date_str": "Jun 04, 2024"}, False),
        ({"release_date_str": "Recent"}, True),
        # fractional seconds and times used to read as years (".201534" -> 2015)
        ({"created_at": "2026-10-08T09:12:10.201534Z"}, True),
        ({"createdAt": "2026-02-20T20:15:00Z"}, True),
        ({}, False),
    ],
)
def test_release_year_filter(model, new):
    assert is_model_2026_or_newer(model) is new


def test_size_estimates_from_names_and_tags():
    q = _estimate_hf_model_specs("Qwen/Qwen3-4B-Instruct-GGUF", tags=["gguf", "q4_k_m"])
    assert q["params_b"] == 4.0 and q["quantization"].startswith("INT4") and q["category"] == "npu_edge_llm"
    big = _estimate_hf_model_specs("mistralai/Mixtral-8x7B-Instruct")
    assert big["params_b"] == round(8 * 7 * 0.85, 1) and big["category"] == "high_capacity_llm"
    assert big["requires_dgpu_vram_gb"] > 12
    vl = _estimate_hf_model_specs("Qwen/Qwen2.5-VL-7B-Instruct")
    assert vl["params"] == "7B VL" and vl["category"] == "vision_multimodal" and vl["recommended_for_npu"] is True
    emb = _estimate_hf_model_specs("BAAI/bge-small-en", pipeline_tag="feature-extraction")
    assert emb["category"] == "embeddings_rag" and emb["est_ram_gb"] <= 1.0  # "small" used to make it 14B
    assert _estimate_hf_model_specs("sentence-transformers/all-MiniLM-L6-v2")["params_b"] == 0.4
    counted = _estimate_hf_model_specs("org/model", safetensors_total=12_300_000_000)
    assert counted["params_b"] == 12.3 and counted["category"] == "gpu_balanced_llm"
    assert counted["quantization"].startswith("FP16")
    tagged = _estimate_hf_model_specs("org/model", tags=["1.5b", "int8"])
    assert tagged["params_b"] == 1.5 and tagged["quantization"] == "INT8 / FP8"
    assert _estimate_hf_model_specs("org/phi-mini")["params_b"] == 3.8
    assert _estimate_hf_model_specs("org/thing")["params_b"] == 7.0


def test_two_bit_gguf_uses_the_real_file_size():
    spec = _estimate_hf_model_specs("org/Big-70B-IQ2_XS-GGUF", gguf_total=21 * 1024**3)
    assert spec["quantization"].startswith("IQ2") and spec["est_ram_gb"] == round(21 + 0.8, 1)
    assert _estimate_hf_model_specs("org/m-7b-q3_k_m")["quantization"].startswith("IQ3")


@pytest.mark.parametrize(
    ("model", "only_embeddings"),
    [
        ("nomic-embed-text", True),
        ("BAAI/bge-m3", True),
        ("embeddinggemma", True),
        ("intfloat/e5-mistral-7b-instruct", False),
        ("qwen3:4b", False),
        ({"pipeline_tag": "sentence-similarity"}, True),
        ({"capabilities": ["embedding"]}, True),
        ({"capabilities": ["embedding", "chat"], "id": "x"}, False),
        ({"id": "org/gte-base"}, True),
        (None, False),
    ],
)
def test_embedding_only_models(model, only_embeddings):
    assert is_embedding_only_model(model) is only_embeddings
