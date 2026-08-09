"""Tests for defects found in review that are NOT yet fixed.

**This module is expected to be red.** Each test asserts the behaviour the
service should have; they are here so the gap is executable and reviewable
rather than prose in a report. Delete a test's entry from the list below as you
fix it — none of them are xfail-marked, deliberately, so an unfixed regression
can't hide.

Covered here:
  * labels (work/home/etc.) are destroyed by a read-modify-write round-trip —
    this one needs a decision on the wire format (emails/phones/urls are plain
    strings today; preserving labels means they'd need to carry one) before
    it can be fixed, so it's parked here rather than patched around.

Fixed and moved out of this module: non-ASCII bearer tokens, case-insensitive
auth scheme, birthday calendar validation (test_http.py); sidecar
cn_identifier collisions, relative db_path (test_sidecar.py); unhandled
framework errors, inconsistent 404/405 error shape (test_http.py, via
http.py's exception_handlers); blocking Contacts calls on the event loop
(test_http.py, via run_in_threadpool); _run_sync timeout
(test_contacts_client.py); misleading "Auth DISABLED" warning (test_main.py);
organisation-only contacts, middle names, repeated-space names (test_store.py).
"""
from __future__ import annotations
import pytest
from starlette.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}

pytestmark = pytest.mark.known_issues


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
