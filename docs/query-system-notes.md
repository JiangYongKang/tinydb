# TinyDB 查询系统学习笔记

## 一、核心架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        查询执行与缓存流程                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. 构建查询条件                                                   │
│     Query().name == 'Alice'                                      │
│         ↓                                                         │
│     QueryInstance(_test=lambda, _hash=('==', ('name',), 'Alice'))│
│                                                                   │
│  2. Table.search(cond)                                            │
│     ┌─────────────────────────────────────────────────────────┐  │
│     │  ① 检查缓存: _query_cache.get(cond)                      │  │
│     │     ├─ 命中 → 直接返回缓存结果                             │  │
│     │     └─ 未命中 → 继续执行                                   │  │
│     │                                                           │  │
│     │  ② 遍历所有文档: cond(doc) → True/False                   │  │
│     │     收集匹配的文档                                          │  │
│     │                                                           │  │
│     │  ③ 检查 is_cacheable()                                     │  │
│     │     ├─ True  → 写入缓存: _query_cache[cond] = docs       │  │
│     │     └─ False → 跳过缓存                                    │  │
│     │                                                           │  │
│     │  ④ 返回结果                                                │  │
│     └─────────────────────────────────────────────────────────┘  │
│                                                                   │
│  3. 写入操作 (insert/update/remove/truncate)                      │
│         ↓                                                         │
│     _update_table() → clear_cache() → 缓存失效                   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、为何 `QueryInstance` 需要稳定的 `__hash__`

### 2.1 根本原因：字典作为缓存键

