"""Fuzz and property-based tests for Bipolar VSA Vector Math."""

import numpy as np
from hypothesis import given, settings, strategies as st
from epires_core.vsa import BipolarVSA


@settings(max_examples=100)
@given(
    dim=st.integers(min_value=100, max_value=2000),
    key1=st.text(min_size=1, max_size=100),
    key2=st.text(min_size=1, max_size=100),
)
def test_fuzz_vsa_bind_exact_reversibility(dim: int, key1: str, key2: str):
    """Property: For any vectors a and b, bind(bind(a, b), b) == a."""
    vsa = BipolarVSA(dim=dim)
    a = vsa.generate_vector(key1)
    b = vsa.generate_vector(key2)

    bound = vsa.bind(a, b)
    assert bound.shape == (dim,)
    assert set(np.unique(bound)).issubset({-1, 1})

    unbound = vsa.bind(bound, b)
    assert np.array_equal(unbound, a)


@settings(max_examples=100)
@given(
    dim=st.integers(min_value=500, max_value=2000),
    num_vectors=st.integers(min_value=1, max_value=20),
    shifts=st.integers(min_value=-10, max_value=10),
)
def test_fuzz_vsa_bundle_and_permute(dim: int, num_vectors: int, shifts: int):
    """Property: Bundling any collection of vectors produces a valid bipolar vector."""
    vsa = BipolarVSA(dim=dim)
    vectors = [vsa.generate_vector(f"key_{i}") for i in range(num_vectors)]

    bundled = vsa.bundle(vectors)
    assert bundled.shape == (dim,)
    assert set(np.unique(bundled)).issubset({-1, 1})

    permuted = vsa.permute(bundled, shifts=shifts)
    assert permuted.shape == (dim,)
    assert set(np.unique(permuted)).issubset({-1, 1})


@settings(max_examples=100)
@given(
    dim=st.integers(min_value=100, max_value=2000),
    key_a=st.text(min_size=1, max_size=50),
    key_b=st.text(min_size=1, max_size=50),
)
def test_fuzz_vsa_similarity_bounds(dim: int, key_a: str, key_b: str):
    """Property: Cosine similarity is always bounded strictly in [-1.0, 1.0]."""
    vsa = BipolarVSA(dim=dim)
    va = vsa.generate_vector(key_a)
    vb = vsa.generate_vector(key_b)

    sim = vsa.similarity(va, vb)
    assert -1.000001 <= sim <= 1.000001

    # Identity self-similarity is always 1.0
    self_sim = vsa.similarity(va, va)
    assert abs(self_sim - 1.0) < 1e-5
