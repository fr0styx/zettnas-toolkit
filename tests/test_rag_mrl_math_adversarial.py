"""Adversarial stress-testing suite for MRL dimension slicing & L2 normalization.

Empirically stress-tests mathematical invariants in `backend.services.rag_engine`:
  - `truncate_and_normalize_mrl`
  - `cosine_similarity_vec`

Examines extreme dimensions (768d, 512d, 256d, 128d, 64d, 1d, oversized),
extreme numerical scales (subnormals 1e-35, large 1e30, overflow 1e160, zeros, negatives),
unit L2 sphere guarantees (1.0 +/- 1e-5), orthogonality (0.0 +/- 1e-5),
and floating-point stability.
"""

import math
import os
import random
import sys
import pytest

# Ensure /app is in sys.path when executed directly as a script
if "/app" not in sys.path:
    sys.path.insert(0, "/app")
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from backend.services.rag_engine import (
    truncate_and_normalize_mrl,
    cosine_similarity_vec,
)


def _generate_random_unit_vector(dim: int, seed: int = 42) -> list[float]:
    """Generates a uniform random vector normalized to the unit sphere."""
    rng = random.Random(seed)
    raw = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


# ===========================================================================
# 1. Extreme Dimensions & Slicing Invariants
# ===========================================================================


@pytest.mark.parametrize("target_dim", [512, 256, 128, 64, 1])
def test_mrl_slicing_unit_vector_dimensions(target_dim: int):
    """Verifies that slicing a 768d unit vector preserves unit L2 norm (1.0 +/- 1e-5)."""
    vec_768 = _generate_random_unit_vector(768, seed=target_dim)
    sliced = truncate_and_normalize_mrl(vec_768, target_dim)

    assert len(sliced) == target_dim
    norm = math.sqrt(sum(x * x for x in sliced))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_mrl_slicing_full_dimension_unit_vector():
    """Verifies behavior when target_dim == len(vec) on an already unit-normalized vector."""
    vec_768 = _generate_random_unit_vector(768, seed=768)
    out = truncate_and_normalize_mrl(vec_768, 768)
    assert len(out) == 768
    norm = math.sqrt(sum(x * x for x in out))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_mrl_slicing_oversized_dimension_unit_vector():
    """Verifies behavior when target_dim > len(vec) on an already unit-normalized vector."""
    vec_768 = _generate_random_unit_vector(768, seed=1024)
    out = truncate_and_normalize_mrl(vec_768, 1024)
    assert len(out) == 768
    norm = math.sqrt(sum(x * x for x in out))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_mrl_unnormalized_input_at_full_or_oversized_dim():
    """Verifies if unnormalized input is normalized when target_dim >= len(vec)."""
    unnorm_vec = [2.0] * 768
    out = truncate_and_normalize_mrl(unnorm_vec, 768)
    norm = math.sqrt(sum(x * x for x in out))
    # Mathematical invariant: non-zero vector must normalize to 1.0 +/- 1e-5
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


# ===========================================================================
# 2. Extreme Numerical Scales (Subnormals, Overflow, Large Floats, Zeros)
# ===========================================================================


def test_mrl_all_zeros_input():
    """Verifies that all-zeros vector returns without NaN, Inf, or ZeroDivisionError."""
    zeros = [0.0] * 768
    out = truncate_and_normalize_mrl(zeros, 256)
    assert len(out) == 256
    assert all(x == 0.0 for x in out)
    assert not any(math.isnan(x) or math.isinf(x) for x in out)


def test_mrl_subnormal_floats_1e35():
    """Verifies unit L2 norm invariant for near-zero subnormal floats (1e-35)."""
    subnormal_vec = [1e-35] * 768
    out = truncate_and_normalize_mrl(subnormal_vec, 256)
    assert len(out) == 256
    norm = math.sqrt(sum(x * x for x in out))
    # Must equal 1.0 +/- 1e-5 for non-zero vector
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_mrl_large_floats_1e30():
    """Verifies that large floats (1e30) normalize cleanly to 1.0 without intermediate overflow."""
    large_vec = [1e30] * 768
    out = truncate_and_normalize_mrl(large_vec, 256)
    assert len(out) == 256
    assert not any(math.isnan(x) or math.isinf(x) for x in out)
    norm = math.sqrt(sum(x * x for x in out))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_mrl_intermediate_float_overflow_1e160():
    """Verifies that vectors with components near overflow limit (1e160) do not collapse to zero."""
    huge_vec = [1e160] * 768
    out = truncate_and_normalize_mrl(huge_vec, 256)
    assert len(out) == 256
    norm = math.sqrt(sum(x * x for x in out))
    # Intermediate x*x overflows to inf, resulting in x / inf = 0.0 (norm = 0.0)
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_mrl_negative_values():
    """Verifies that vectors with negative and alternating values normalize to unit sphere."""
    neg_vec = [-0.05] * 768
    out_neg = truncate_and_normalize_mrl(neg_vec, 256)
    norm_neg = math.sqrt(sum(x * x for x in out_neg))
    assert math.isclose(norm_neg, 1.0, rel_tol=1e-5)

    alt_vec = [(-1.0) ** i * 0.05 for i in range(768)]
    out_alt = truncate_and_normalize_mrl(alt_vec, 256)
    norm_alt = math.sqrt(sum(x * x for x in out_alt))
    assert math.isclose(norm_alt, 1.0, rel_tol=1e-5)