在 [table.py:113-114](../tinydb/table.py#L113-L114) 中：

```python
self._query_cache: LRUCache[QueryLike, List[Document]] \
    = self.query_cache_class(capacity=cache_size)
```

`_query_cache` 是一个 `LRUCache`（本质是 `OrderedDict`），**查询对象本身作为字典的键**。

Python 字典要求键必须：
1. **可哈希**（实现 `__hash__`）
2. **可比较**（实现 `__eq__`）
3. **哈希稳定**（相同对象的 `__hash__` 返回值不变）

### 2.2 `QueryInstance` 的哈希实现

在 [queries.py:88-92](../tinydb/queries.py#L88-L92)：

```python
def __hash__(self) -> int:
    # We calculate the query hash by using the ``hashval`` object which
    # describes this query uniquely, so we can calculate a stable hash
    # value by simply hashing it
    return hash(self._hash)
```

`QueryInstance` 内部维护 `_hash` 属性（一个元组），哈希值由这个元组计算而来。

### 2.3 为何需要"稳定"？

**场景示例**：

```python
# 第一次查询
cond1 = Query().name == 'Alice'
table.search(cond1)  # 缓存键: hash(cond1)

# 第二次查询（语义相同，但对象不同）
cond2 = Query().name == 'Alice'
table.search(cond2)  # 期望命中缓存！
```

如果 `cond1` 和 `cond2` 的 `__hash__` 返回不同的值，第二次查询就无法命中缓存。

**稳定哈希的定义**：
> 两个语义等价的查询对象，必须有相同的 `__hash__` 返回值，且 `__eq__` 返回 `True`。

在 [queries.py:97-101](../tinydb/queries.py#L97-L101)：

```python
def __eq__(self, other: object):
    if isinstance(other, QueryInstance):
        return self._hash == other._hash  # 比较 _hash 元组
    return False
```

---

## 三、`__and__` / `__or__` 为何用 `frozenset` 参与哈希

### 3.1 源码分析

在 [queries.py:105-123](../tinydb/queries.py#L105-L123)：

```python
def __and__(self, other: 'QueryInstance') -> 'QueryInstance':
    # We use a frozenset for the hash as the AND operation is commutative
    # (a & b == b & a) and the frozenset does not consider the order of
    # elements
    if self.is_cacheable() and other.is_cacheable():
        hashval = ('and', frozenset([self._hash, other._hash]))
    else:
        hashval = None
    return QueryInstance(lambda value: self(value) and other(value), hashval)

def __or__(self, other: 'QueryInstance') -> 'QueryInstance':
    # We use a frozenset for the hash as the OR operation is commutative
    # (a | b == b | a) and the frozenset does not consider the order of
    # elements
    if self.is_cacheable() and other.is_cacheable():
        hashval = ('or', frozenset([self._hash, other._hash]))
    else:
        hashval = None
    return QueryInstance(lambda value: self(value) or other(value), hashval)
```

### 3.2 核心原因：逻辑运算的交换律

**逻辑与（AND）和逻辑或（OR）满足交换律**：
- `a & b` 语义等价于 `b & a`
- `a | b` 语义等价于 `b | a`

如果使用普通 `list` 或 `tuple`，顺序会影响哈希：

```python
# 假设用 tuple 而不是 frozenset
hashval1 = ('and', (hash_a, hash_b))
hashval2 = ('and', (hash_b, hash_a))
# hash(hashval1) != hash(hashval2) ← 问题！
```

**`frozenset` 的特性**：
1. 元素无序（顺序不影响相等性和哈希）
2. 不可变（可哈希）
3. 相同元素的 `frozenset` 相等且哈希相同

```python
frozenset([a, b]) == frozenset([b, a])  # True
hash(frozenset([a, b])) == hash(frozenset([b, a]))  # True
```

### 3.3 对比：`__invert__` 不需要 `frozenset`

在 [queries.py:125-127](../tinydb/queries.py#L125-L127)：

```python
def __invert__(self) -> 'QueryInstance':
    hashval = ('not', self._hash) if self.is_cacheable() else None
    return QueryInstance(lambda value: not self(value), hashval)
```

**原因**：逻辑非（NOT）是一元运算符，没有交换律问题。`~a` 只有一种写法，不需要考虑顺序。

---

## 四、`freeze` 函数在哈希中的作用

### 4.1 问题：可变类型不可哈希

Python 中：
- `list`、`dict`、`set` 是可变的 → **不可哈希**
- `tuple`、`str`、`int`、`frozenset` 是不可变的 → **可哈希**

查询条件中可能包含可变类型：

```python
Query().tags == ['python', 'database']  # list 不可哈希
Query().info == {'level': 'admin'}      # dict 不可哈希
```

### 4.2 `freeze` 的实现

在 [utils.py:144-159](../tinydb/utils.py#L144-L159)：

```python
def freeze(obj):
    """
    Freeze an object by making it immutable and thus hashable.
    """
    if isinstance(obj, dict):
        # Transform dicts into ``FrozenDict``s
        return FrozenDict((k, freeze(v)) for k, v in obj.items())
    elif isinstance(obj, list):
        # Transform lists into tuples
        return tuple(freeze(el) for el in obj)
    elif isinstance(obj, set):
        # Transform sets into ``frozenset``s
        return frozenset(obj)
    else:
        # Don't handle all other objects
        return obj
```

**转换规则**：
| 原始类型 | 冻结后类型 |
|---------|-----------|
| `dict` | `FrozenDict`（自定义不可变字典） |
| `list` | `tuple` |
| `set` | `frozenset` |
| 其他 | 保持不变 |

### 4.3 `FrozenDict` 的实现

在 [utils.py:114-142](../tinydb/utils.py#L114-L142)：

```python
class FrozenDict(dict):
    """
    An immutable dictionary.
    """
    def __hash__(self):
        # Calculate the has by hashing a tuple of all dict items
        return hash(tuple(sorted(self.items())))
    
    # 禁用所有修改操作
    __setitem__ = _immutable
    __delitem__ = _immutable
    # ...
```

### 4.4 在查询中的使用

在 [queries.py:243-254](../tinydb/queries.py#L243-L254)：

```python
def __eq__(self, rhs: Any):
    return self._generate_test(
        lambda value: value == rhs,
        ('==', self._path, freeze(rhs))  # 冻结比较值
    )
```

**示例**：

```python
cond = Query().tags == ['python', 'database']
# _hash = ('==', ('tags',), ('python', 'database'))  # list → tuple

cond2 = Query().info == {'level': 'admin'}
# _hash = ('==', ('info',), FrozenDict({'level': 'admin'}))  # dict → FrozenDict
```

---

## 五、`Table.search` 如何决定缓存

### 5.1 完整流程

在 [table.py:241-283](../tinydb/table.py#L241-L283)：

```python
def search(self, cond: QueryLike) -> List[Document]:
    # 步骤1: 检查缓存
    cached_results = self._query_cache.get(cond)
    if cached_results is not None:
        return cached_results[:]  # 返回副本，防止外部修改
    
    # 步骤2: 执行查询
    docs = [
        self.document_class(doc, self.document_id_class(doc_id))
        for doc_id, doc in self._read_table().items()
        if cond(doc)  # 调用 QueryInstance.__call__
    ]
    
    # 步骤3: 决定是否缓存
    # 使用 getattr 处理可选的 is_cacheable 方法
    is_cacheable: Callable[[], bool] = getattr(cond, 'is_cacheable',
                                               lambda: True)
    if is_cacheable():
        self._query_cache[cond] = docs[:]  # 存入副本
    
    return docs
```

### 5.2 `getattr` 舞蹈的原因

注释解释得很清楚 [table.py:266-277](../tinydb/table.py#L266-L277)：

```python
# This weird `getattr` dance is needed to make MyPy happy as
# it doesn't know that a query might have a `is_cacheable` method
# that is not declared in the `QueryLike` protocol due to it being
# optional.
#
# Note also that by default we expect custom query objects to be
# cacheable (which means they need to have a stable hash value).
# This is to keep consistency with TinyDB's behavior before
# `is_cacheable` was introduced which assumed that all queries
# are cacheable.
```

**关键点**：
1. `QueryLike` Protocol 只声明了 `__call__` 和 `__hash__`
2. `is_cacheable` 是**可选**方法
3. **默认假设可缓存**（向后兼容）

### 5.3 `QueryInstance.is_cacheable` 的实现

在 [queries.py:76-77](../tinydb/queries.py#L76-L77)：

```python
def is_cacheable(self) -> bool:
    return self._hash is not None
```

**规则**：`_hash` 不为 `None` 即可缓存。

---

## 六、写入数据后缓存为何必须失效

### 6.1 缓存失效的触发点

在 [table.py:763-813](../tinydb/table.py#L763-L813) 的 `_update_table` 方法：

```python
def _update_table(self, updater: Callable[[Dict[int, Mapping]], None]):
    # ... 读取并修改数据 ...
    
    # Write the newly updated data back to the storage
    self._storage.write(tables)
    
    # Clear the query cache, as the table contents have changed
    self.clear_cache()  # ← 关键！
```

**所有写入操作都经过 `_update_table`**：
- `insert` / `insert_multiple`
- `update` / `update_multiple` / `upsert`
- `remove` / `truncate`

### 6.2 为何必须失效？

**缓存的基本假设**：
> 相同查询条件 + 相同数据 = 相同结果

当数据变化时，这个假设不成立：

```python
# 初始数据: [{'name': 'Alice', 'age': 25}]
cond = Query().age > 20
table.search(cond)  # 结果: [Alice]，缓存此结果

# 插入新数据
table.insert({'name': 'Bob', 'age': 30})

# 如果缓存不失效...
table.search(cond)  # 期望: [Alice, Bob]
                     # 实际（如果用缓存）: [Alice] ← 错误！
```

### 6.3 为何是"全量清除"而非"增量更新"？

TinyDB 选择简单策略：**任何写入都清除整个缓存**。

**原因**：
1. **实现简单**：不需要追踪哪个查询受哪条数据影响
2. **TinyDB 定位**：轻量级嵌入式数据库，数据量通常不大
3. **LRU 缓存**：即使不清空，旧条目也会被淘汰

**对比**：如果要增量更新，需要：
- 记录每个查询匹配了哪些文档
- 写入时判断是否影响这些文档
- 复杂度大幅提升

---

## 七、可缓存 vs 不可缓存查询

### 7.1 判断标准

| 特征 | 可缓存查询 | 不可缓存查询 |
|-----|-----------|-------------|
| `_hash` | 非 `None` | `None` |
| `is_cacheable()` | `True` | `False` |
| 确定性 | 相同输入永远返回相同结果 | 结果可能随时间/外部状态变化 |
| 示例 | `Query().name == 'Alice'` | 使用 `map()` 的查询 |

### 7.2 可缓存查询示例

```python
# 简单比较
cond1 = Query().name == 'Alice'
# _hash = ('==', ('name',), 'Alice')

# 逻辑组合
cond2 = (Query().age > 18) & (Query().active == True)
# _hash = ('and', frozenset([
#     ('>', ('age',), 18),
#     ('==', ('active',), True)
# ]))

# 嵌套路径
cond3 = Query().profile.address.city == 'Beijing'
# _hash = ('==', ('profile', 'address', 'city'), 'Beijing')

# 包含列表/字典（会被 freeze）
cond4 = Query().tags == ['python', 'db']
# _hash = ('==', ('tags',), ('python', 'db'))  # list → tuple
```

### 7.3 不可缓存查询示例

**使用 `map()` 方法**（[queries.py:500-514](../tinydb/queries.py#L500-L514)）：

```python
def map(self, fn: Callable[[Any], Any]) -> 'Query':
    query = type(self)()
    query._path = self._path + (fn,)
    
    # ... and kill the hash - callable objects can be mutable, 
    # so it's harmful to cache their results.
    query._hash = None  # ← 关键！
    
    return query
```

**示例**：

```python
# 使用 lambda 转换值
cond = Query().price.map(lambda x: x * 1.1) > 100
# _hash = None → is_cacheable() = False

# 每次创建的 lambda 都是不同对象
cond1 = Query().price.map(lambda x: x * 1.1) > 100
cond2 = Query().price.map(lambda x: x * 1.1) > 100
# cond1.__eq__(cond2) 返回 False（lambda 对象不同，_hash 均为 None）
# 即使缓存也无法命中，不如不缓存
```

**其他不可缓存场景**：
- 调用外部 API 的自定义查询
- 依赖当前时间的查询
- 使用随机数的查询

---

## 八、自定义查询对象的 `is_cacheable` 实现

### 8.1 问题场景

假设你想创建一个自定义查询对象，但无法提供稳定的 `__hash__`：

```python
class ExternalApiQuery:
    """调用外部 API 进行验证的查询"""
    
    def __init__(self, api_url: str):
        self.api_url = api_url
        # API 响应可能随时间变化，无法稳定哈希
    
    def __call__(self, doc: Mapping) -> bool:
        # 调用外部 API 验证
        response = requests.get(f"{self.api_url}/verify/{doc['id']}")
        return response.json()['valid']
    
    def __hash__(self) -> int:
        # 问题：如何实现？
        # - 如果 hash(self.api_url)：API 响应可能变，缓存会过期
        # - 如果随机值：无法命中缓存
        return hash(self.api_url)  # 这是"谎言"！
```

### 8.2 正确实现：`is_cacheable()` 返回 `False`

```python
class ExternalApiQuery:
    def __init__(self, api_url: str):
        self.api_url = api_url
    
    def __call__(self, doc: Mapping) -> bool:
        response = requests.get(f"{self.api_url}/verify/{doc['id']}")
        return response.json()['valid']
    
    def __hash__(self) -> int:
        # 即使实现了 __hash__...
        return hash(self.api_url)
    
    def is_cacheable(self) -> bool:
        # 关键：明确告诉 TinyDB 不要缓存
        return False
```

### 8.3 后果分析

| 情况 | 后果 |
|-----|------|
| **正确实现**：`is_cacheable() → False` | 每次查询都重新执行，结果永远正确 |
| **错误实现**：`is_cacheable() → True` 但结果不确定 | 缓存可能返回过期数据，导致 bug |
| **未实现 `is_cacheable`** | 默认 `True`，同上风险 |
| **未实现 `__hash__`** | 无法作为字典键，运行时 `TypeError` |

### 8.4 设计权衡

**不可缓存的代价**：
- 每次查询都要遍历所有文档
- 性能较差

**不可缓存的收益**：
- 结果永远正确
- 避免缓存过期导致的 bug

**何时选择不可缓存**：
1. 查询结果依赖外部状态（API、时间、随机数）
2. 查询函数可能被修改（闭包捕获的变量变化）
3. 无法保证"相同输入 → 相同输出"

---

## 九、关键源码路径总结

| 功能 | 文件位置 | 关键代码 |
|-----|---------|---------|
| 查询哈希 | `queries.py:88-92` | `__hash__` 返回 `hash(self._hash)` |
| 相等比较 | `queries.py:97-101` | `__eq__` 比较 `self._hash` |
| AND 组合 | `queries.py:105-113` | 使用 `frozenset` 保证交换律 |
| OR 组合 | `queries.py:115-123` | 使用 `frozenset` 保证交换律 |
| NOT 组合 | `queries.py:125-127` | 直接使用 `tuple` |
| 可缓存判断 | `queries.py:76-77` | `is_cacheable()` 返回 `self._hash is not None` |
| 冻结函数 | `utils.py:144-159` | `freeze()` 转换可变类型 |
| 搜索缓存 | `table.py:241-283` | `search()` 检查和写入缓存 |
| 缓存失效 | `table.py:812-813` | `_update_table()` 调用 `clear_cache()` |
| map 不可缓存 | `queries.py:512` | `query._hash = None` |

---

## 十、核心设计思想

### 10.1 查询 = 可调用对象 + 稳定标识

TinyDB 的查询设计精妙之处：
- **`_test`**：实际执行的谓词函数（`Callable`）
- **`_hash`**：查询的"语义标识"（用于缓存键）

两者分离的好处：
- `_test` 可以是任意 lambda/闭包（执行逻辑）
- `_hash` 保证语义等价的查询能命中缓存

### 10.2 缓存策略：保守但安全

| 决策 | 原因 |
|-----|------|
| 默认假设可缓存 | 向后兼容，大多数查询确实可缓存 |
| 写入即全量清空 | 实现简单，避免复杂的依赖追踪 |
| `map()` 强制不可缓存 | 函数对象可能可变，缓存风险高 |

### 10.3 扩展性：Protocol + 可选方法

`QueryLike` Protocol 只要求：
```python
def __call__(self, value: Mapping) -> bool: ...
def __hash__(self) -> int: ...
```

`is_cacheable` 是**可选**的鸭子类型方法：
- 有 → 尊重其返回值
- 无 → 默认 `True`

这种设计：
- 保持 Protocol 简洁
- 允许自定义查询灵活控制缓存行为
- 向后兼容（旧代码不需要修改）
