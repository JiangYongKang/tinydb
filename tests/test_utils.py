import pytest

from tinydb.utils import LRUCache, freeze, FrozenDict


def test_lru_cache():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    _ = cache["a"]  # move to front in lru queue
    cache["d"] = 4  # move oldest item out of lru queue

    try:
        _ = cache['f']
    except KeyError:
        pass

    assert cache.lru == ["c", "a", "d"]


def test_lru_cache_set_multiple():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["a"] = 2
    cache["a"] = 3
    cache["a"] = 4

    assert cache.lru == ["a"]


def test_lru_cache_set_update():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["a"] = 2

    assert cache["a"] == 2


def test_lru_cache_get():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 1
    cache["c"] = 1
    cache.get("a")
    cache["d"] = 4

    assert cache.lru == ["c", "a", "d"]


def test_lru_cache_delete():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 2
    del cache["a"]

    try:
        del cache['f']
    except KeyError:
        pass

    assert cache.lru == ["b"]


def test_lru_cache_clear():
    cache = LRUCache(capacity=3)
    cache["a"] = 1
    cache["b"] = 2
    cache.clear()

    assert cache.lru == []


def test_lru_cache_unlimited():
    cache = LRUCache()
    for i in range(100):
        cache[i] = i

    assert len(cache.lru) == 100


def test_lru_cache_unlimited_explicit():
    cache = LRUCache(capacity=None)
    for i in range(100):
        cache[i] = i

    assert len(cache.lru) == 100


def test_lru_cache_iteration_works():
    cache = LRUCache()
    count = 0
    for _ in cache:
        assert False, 'there should be no elements in the cache'

    assert count == 0


def test_lru_cache_falsy_values_bug():
    """
    Test for GitHub issue #596: LRU cache should handle falsy values correctly.
    
    Bug: `if self.cache.get(key):` treated falsy values as non-existent keys,
    breaking LRU ordering when updating existing keys with falsy values.
    """
    cache = LRUCache(capacity=3)
    
    # Set up cache with falsy value
    cache["a"] = 0      # Falsy value
    cache["b"] = 1
    cache["c"] = 2

    assert cache.lru == ["a", "b", "c"]
    
    # Update existing key with falsy value - should move to end
    cache.set("a", 3)
    assert cache.lru == ["b", "c", "a"]
    
    # Add new item - should evict oldest ("b"), not "a"
    cache.set("d", 4)
    assert cache.lru == ["c", "a", "d"]
    assert "b" not in cache
    assert cache["a"] == 3


def test_lru_cache_none_value():
    """
    Test that LRU cache correctly handles None as a valid cached value.
    
    Bug: Using `value is None` to check for cache misses incorrectly treated
    None values as misses, causing:
    1. `__getitem__` raising KeyError when value is None
    2. `get` not updating LRU order when accessing a None value
    """
    cache = LRUCache(capacity=3)
    
    # Store None as a valid value
    cache["a"] = None
    cache["b"] = 1
    cache["c"] = 2
    
    # Check initial LRU order before any access
    assert cache.lru == ["a", "b", "c"]
    
    # Test __getitem__ with None value - should not raise KeyError
    assert cache["a"] is None
    
    # Test get with None value - should return None, not default
    assert cache.get("a") is None
    assert cache.get("a", default="default") is None
    
    # Test that accessing None value updates LRU order
    # After accessing "a" via __getitem__ and get, "a" should be at the end
    assert cache.lru == ["b", "c", "a"]
    
    # Access "b" - should move to end
    cache.get("b")
    assert cache.lru == ["c", "a", "b"]
    
    # Test that non-existent key still returns default
    assert cache.get("nonexistent") is None
    assert cache.get("nonexistent", default="default") == "default"
    
    # Test that non-existent key raises KeyError in __getitem__
    with pytest.raises(KeyError):
        _ = cache["nonexistent"]
    
    # Test eviction with None values
    cache["d"] = 3  # Should evict "c" (oldest)
    assert cache.lru == ["a", "b", "d"]
    assert "c" not in cache
    assert cache["a"] is None  # None value still accessible

def test_freeze():
    frozen = freeze([0, 1, 2, {'a': [1, 2, 3]}, {1, 2}])
    assert isinstance(frozen, tuple)
    assert isinstance(frozen[3], FrozenDict)
    assert isinstance(frozen[3]['a'], tuple)
    assert isinstance(frozen[4], frozenset)

    with pytest.raises(TypeError):
        frozen[0] = 10

    with pytest.raises(TypeError):
        frozen[3]['a'] = 10

    with pytest.raises(TypeError):
        frozen[3].pop('a')

    with pytest.raises(TypeError):
        frozen[3].update({'a': 9})
