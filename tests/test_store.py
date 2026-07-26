#!/usr/bin/env python3
"""Store unit tests: messages CRUD, FTS search, contacts, state."""
import os, sys, importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_store(tmp_path, monkeypatch):
    """Reload store module pointed at a temp DB."""
    import backend.core.store as store
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "test.db"))
    store.init_db()
    return store


def test_add_and_get_messages(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.add_message("e1", "alice", "hello", "in", created_at=1000)
    store.add_message("e2", "alice", "world", "out", created_at=1001)
    msgs = store.get_messages("alice")
    assert [m["content"] for m in msgs] == ["hello", "world"]
    assert msgs[0]["direction"] == "in"


def test_duplicate_event_id_ignored(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.add_message("e1", "alice", "hello", "in")
    store.add_message("e1", "alice", "hello", "in")
    assert len(store.get_messages("alice")) == 1


def test_fts_search(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.add_message("e1", "alice", "部署文档在服务器上", "in")
    store.add_message("e2", "alice", "今天天气不错", "in")
    results = store.search_messages("部署*")
    assert len(results) == 1
    assert "部署" in results[0]["content"]


def test_mark_delivered_and_read(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.add_message("e1", "alice", "hi", "out")
    store.mark_delivered("e1")
    store.mark_read("e1")
    m = store.get_messages("alice")[0]
    assert m["delivered"] == 1
    assert m["read_status"] == 1


def test_contacts_crud(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.upsert_contact("pk1", display_name="Alice", petname="小A")
    store.upsert_contact("pk1", display_name="Alice2")  # update
    contacts = store.list_contacts()
    assert len(contacts) == 1
    assert contacts[0]["display_name"] == "Alice2"
    assert contacts[0]["petname"] == "小A"
    store.delete_contact("pk1")
    assert store.list_contacts() == []


def test_state_roundtrip(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    assert store.get_state("k") is None
    store.set_state("k", "123")
    assert store.get_state("k") == "123"
    store.set_state("k", "456")
    assert store.get_state("k") == "456"


def test_history_pagination(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    for i in range(10):
        store.add_message(f"e{i}", "alice", f"msg{i}", "in", created_at=1000 + i)
    page1 = store.get_messages("alice", limit=3)
    assert [m["content"] for m in page1] == ["msg7", "msg8", "msg9"]
    page2 = store.get_messages("alice", limit=3, before=1007)
    assert [m["content"] for m in page2] == ["msg4", "msg5", "msg6"]
