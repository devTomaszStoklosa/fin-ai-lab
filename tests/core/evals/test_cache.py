from pathlib import Path

from fin_ai_lab.core.evals.cache import EvalCache, cache_key


def test_cache_key_is_stable_for_same_payload() -> None:
    payload = {"a": 1, "b": "x"}

    assert cache_key(payload) == cache_key(dict(payload))


def test_cache_key_differs_for_different_payload() -> None:
    assert cache_key({"a": 1}) != cache_key({"a": 2})


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = EvalCache(cache_dir=tmp_path)
    key = cache_key({"x": 1})

    assert cache.get("target", key) is None

    cache.set("target", key, {"output": {"sum": 5}})

    assert cache.get("target", key) == {"output": {"sum": 5}}


def test_cache_namespaces_do_not_collide(tmp_path: Path) -> None:
    cache = EvalCache(cache_dir=tmp_path)
    key = cache_key({"x": 1})

    cache.set("target", key, {"output": 1})
    cache.set("judge", key, {"output": 2})

    assert cache.get("target", key) == {"output": 1}
    assert cache.get("judge", key) == {"output": 2}
