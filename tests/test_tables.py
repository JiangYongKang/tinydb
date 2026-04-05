import re

import pytest

from tinydb import where


def test_next_id(db):
    db.truncate()

    assert db._get_next_id() == 1
    assert db._get_next_id() == 2
    assert db._get_next_id() == 3


def test_tables_list(db):
    db.table('table1').insert({'a': 1})
    db.table('table2').insert({'a': 1})

    assert db.tables() == {'_default', 'table1', 'table2'}


def test_one_table(db):
    table1 = db.table('table1')

    table1.insert_multiple({'int': 1, 'char': c} for c in 'abc')

    assert table1.get(where('int') == 1)['char'] == 'a'
    assert table1.get(where('char') == 'b')['char'] == 'b'


def test_multiple_tables(db):
    table1 = db.table('table1')
    table2 = db.table('table2')
    table3 = db.table('table3')

    table1.insert({'int': 1, 'char': 'a'})
    table2.insert({'int': 1, 'char': 'b'})
    table3.insert({'int': 1, 'char': 'c'})

    assert table1.count(where('char') == 'a') == 1
    assert table2.count(where('char') == 'b') == 1
    assert table3.count(where('char') == 'c') == 1

    db.drop_tables()

    assert len(table1) == 0
    assert len(table2) == 0
    assert len(table3) == 0


def test_caching(db):
    table1 = db.table('table1')
    table2 = db.table('table1')

    assert table1 is table2


def test_query_cache(db):
    query1 = where('int') == 1

    assert db.count(query1) == 3
    assert query1 not in db._query_cache

    db.search(query1)
    assert query1 in db._query_cache

    assert db.count(query1) == 3
    assert query1 in db._query_cache

    query2 = where('int') == 0

    assert db.count(query2) == 0
    assert query2 not in db._query_cache

    db.search(query2)
    assert query2 in db._query_cache

    assert db.count(query2) == 0
    assert query2 in db._query_cache


def test_query_cache_with_mutable_callable(db):
    table = db.table('table')
    table.insert({'val': 5})

    mutable = 5
    increase = lambda x: x + mutable

    assert where('val').is_cacheable()
    assert not where('val').map(increase).is_cacheable()
    assert not (where('val').map(increase) == 10).is_cacheable()

    search = where('val').map(increase) == 10
    assert table.count(search) == 1

    # now `increase` would yield 15, not 10
    mutable = 10

    assert table.count(search) == 0
    assert len(table._query_cache) == 0


def test_zero_cache_size(db):
    table = db.table('table3', cache_size=0)
    query = where('int') == 1

    table.insert({'int': 1})
    table.insert({'int': 1})

    assert table.count(query) == 2
    assert table.count(where('int') == 2) == 0
    assert len(table._query_cache) == 0


def test_query_cache_size(db):
    table = db.table('table3', cache_size=1)
    query = where('int') == 1

    table.insert({'int': 1})
    table.insert({'int': 1})

    assert table.count(query) == 2
    assert table.count(where('int') == 2) == 0
    assert len(table._query_cache) == 0

    table.search(query)
    table.search(where('int') == 2)
    assert len(table._query_cache) == 1


def test_lru_cache(db):
    # Test integration into TinyDB
    table = db.table('table3', cache_size=2)
    query = where('int') == 1

    table.search(query)
    table.search(where('int') == 2)
    table.search(where('int') == 3)
    assert query not in table._query_cache

    table.remove(where('int') == 1)
    assert not table._query_cache.lru

    table.search(query)

    assert len(table._query_cache) == 1
    table.clear_cache()
    assert len(table._query_cache) == 0


def test_table_is_iterable(db):
    table = db.table('table1')

    table.insert_multiple({'int': i} for i in range(3))

    assert [r for r in table] == table.all()


def test_table_name(db):
    name = 'table3'
    table = db.table(name)
    assert name == table.name

    with pytest.raises(AttributeError):
        table.name = 'foo'


def test_table_repr(db):
    name = 'table4'
    table = db.table(name)

    assert re.match(
        r"<Table name=\'table4\', total=0, "
        r"storage=<tinydb\.storages\.(MemoryStorage|JSONStorage) object at [a-zA-Z0-9]+>>",
        repr(table))


def test_truncate_table(db):
    db.truncate()
    assert db._get_next_id() == 1


def test_persist_table(db):
    db.table("persisted", persist_empty=True)
    assert "persisted" in db.tables()

    db.table("nonpersisted", persist_empty=False)
    assert "nonpersisted" not in db.tables()


def test_count_equals_search_len(db):
    db.drop_tables()
    db.insert_multiple({'int': i, 'char': c} for i, c in enumerate('abcde'))

    query = where('int') > 1
    assert db.count(query) == len(db.search(query))

    query_no_match = where('int') > 100
    assert db.count(query_no_match) == len(db.search(query_no_match)) == 0

    query_all = where('int').exists()
    assert db.count(query_all) == len(db.search(query_all)) == 5


def test_count_uses_cache(db):
    db.drop_tables()
    db.insert_multiple({'int': i} for i in range(10))

    query = where('int') > 5

    assert query not in db._query_cache

    db.search(query)
    assert query in db._query_cache
    cached_results = db._query_cache.get(query)
    assert cached_results is not None
    expected_count = len(cached_results)

    assert db.count(query) == expected_count

    db._read_table = lambda: {}
    assert db.count(query) == expected_count


def test_count_does_not_populate_cache(db):
    db.drop_tables()
    db.insert_multiple({'int': i} for i in range(10))

    query = where('int') > 5

    assert query not in db._query_cache

    db.count(query)
    assert query not in db._query_cache

    db.search(query)
    assert query in db._query_cache


def test_count_empty_table(db):
    db.drop_tables()

    assert db.count(where('int') == 1) == 0
    assert db.count(where('int').exists()) == 0


def test_count_after_write_invalidates_cache(db):
    db.drop_tables()
    db.insert({'int': 1})
    db.insert({'int': 2})

    query = where('int') == 1

    db.search(query)
    assert query in db._query_cache
    assert db.count(query) == 1

    db.insert({'int': 1})

    assert query not in db._query_cache
    assert db.count(query) == 2


def test_count_does_not_construct_documents():
    from tinydb import TinyDB, where
    from tinydb.storages import MemoryStorage
    from tinydb.table import Document, Table

    class TrackingDocument(Document):
        creation_count = 0

        def __init__(self, value, doc_id):
            TrackingDocument.creation_count += 1
            super().__init__(value, doc_id)

    class TrackingTable(Table):
        document_class = TrackingDocument

    db = TinyDB(storage=MemoryStorage)
    db.table_class = TrackingTable

    table = db.table('test')
    doc_count = 100
    table.insert_multiple({'value': i} for i in range(doc_count))

    TrackingDocument.creation_count = 0

    count_result = table.count(where('value') >= 0)
    assert count_result == doc_count
    assert TrackingDocument.creation_count == 0

    search_result = table.search(where('value') >= 0)
    assert len(search_result) == doc_count
    assert TrackingDocument.creation_count == doc_count
    assert all(isinstance(d, TrackingDocument) for d in search_result)