# ===========================================================================
# 3. Cosine Similarity Invariants (Identical, Orthogonal, Dimensional Mismatch)
# ===========================================================================


@pytest.mark.parametrize("dim", [512, 256, 128, 64, 1])
def test_cosine_similarity_identical_sliced_vectors(dim: int):
    """Verifies that cosine similarity between identical sliced unit vectors is 1.0 +/- 1e-5."""
    vec_768 = _generate_random_unit_vector(768, seed=dim * 7)
    sliced = truncate_and_normalize_mrl(vec_768, dim)
    sim = cosine_similarity_vec(sliced, sliced)
    assert math.isclose(sim, 1.0, rel_tol=1e-5)


@pytest.mark.parametrize("dim", [768, 512, 256, 128, 64, 2])
def test_cosine_similarity_orthogonal_canonical(dim: int):
    """Verifies that canonical orthogonal basis vectors evaluate to 0.0 +/- 1e-5."""
    e1 = [1.0] + [0.0] * (dim - 1)
    e2 = [0.0, 1.0] + [0.0] * (dim - 2)
    sim = cosine_similarity_vec(e1, e2)
    assert math.isclose(sim, 0.0, abs_tol=1e-5)


def test_cosine_similarity_dense_orthogonal():
    """Verifies that dense orthogonal vectors evaluate to 0.0 +/- 1e-5."""
    dim = 256
    v1 = [1.0] * dim
    v2 = [1.0 if i % 2 == 0 else -1.0 for i in range(dim)]
    norm1 = math.sqrt(sum(x * x for x in v1))
    norm2 = math.sqrt(sum(x * x for x in v2))
    u1 = [x / norm1 for x in v1]
    u2 = [x / norm2 for x in v2]
    sim = cosine_similarity_vec(u1, u2)
    assert math.isclose(sim, 0.0, abs_tol=1e-5)


def test_cosine_similarity_cross_dimensional_same_prefix():
    """Verifies that cross-dimensional vectors sharing identical normalized prefix evaluate to 1.0."""
    vec_768 = _generate_random_unit_vector(768, seed=99)
    v_512 = truncate_and_normalize_mrl(vec_768, 512)
    v_256 = truncate_and_normalize_mrl(vec_768, 256)
    v_128 = truncate_and_normalize_mrl(vec_768, 128)

    # Cross-dimension comparisons trigger MRL dynamic prefix truncation in cosine_similarity_vec
    assert math.isclose(cosine_similarity_vec(v_512, v_256), 1.0, rel_tol=1e-5)
    assert math.isclose(cosine_similarity_vec(v_512, v_128), 1.0, rel_tol=1e-5)
    assert math.isclose(cosine_similarity_vec(v_256, v_128), 1.0, rel_tol=1e-5)


def test_cosine_similarity_subnormal_identical_fails():
    """Verifies that identical subnormal vectors evaluate to 1.0 in cosine_similarity_vec."""
    subnormal_vec = [1e-35] * 768
    out = truncate_and_normalize_mrl(subnormal_vec, 256)
    sim = cosine_similarity_vec(out, out)
    assert math.isclose(sim, 1.0, rel_tol=1e-5)


def test_cosine_similarity_nan_poisoning_prevention():
    """Verifies that corrupted vectors containing NaN do not evaluate to 1.0 (perfect similarity)."""
    corrupted_vec = [float("nan")] * 256
    clean_vec = _generate_random_unit_vector(256, seed=123)

    sim_self = cosine_similarity_vec(corrupted_vec, corrupted_vec)
    sim_cross = cosine_similarity_vec(corrupted_vec, clean_vec)

    # A vector containing NaN must NEVER produce a valid 1.0 similarity match
    assert not math.isclose(sim_self, 1.0, rel_tol=1e-5)
    assert not math.isclose(sim_cross, 1.0, rel_tol=1e-5)


