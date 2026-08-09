"""Direct tests for the id ↔ CNContact.identifier mapping table. It was only ever
exercised indirectly through `store`, which hid its failure modes."""
import pytest

from apple_contacts_server.sidecar import Sidecar


@pytest.fixture
def sidecar(tmp_path):
    return Sidecar(str(tmp_path / "meta.db"))


def test_put_and_lookup_both_directions(sidecar):
    sidecar.put("client-id", "cn-abc")
    assert sidecar.by_id("client-id") == "cn-abc"
    assert sidecar.by_cn_identifier("cn-abc") == "client-id"


def test_lookups_miss_cleanly(sidecar):
    assert sidecar.by_id("nope") is None
    assert sidecar.by_cn_identifier("nope") is None


def test_put_rebinds_an_existing_id(sidecar):
    sidecar.put("client-id", "cn-old")
    sidecar.put("client-id", "cn-new")
    assert sidecar.by_id("client-id") == "cn-new"
    assert sidecar.by_cn_identifier("cn-old") is None
    assert sidecar.all() == [("client-id", "cn-new")]


def test_put_is_idempotent(sidecar):
    for _ in range(3):
        sidecar.put("client-id", "cn-abc")
    assert sidecar.all() == [("client-id", "cn-abc")]


def test_all_returns_every_pair(sidecar):
    sidecar.put("a", "cn-a")
    sidecar.put("b", "cn-b")
    assert sorted(sidecar.all()) == [("a", "cn-a"), ("b", "cn-b")]


def test_all_is_empty_on_a_fresh_database(sidecar):
    assert sidecar.all() == []


def test_delete_row(sidecar):
    sidecar.put("a", "cn-a")
    sidecar.delete_row("a")
    assert sidecar.by_id("a") is None
    assert sidecar.all() == []


def test_delete_row_of_unknown_id_is_a_no_op(sidecar):
    sidecar.put("a", "cn-a")
    sidecar.delete_row("does-not-exist")
    assert sidecar.all() == [("a", "cn-a")]


def test_rows_persist_across_reopen(tmp_path):
    path = str(tmp_path / "meta.db")
    Sidecar(path).put("a", "cn-a")
    assert Sidecar(path).by_id("a") == "cn-a"


def test_opening_twice_does_not_wipe_the_schema(tmp_path):
    """`executescript` runs on every open; CREATE TABLE IF NOT EXISTS must hold."""
    path = str(tmp_path / "meta.db")
    first = Sidecar(path)
    first.put("a", "cn-a")
    second = Sidecar(path)
    second.put("b", "cn-b")
    assert sorted(second.all()) == [("a", "cn-a"), ("b", "cn-b")]


def test_creates_missing_parent_directories(tmp_path):
    sidecar = Sidecar(str(tmp_path / "deeply" / "nested" / "meta.db"))
    sidecar.put("a", "cn-a")
    assert (tmp_path / "deeply" / "nested" / "meta.db").exists()


def test_expands_a_tilde_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    Sidecar("~/state/meta.db").put("a", "cn-a")
    assert (tmp_path / "state" / "meta.db").exists()


def test_ids_are_opaque_strings(sidecar):
    """Nothing constrains the id format — unicode, punctuation and long values
    all have to survive, since the caller chooses them."""
    for id, cn_identifier in [("ünïcode-id", "cn-1"), ("a/b:c d", "cn-2"), ("x" * 500, "cn-3")]:
        sidecar.put(id, cn_identifier)
        assert sidecar.by_id(id) == cn_identifier


def test_sql_metacharacters_in_ids_are_not_interpreted(sidecar):
    hostile = "'; DROP TABLE contacts; --"
    sidecar.put(hostile, "cn-1")
    assert sidecar.by_id(hostile) == "cn-1"
    assert sidecar.all() == [(hostile, "cn-1")]
