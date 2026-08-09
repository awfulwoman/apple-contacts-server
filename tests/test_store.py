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
    c = _new_contact(store_module, name="Ada Lovelace", nickname="Ada", emails=[{"value": "ada@example.com"}])
    stored = store_module.upsert(c)
    assert stored["name"] == "Ada Lovelace"
    assert stored["nickname"] == "Ada"
    assert stored["emails"] == [{"label": "home", "value": "ada@example.com"}]

    fetched = store_module.get(c["id"])
    assert fetched["name"] == "Ada Lovelace"
    assert fetched["id"] == c["id"]


def test_upsert_full_fields(store_module):
    c = _new_contact(
        store_module,
        name="Grace Hopper",
        organisation="US Navy",
        job_title="Rear Admiral",
        emails=[{"value": "grace@example.com"}, {"label": "work", "value": "g.hopper@example.com"}],
        phones=[{"value": "+15551234567"}],
        addresses=[{
            "label": "work", "street": "1 Infinite Loop", "city": "Cupertino",
            "state": "CA", "postal_code": "95014", "country": "USA",
        }],
        birthday="1906-12-09",
        urls=[{"value": "https://example.com"}],
    )
    stored = store_module.upsert(c)
    assert stored["organisation"] == "US Navy"
    assert stored["job_title"] == "Rear Admiral"
    assert stored["emails"] == [
        {"label": "home", "value": "grace@example.com"},
        {"label": "work", "value": "g.hopper@example.com"},
    ]
    assert stored["phones"] == [{"label": "home", "value": "+15551234567"}]
    assert stored["addresses"] == [{
        "label": "work", "street": "1 Infinite Loop", "city": "Cupertino",
        "state": "CA", "postal_code": "95014", "country": "USA",
    }]
    assert stored["birthday"] == "1906-12-09"
    assert stored["urls"] == [{"label": "home", "value": "https://example.com"}]


def test_upsert_preserves_a_custom_label_on_round_trip(store_module):
    """A label sent back unchanged — including one that isn't a recognised
    friendly alias — must survive as a literal custom label."""
    c = _new_contact(store_module, emails=[{"label": "yacht club", "value": "ada@example.com"}])
    stored = store_module.upsert(c)
    assert stored["emails"] == [{"label": "yacht club", "value": "ada@example.com"}]

    fetched = store_module.get(c["id"])
    assert fetched["emails"] == [{"label": "yacht club", "value": "ada@example.com"}]


def test_read_modify_write_preserves_a_native_contacts_label(store_module, fake_cn):
    """A native contact's raw framework label token, fetched and sent back
    unchanged, must not be relabelled 'home'."""
    native = fake_cn.new_contact()
    native.setGivenName_("Grace")
    native.setFamilyName_("Hopper")
    native.setEmailAddresses_([fake_cn.make_labeled_value("_$!<Work>!$_", "g@navy.mil")])
    fake_cn.save_contact(None, native, is_new=True)

    fetched = store_module.list_contacts()[0]
    assert fetched["emails"] == [{"label": "_$!<Work>!$_", "value": "g@navy.mil"}]

    stored = store_module.upsert(fetched)
    assert stored["emails"] == [{"label": "_$!<Work>!$_", "value": "g@navy.mil"}]


def test_upsert_birthday_without_year(store_module):
    c = _new_contact(store_module, birthday="--12-09")
    stored = store_module.upsert(c)
    assert stored["birthday"] == "--12-09"


def test_upsert_requires_name(store_module):
    c = _new_contact(store_module, name="  ")
    with pytest.raises(ValueError):
        store_module.upsert(c)


def test_upsert_allows_organisation_only_contact(store_module):
    """Company contacts (Contacts.app allows these) have no given/family name;
    organisation alone must satisfy the "needs some identity" check."""
    c = _new_contact(store_module, name="", organisation="Acme Corp")
    stored = store_module.upsert(c)
    assert stored["name"] == ""
    assert stored["organisation"] == "Acme Corp"


def test_organisation_only_contact_round_trips(store_module, fake_cn):
    """A company contact adopted from Contacts.app must be writable straight
    back — a read-modify-write over the whole address book shouldn't break on it."""
    native = fake_cn.new_contact()
    native.setOrganizationName_("Acme Corp")
    fake_cn.save_contact(None, native, is_new=True)

    listed = store_module.list_contacts()[0]
    assert listed["organisation"] == "Acme Corp"
    stored = store_module.upsert(listed)
    assert stored["organisation"] == "Acme Corp"


def test_middle_name_included_in_name(store_module, fake_cn):
    native = fake_cn.new_contact()
    native.setGivenName_("Mary")
    native.setMiddleName_("Jane")
    native.setFamilyName_("Watson")
    fake_cn.save_contact(None, native, is_new=True)

    assert store_module.list_contacts()[0]["name"] == "Mary Jane Watson"


def test_upsert_splits_a_three_part_name_into_given_middle_family(store_module, fake_cn):
    store_module.upsert(_new_contact(store_module, id="mjw", name="Mary Jane Watson"))
    stored = fake_cn.contacts[store_module._sidecar.by_id("mjw")]
    assert stored.givenName() == "Mary"
    assert stored.middleName() == "Jane"
    assert stored.familyName() == "Watson"


def test_upsert_repeated_spaces_do_not_leak_into_family_name(store_module, fake_cn):
    store_module.upsert(_new_contact(store_module, id="al", name="Ada  Lovelace"))
    stored = fake_cn.contacts[store_module._sidecar.by_id("al")]
    assert stored.givenName() == "Ada"
    assert stored.familyName() == "Lovelace"


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
