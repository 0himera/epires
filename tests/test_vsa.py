"""Tests for Bipolar Vector Symbolic Architecture (VSA)."""

import numpy as np
from epires_core.vsa import BipolarVSA


def test_vsa_vector_generation():
    vsa = BipolarVSA(dim=10000, seed=42)
    v1 = vsa.generate_vector("Model:CatBoost")
    v2 = vsa.generate_vector("Model:CatBoost")
    v3 = vsa.generate_vector("Model:LightGBM")

    # Bipolar values only
    assert set(np.unique(v1)).issubset({-1, 1})
    assert v1.shape == (10000,)
    assert v1.dtype == np.int8

    # Determinism by key
    assert np.array_equal(v1, v2)
    # Quasi-orthogonality between different keys
    sim = vsa.similarity(v1, v3)
    assert abs(sim) < 0.05, f"Expected near zero similarity, got {sim}"


def test_vsa_bind_reversibility():
    vsa = BipolarVSA(dim=10000)
    role = vsa.generate_vector("ROLE:model")
    filler = vsa.generate_vector("VAL:LightGBM")

    bound = vsa.bind(role, filler)

    # Bounded in {-1, 1}
    assert set(np.unique(bound)).issubset({-1, 1})

    # Binding is orthogonal to operands
    assert abs(vsa.similarity(bound, role)) < 0.05
    assert abs(vsa.similarity(bound, filler)) < 0.05

    # Exact reversibility: unbind by multiplying with role again
    unbound = vsa.bind(bound, role)
    assert np.array_equal(unbound, filler)


def test_vsa_permute_shifts():
    vsa = BipolarVSA(dim=10000)
    v = vsa.generate_vector("Entity:Source")
    perm1 = vsa.permute(v, shifts=1)
    perm2 = vsa.permute(v, shifts=2)

    assert perm1.shape == v.shape
    # Permuting breaks similarity
    assert abs(vsa.similarity(v, perm1)) < 0.05
    assert abs(vsa.similarity(perm1, perm2)) < 0.05


def test_vsa_bundle_majority():
    vsa = BipolarVSA(dim=10000)
    v1 = vsa.generate_vector("A")
    v2 = vsa.generate_vector("B")
    v3 = vsa.generate_vector("C")

    bundled = vsa.bundle([v1, v2, v3])
    assert bundled.shape == (10000,)
    assert set(np.unique(bundled)).issubset({-1, 1})

    # Bundled vector is positively correlated with all elements
    sim1 = vsa.similarity(bundled, v1)
    sim2 = vsa.similarity(bundled, v2)
    sim3 = vsa.similarity(bundled, v3)

    assert sim1 > 0.4
    assert sim2 > 0.4
    assert sim3 > 0.4
