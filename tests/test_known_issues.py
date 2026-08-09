"""Tests for defects found in review that are NOT yet fixed.

**This module is expected to be red.** Each test asserts the behaviour the
service should have; they are here so the gap is executable and reviewable
rather than prose in a report. Delete a test's entry from the list below as you
fix it — none of them are xfail-marked, deliberately, so an unfixed regression
can't hide.

Covered here:
  * birthday accepts impossible calendar dates
  * labels (work/home/etc.) are destroyed by a read-modify-write round-trip
  * organisation-only and middle-name contacts don't round-trip
  * Contacts framework failures surface as unhandled 500s
  * routing errors (404/405) use a different error shape to handler errors
  * blocking Contacts calls run on the event loop
  * `_run_sync` waits forever if a completion handler never fires
  * the "Auth DISABLED" startup warning describes the opposite of what happens

Fixed and moved out of this module: non-ASCII bearer tokens (test_http.py),
case-insensitive auth scheme (test_http.py), sidecar cn_identifier collisions
and relative db_path (test_sidecar.py).
"""
from __future__ import annotations
import logging
import threading
import time

import httpx
import pytest
from starlette.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}

pytestmark = pytest.mark.known_issues


# --- Finding 3: birthday is not validated --------------------------------------

@pytest.mark.parametrize(
    "birthday",
    ["2020-13-45", "0000-00-00", "2020-02-30", "2020-00-15", "2020-01-00", "1906-12-09T00:00:00", "not-a-date-at-all"],
)
def test_impossible_birthday_rejected(app, birthday):
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.put("/contacts/bd", json={"name": "A B", "birthday": birthday}, headers=AUTH)
    assert resp.status_code == 400, f"accepted {birthday!r} and stored {resp.json().get('birthday')!r}"


@pytest.mark.parametrize("birthday", ["1906-12-09", "--12-09", "2000-02-29"])
def test_valid_birthday_still_accepted(app, birthday):
    """Guard rail for whatever validation gets added: these must keep working."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.put("/contacts/bd", json={"name": "A B", "birthday": birthday}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["birthday"] == birthday


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


# --- Contacts framework failures are unhandled ---------------------------------

@pytest.mark.parametrize(
    "method,route",
    [("fetch_all_contacts", "list"), ("contact_by_identifier", "get")],
)
def test_contacts_failure_returns_json_error_envelope(app, fake_cn, store_module, method, route):
    """AccessDenied/SaveFailed are never caught in http.py, so a revoked TCC grant
    or an unreachable store returns a bare 500 with a plain-text body."""
    from apple_contacts_server.contacts_client import AccessDenied

    store_module.upsert({"id": "x", "name": "A B"})
    fake_cn.failures[method] = AccessDenied("Contacts access not granted")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/contacts" if route == "list" else "/contacts/x", headers=AUTH)

    assert resp.status_code >= 500
    assert resp.headers["content-type"].startswith("application/json"), resp.text
    assert "error" in resp.json()


def test_save_failure_returns_json_error_envelope(app, fake_cn):
    from apple_contacts_server.contacts_client import SaveFailed

    fake_cn.failures["save_contact"] = SaveFailed("could not write to the address book")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.put("/contacts/x", json={"name": "A B"}, headers=AUTH)

    assert resp.status_code >= 500
    assert resp.headers["content-type"].startswith("application/json"), resp.text
    assert "error" in resp.json()


# --- Error envelope is inconsistent across the app -----------------------------

@pytest.mark.parametrize(
    "method,path",
    [("post", "/contacts/x"), ("patch", "/contacts/x"), ("get", "/nope"), ("delete", "/contacts")],
)
def test_routing_errors_use_the_documented_error_shape(app, method, path):
    """Handler errors return {"error": {"code", "message"}}; Starlette's own 404/405
    return text/plain, so a client can't parse one shape."""
    client = TestClient(app)
    resp = getattr(client, method)(path, headers=AUTH)
    assert resp.status_code in (404, 405)
    assert resp.headers["content-type"].startswith("application/json"), resp.text
    assert set(resp.json()["error"]) == {"code", "message"}


# --- Blocking Contacts calls run on the event loop ------------------------------

async def test_contacts_calls_do_not_block_the_event_loop(app, fake_cn):
    """Handlers are `async def` but call the Contacts framework synchronously.
    Enumerating a large address book stalls every other in-flight request."""
    original = fake_cn.fetch_all_contacts

    def slow_fetch(store):
        time.sleep(0.4)
        return original(store)

    fake_cn.fetch_all_contacts = slow_fetch

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        import asyncio

        started = time.perf_counter()
        await asyncio.gather(*(client.get("/contacts", headers=AUTH) for _ in range(3)))
        elapsed = time.perf_counter() - started

    assert elapsed < 0.9, f"3 concurrent requests took {elapsed:.2f}s — they serialised"


# --- `_run_sync` has no timeout -------------------------------------------------

def test_run_sync_gives_up_if_the_completion_handler_never_fires():
    """A completion handler that never fires hangs startup forever, with no log
    line and no way for a headless LaunchAgent to recover."""
    from apple_contacts_server import contacts_client

    finished = threading.Event()

    def never_calls_back(callback):
        pass

    def target():
        try:
            contacts_client._run_sync(never_calls_back)
        except Exception:
            pass
        finished.set()

    threading.Thread(target=target, daemon=True).start()
    assert finished.wait(timeout=3), "_run_sync blocked forever instead of timing out"


# --- Startup warning describes the opposite of the behaviour --------------------

def test_no_token_warning_does_not_claim_auth_is_disabled(fake_cn, tmp_path, monkeypatch, caplog):
    """With no tokens configured, `_authorized` returns False and every request
    401s. The server is unusable, not open — but the log says 'Auth DISABLED'."""
    from apple_contacts_server import main, store
    from apple_contacts_server.config import Config

    monkeypatch.setattr(store, "cn", fake_cn)
    config = Config(bearer_tokens=[], db_path=str(tmp_path / "meta.db"), _env_file=None)

    with caplog.at_level(logging.WARNING, logger="apple_contacts_server"):
        app = main.create_app(config)

    client = TestClient(app)
    assert client.get("/contacts").status_code == 401

    warning = " ".join(r.message for r in caplog.records).lower()
    assert "disabled" not in warning, f"misleading startup warning: {warning!r}"
