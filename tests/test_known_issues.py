"""Tests for defects found in review that are NOT yet fixed.

**This module is expected to be red.** Each test asserts the behaviour the
service should have; they are here so the gap is executable and reviewable
rather than prose in a report. Delete a test's entry from the list below as you
fix it — none of them are xfail-marked, deliberately, so an unfixed regression
can't hide.

Covered here:
  * labels (work/home/etc.) are destroyed by a read-modify-write round-trip
  * organisation-only and middle-name contacts don't round-trip
  * repeated internal spaces in a name leak into family_name

Fixed and moved out of this module: non-ASCII bearer tokens, case-insensitive
auth scheme, birthday calendar validation (test_http.py); sidecar
cn_identifier collisions, relative db_path (test_sidecar.py); unhandled
framework errors, inconsistent 404/405 error shape (test_http.py, via
http.py's exception_handlers); blocking Contacts calls on the event loop
(test_http.py, via run_in_threadpool); _run_sync timeout
(test_contacts_client.py); misleading "Auth DISABLED" warning (test_main.py).
"""
from __future__ import annotations
import pytest
from starlette.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}

pytestmark = pytest.mark.known_issues


# --- Finding 4: labels destroyed by round-trip ---------------------------------

def test_read_modify_write_preserves_labels(app, store_module, fake_cn):
    """A contact created in Contacts.app with a *work* email, fetched and written
    back unchanged, must not come back relabelled 'home'."""
    native = fake_cn.new_contact()
    native.setGivenName_("Grace")
    native.setFamilyName_("Hopper")
    native.setEmailAddresses_([fake_cn.make_labeled_value("work", "g@navy.mil")])
    native.setPhoneNumbers_([fake_cn.make_labeled_value("work", fake_cn.make_phone_number("+15551234567"))])
    fake_cn.save_contact(None, native, is_new=True)

    client = TestClient(app)
    fetched = client.get("/contacts", headers=AUTH).json()["contacts"][0]
    assert client.put(f"/contacts/{fetched['id']}", json=fetched, headers=AUTH).status_code == 200

    stored = fake_cn.contacts[store_module._sidecar.by_id(fetched["id"])]
    assert stored.emailAddresses()[0].label() == "work"
    assert stored.phoneNumbers()[0].label() == "work"


# --- Finding 5: contacts that don't round-trip ---------------------------------

def test_organisation_only_contact_round_trips(app, fake_cn):
    """Company contacts have no given/family name. They list fine, but PUTting
    the document straight back is rejected — read-modify-write is impossible."""
    native = fake_cn.new_contact()
    native.setOrganizationName_("Acme Corp")
    fake_cn.save_contact(None, native, is_new=True)

    client = TestClient(app)
    fetched = client.get("/contacts", headers=AUTH).json()["contacts"][0]
    assert fetched["organisation"] == "Acme Corp"

    resp = client.put(f"/contacts/{fetched['id']}", json=fetched, headers=AUTH)
    assert resp.status_code == 200, resp.json()


def test_middle_name_survives_round_trip(app, store_module, fake_cn):
    """`middleName` is never fetched, so 'Mary Jane Watson' reads back as
    'Mary Watson' while Contacts.app still shows the middle name."""
    native = fake_cn.new_contact()
    native.setGivenName_("Mary")
    native.setMiddleName_("Jane")
    native.setFamilyName_("Watson")
    fake_cn.save_contact(None, native, is_new=True)

    client = TestClient(app)
    fetched = client.get("/contacts", headers=AUTH).json()["contacts"][0]
    assert fetched["name"] == "Mary Jane Watson"


def test_repeated_spaces_in_name_do_not_leak_into_family_name(store_module, fake_cn):
    """'Ada  Lovelace' splits on the first space only, giving family=' Lovelace'."""
    store_module.upsert({"id": "s", "name": "Ada  Lovelace"})
    stored = fake_cn.contacts[store_module._sidecar.by_id("s")]
    assert stored.givenName() == "Ada"
    assert stored.familyName() == "Lovelace"
