import pytest


def _new_contact(store_module, **overrides):
    c = {
        "id": store_module.new_id(),
        "name": "Ada Lovelace",
        "nickname": "",
        "organisation": "",
        "job_title": "",
        "emails": [],
        "phones": [],
        "addresses": [],
        "birthday": None,
        "urls": [],
    }
    c.update(overrides)
    return c


def test_upsert_and_get_roundtrip(store_module):
    c = _new_contact(store_module, name="Ada Lovelace", nickname="Ada", emails=["ada@example.com"])
    stored = store_module.upsert(c)
    assert stored["name"] == "Ada Lovelace"
    assert stored["nickname"] == "Ada"
    assert stored["emails"] == ["ada@example.com"]

    fetched = store_module.get(c["id"])
    assert fetched["name"] == "Ada Lovelace"
    assert fetched["id"] == c["id"]


def test_upsert_full_fields(store_module):
    c = _new_contact(
        store_module,
        name="Grace Hopper",
        organisation="US Navy",
        job_title="Rear Admiral",
        emails=["grace@example.com", "g.hopper@example.com"],
        phones=["+15551234567"],
        addresses=[{"street": "1 Infinite Loop", "city": "Cupertino", "state": "CA", "postal_code": "95014", "country": "USA"}],
        birthday="1906-12-09",
        urls=["https://example.com"],
    )
    stored = store_module.upsert(c)
    assert stored["organisation"] == "US Navy"
    assert stored["job_title"] == "Rear Admiral"
    assert stored["emails"] == ["grace@example.com", "g.hopper@example.com"]
    assert stored["phones"] == ["+15551234567"]
    assert stored["addresses"] == [{"street": "1 Infinite Loop", "city": "Cupertino", "state": "CA", "postal_code": "95014", "country": "USA"}]
    assert stored["birthday"] == "1906-12-09"
    assert stored["urls"] == ["https://example.com"]


def test_upsert_birthday_without_year(store_module):
    c = _new_contact(store_module, birthday="--12-09")
    stored = store_module.upsert(c)
    assert stored["birthday"] == "--12-09"


def test_upsert_requires_name(store_module):
    c = _new_contact(store_module, name="  ")
    with pytest.raises(ValueError):
        store_module.upsert(c)


def test_upsert_updates_existing(store_module):
    c = _new_contact(store_module, name="Ada Lovelace")
    stored = store_module.upsert(c)

    updated = dict(stored)
    updated["organisation"] = "Analytical Engines Ltd"
    restored = store_module.upsert(updated)
    assert restored["organisation"] == "Analytical Engines Ltd"
    assert restored["id"] == c["id"]

    fetched = store_module.get(c["id"])
    assert fetched["organisation"] == "Analytical Engines Ltd"


def test_delete_removes_contact(store_module):
    c = _new_contact(store_module, name="Ada Lovelace")
    store_module.upsert(c)

    assert store_module.delete(c["id"]) is True
    assert store_module.get(c["id"]) is None


def test_delete_unknown_id_returns_false(store_module):
    assert store_module.delete("no-such-id") is False


def test_list_contacts_adopts_natively_created(store_module, fake_cn):
    native = fake_cn.new_contact()
    native.setGivenName_("Katherine")
    native.setFamilyName_("Johnson")
    fake_cn.save_contact(None, native, is_new=True)

    results = store_module.list_contacts()
    assert len(results) == 1
    assert results[0]["name"] == "Katherine Johnson"
    assert results[0]["id"] != native.identifier()  # our own id, not CNContact's

    # Second call reuses the same adopted id rather than adopting again.
    again = store_module.list_contacts()
    assert again[0]["id"] == results[0]["id"]


def test_list_contacts_self_heals_native_deletion(store_module, fake_cn):
    c = _new_contact(store_module, name="Ada Lovelace")
    store_module.upsert(c)
    assert len(store_module.list_contacts()) == 1

    # Deleted directly in Contacts.app, bypassing our delete().
    cn_identifier = store_module._sidecar.by_id(c["id"])
    fake_cn.contacts[cn_identifier]._removed = True

    live = store_module.list_contacts()
    assert live == []
    assert store_module.get(c["id"]) is None


def test_list_contacts_sorted_by_name(store_module):
    store_module.upsert(_new_contact(store_module, name="Zoe Adams"))
    store_module.upsert(_new_contact(store_module, name="Ada Lovelace"))

    results = store_module.list_contacts()
    assert [r["name"] for r in results] == ["Ada Lovelace", "Zoe Adams"]