# ===========================================================================
# Standalone CLI Stress Harness Execution
# ===========================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("  EMPIRICAL ADVERSARIAL STRESS AUDIT: MRL SLICING & L2 NORMALIZATION")
    print("=" * 80)

    print("\n[Audit Pillar 1] Dimensional Truncation Invariants (Input: 768d unit vector)")
    print(f"{'Target Dim':12s} | {'Output Dim':12s} | {'Norm':12s} | {'Self Sim':12s} | {'Verdict'}")
    print("-" * 65)
    vec = _generate_random_unit_vector(768, seed=42)
    for d in [768, 512, 256, 128, 64, 1, 1024]:
        res = truncate_and_normalize_mrl(vec, d)
        n = math.sqrt(sum(x * x for x in res))
        sim = cosine_similarity_vec(res, res)
        passed = len(res) == min(d, 768) and math.isclose(n, 1.0, rel_tol=1e-5) and math.isclose(sim, 1.0, rel_tol=1e-5)
        verdict = "PASS" if passed else "FAIL"
        print(f"{d:12d} | {len(res):12d} | {n:12.6f} | {sim:12.6f} | {verdict}")

    print("\n[Audit Pillar 2] Numerical Edge Cases & Stress Inputs (Sliced to 256d)")
    print(f"{'Input Type':22s} | {'Norm':12s} | {'Self Sim':12s} | {'NaN/Inf':8s} | {'Invariant Verdict'}")
    print("-" * 75)
    cases = {
        "all zeros": ([0.0] * 768, "Zero vector (norm=0)"),
        "subnormal (1e-35)": ([1e-35] * 768, "Unit norm (1.0)"),
        "small (1e-15)": ([1e-15] * 768, "Unit norm (1.0)"),
        "large (1e30)": ([1e30] * 768, "Unit norm (1.0)"),
        "huge (1e160)": ([1e160] * 768, "Unit norm (1.0)"),
        "negative (-0.05)": ([-0.05] * 768, "Unit norm (1.0)"),
        "unnormalized (2.0)": ([2.0] * 768, "Unit norm (1.0)"),
    }
    for name, (v, expected_desc) in cases.items():
        res = truncate_and_normalize_mrl(v, 256)
        n = math.sqrt(sum(x * x for x in res))
        sim = cosine_similarity_vec(res, res)
        has_corrupt = any(math.isnan(x) or math.isinf(x) for x in res)

        if name == "all zeros":
            passed = n == 0.0 and sim == 0.0 and not has_corrupt
        else:
            passed = math.isclose(n, 1.0, rel_tol=1e-5) and math.isclose(sim, 1.0, rel_tol=1e-5) and not has_corrupt

        verdict = "PASS" if passed else "FAIL"
        print(f"{name:22s} | {n:12.4e} | {sim:12.4e} | {str(has_corrupt):8s} | {verdict:6s} ({expected_desc})")

    print("\n[Audit Pillar 3] Unnormalized Input at Full/Oversized Dim")
    v_raw = [2.0] * 768
    for d in [768, 1024]:
        res = truncate_and_normalize_mrl(v_raw, d)
        n = math.sqrt(sum(x * x for x in res))
        passed = math.isclose(n, 1.0, rel_tol=1e-5)
        print(
            f"  target_dim={d:4d} on unnormalized 768d: norm={n:10.4f} -> {'PASS' if passed else 'FAIL (remains unnormalized)'}"
        )

    print("\n[Audit Pillar 4] NaN Masking in Cosine Similarity")
    v_nan = [float("nan")] * 256
    v_clean = _generate_random_unit_vector(256)
    sim_nan_self = cosine_similarity_vec(v_nan, v_nan)
    sim_nan_clean = cosine_similarity_vec(v_nan, v_clean)
    pass_nan_self = not math.isclose(sim_nan_self, 1.0, rel_tol=1e-5)
    pass_nan_clean = not math.isclose(sim_nan_clean, 1.0, rel_tol=1e-5)
    print(
        f"  cosine_similarity(nan, nan)   = {sim_nan_self} -> {'PASS' if pass_nan_self else 'FAIL (returns 1.0 due to min(1.0, nan))'}"
    )
    print(
        f"  cosine_similarity(nan, clean) = {sim_nan_clean} -> {'PASS' if pass_nan_clean else 'FAIL (returns 1.0 due to min(1.0, nan))'}"
    )
    print("=" * 80)
