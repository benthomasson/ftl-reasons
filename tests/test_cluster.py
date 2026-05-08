"""Tests for semantic clustering in derive pipeline.

Tests are skipped when sentence-transformers/scikit-learn are not installed.
Install with: pip install 'ftl-reasons[cluster]'
"""

import pytest

try:
    from reasons_lib.cluster import (
        cluster_beliefs, ClusterCache, _require_cluster_deps, HAS_CLUSTER_DEPS,
    )
except ImportError:
    HAS_CLUSTER_DEPS = False

skip_no_cluster = pytest.mark.skipif(
    not HAS_CLUSTER_DEPS,
    reason="sentence-transformers and scikit-learn not installed"
)


def test_require_cluster_deps_message():
    """Error message mentions install command when deps missing."""
    if HAS_CLUSTER_DEPS:
        pytest.skip("deps are installed, can't test missing-dep path")
    from reasons_lib.cluster import _require_cluster_deps
    with pytest.raises(ImportError, match="ftl-reasons\\[cluster\\]"):
        _require_cluster_deps()


@skip_no_cluster
def test_cluster_beliefs_under_budget():
    beliefs = {f"b-{i}": f"Belief number {i}" for i in range(5)}
    selected, stats = cluster_beliefs(beliefs, budget=10, seed=42)
    assert set(selected) == set(beliefs.keys())
    assert stats["n_clusters"] == 1


@skip_no_cluster
def test_cluster_beliefs_selects_budget():
    beliefs = {f"b-{i}": f"Belief about topic {i} with some text" for i in range(50)}
    selected, stats = cluster_beliefs(beliefs, budget=20, seed=42)
    assert len(selected) == 20
    assert stats["n_clusters"] >= 2


@skip_no_cluster
def test_cluster_beliefs_reproducible():
    beliefs = {f"b-{i}": f"Belief about topic {i}" for i in range(50)}
    sel1, _ = cluster_beliefs(beliefs, budget=20, seed=42)
    sel2, _ = cluster_beliefs(beliefs, budget=20, seed=42)
    assert sel1 == sel2


@skip_no_cluster
def test_cluster_beliefs_cross_domain():
    auth_beliefs = {f"auth-{i}": f"Authentication and login security check {i}"
                    for i in range(25)}
    db_beliefs = {f"db-{i}": f"Database query performance and indexing {i}"
                  for i in range(25)}
    beliefs = {**auth_beliefs, **db_beliefs}
    selected, stats = cluster_beliefs(beliefs, budget=20, seed=42)
    has_auth = any(k.startswith("auth-") for k in selected)
    has_db = any(k.startswith("db-") for k in selected)
    assert has_auth and has_db, (
        f"Expected beliefs from both domains, got: {selected}"
    )


@skip_no_cluster
def test_cluster_cache_reuse():
    beliefs = {f"b-{i}": f"Belief number {i}" for i in range(20)}
    cache = ClusterCache()
    ids1, emb1 = cache.embed(beliefs)
    initial_cache_size = len(cache._cache)
    ids2, emb2 = cache.embed(beliefs)
    assert len(cache._cache) == initial_cache_size
    assert ids1 == ids2


@skip_no_cluster
def test_cluster_cache_incremental():
    beliefs1 = {f"b-{i}": f"Belief number {i}" for i in range(10)}
    cache = ClusterCache()
    cache.embed(beliefs1)
    size_after_first = len(cache._cache)

    beliefs2 = {**beliefs1, **{f"new-{i}": f"New belief {i}" for i in range(5)}}
    cache.embed(beliefs2)
    assert len(cache._cache) == size_after_first + 5


@skip_no_cluster
def test_cluster_stats_shape():
    beliefs = {f"b-{i}": f"Belief about topic {i}" for i in range(30)}
    _, stats = cluster_beliefs(beliefs, budget=15, seed=42)
    assert "n_clusters" in stats
    assert "cluster_sizes" in stats
    assert "embedding_model" in stats
    assert isinstance(stats["cluster_sizes"], list)
    assert sum(stats["cluster_sizes"]) == 30


@skip_no_cluster
def test_cluster_n_clusters_override():
    beliefs = {f"b-{i}": f"Belief about topic {i}" for i in range(50)}
    _, stats = cluster_beliefs(beliefs, budget=20, seed=42, n_clusters=5)
    assert stats["n_clusters"] == 5
