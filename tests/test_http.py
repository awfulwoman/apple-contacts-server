import pytest
from starlette.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}


def test_requires_bearer_token(app):
    client = TestClient(app)
    resp = client.get("/contacts")
    assert resp.status_code == 401


def test_rejects_wrong_token(app):
    client = TestClient(app)
    resp = client.get("/contacts", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_put_get_list_roundtrip(app, store_module):
    client = TestClient(app)
    id = store_module.new_id()
    body = {
        "name": "Ada Lovelace",
        "nickname": "Ada",
        "organisation": "",
        "job_title": "",
        "emails": ["ada@example.com"],
        "phones": [],
        "addresses": [],
        "birthday": None,
        "urls": [],
    }

    put_resp = client.put(f"/contacts/{id}", json=body, headers=AUTH)
    assert put_resp.status_code == 200
    assert put_resp.json()["name"] == "Ada Lovelace"

    get_resp = client.get(f"/contacts/{id}", headers=AUTH)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == id

    list_resp = client.get("/contacts", headers=AUTH)
    assert list_resp.status_code == 200
    assert any(c["id"] == id for c in list_resp.json()["contacts"])


def test_put_missing_name_returns_400(app):
    client = TestClient(app)
    id = "some-id"
    resp = client.put(f"/contacts/{id}", json={"name": "  "}, headers=AUTH)
    assert resp.status_code == 400


def test_get_missing_returns_404(app):
    client = TestClient(app)
    resp = client.get("/contacts/no-such-id", headers=AUTH)
    assert resp.status_code == 404


def test_delete_roundtrip(app, store_module):
    client = TestClient(app)
    id = store_module.new_id()
    client.put(f"/contacts/{id}", json={"name": "Ada Lovelace"}, headers=AUTH)

    del_resp = client.delete(f"/contacts/{id}", headers=AUTH)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    missing_resp = client.delete(f"/contacts/{id}", headers=AUTH)
    assert missing_resp.status_code == 404


def test_delete_requires_auth(app):
    client = TestClient(app)
    assert client.delete("/contacts/x").status_code == 401


def test_put_requires_auth(app):
    client = TestClient(app)
    assert client.put("/contacts/x", json={"name": "A B"}).status_code == 401


def test_get_one_requires_auth(app):
    client = TestClient(app)
    assert client.get("/contacts/x").status_code == 401


def test_malformed_auth_headers_rejected(app):
    client = TestClient(app)
    for header in ["", "Bearer", "Bearer ", "test-token", "Basic test-token", "Bearer  test-token"]:
        resp = client.get("/contacts", headers={"Authorization": header})
        assert resp.status_code == 401, f"{header!r} was accepted"


@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
def test_auth_scheme_is_case_insensitive(app, scheme):
    """RFC 7235 §2.1: the auth-scheme token is case-insensitive."""
    client = TestClient(app)
    resp = client.get("/contacts", headers={"Authorization": f"{scheme} test-token"})
    assert resp.status_code == 200


def test_non_ascii_bearer_token_is_401_not_500(app):
    """`hmac.compare_digest` raises TypeError on a non-ASCII `str`, which would
    otherwise turn attacker-controlled input into an unhandled 500."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/contacts", headers={"Authorization": b"Bearer \xfcnicode"})
    assert resp.status_code == 401


def test_list_empty(app):
    client = TestClient(app)
    resp = client.get("/contacts", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"contacts": []}


def test_invalid_json_body_returns_400(app):
    client = TestClient(app)
    resp = client.put("/contacts/x", content=b"not json at all", headers=AUTH)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_json"


def test_empty_body_returns_400(app):
    client = TestClient(app)
    resp = client.put("/contacts/x", content=b"", headers=AUTH)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_json"


def test_body_id_is_ignored_in_favour_of_path(app):
    client = TestClient(app)
    resp = client.put("/contacts/path-id", json={"name": "A B", "id": "body-id"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["id"] == "path-id"


def test_unknown_body_fields_are_dropped(app):
    client = TestClient(app)
    resp = client.put("/contacts/x", json={"name": "A B", "note": "secret"}, headers=AUTH)
    assert resp.status_code == 200
    assert "note" not in resp.json()


def test_optional_fields_default_when_omitted(app):
    client = TestClient(app)
    resp = client.put("/contacts/x", json={"name": "A B"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {
        "id": "x", "name": "A B", "nickname": "", "organisation": "", "job_title": "",
        "emails": [], "phones": [], "addresses": [], "birthday": None, "urls": [],
    }


def test_explicit_nulls_are_treated_as_empty(app):
    """A client clearing fields sends null, and that shouldn't be a 400."""
    client = TestClient(app)
    body = {"name": "A B", "nickname": None, "emails": None, "addresses": None, "birthday": None}
    resp = client.put("/contacts/x", json=body, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["nickname"] == ""
    assert resp.json()["emails"] == []


# --- Body type validation (see models.ContactBody) ------------------------------
# Every case below reached the Contacts framework before the model existed: most
# raised inside `_apply_dict` and surfaced as a 500, and the bare-string `emails`
# case silently wrote one contact field per character.

@pytest.mark.parametrize(
    "body",
    [
        pytest.param(["a"], id="body-is-array"),
        pytest.param("just a string", id="body-is-string"),
        pytest.param(42, id="body-is-number"),
        pytest.param({}, id="name-missing"),
        pytest.param({"name": 123}, id="name-is-number"),
        pytest.param({"name": None}, id="name-is-null"),
        pytest.param({"name": ["A", "B"]}, id="name-is-array"),
        pytest.param({"name": "A B", "emails": "ada@example.com"}, id="emails-is-string"),
        pytest.param({"name": "A B", "emails": [None]}, id="emails-contains-null"),
        pytest.param({"name": "A B", "emails": [{"a": 1}]}, id="emails-contains-object"),
        pytest.param({"name": "A B", "phones": [None]}, id="phones-contains-null"),
        pytest.param({"name": "A B", "phones": "+15551234567"}, id="phones-is-string"),
        pytest.param({"name": "A B", "urls": "https://example.com"}, id="urls-is-string"),
        pytest.param({"name": "A B", "addresses": ["oops"]}, id="addresses-contains-string"),
        pytest.param({"name": "A B", "addresses": {"street": "x"}}, id="addresses-is-object"),
        pytest.param({"name": "A B", "addresses": [{"street": 1}]}, id="address-field-is-number"),
        pytest.param({"name": "A B", "birthday": 19061209}, id="birthday-is-number"),
        pytest.param({"name": "A B", "birthday": ["1906-12-09"]}, id="birthday-is-array"),
        pytest.param({"name": "A B", "birthday": "2020-13-45"}, id="birthday-bad-month-and-day"),
        pytest.param({"name": "A B", "birthday": "0000-00-00"}, id="birthday-all-zero"),
        pytest.param({"name": "A B", "birthday": "2020-02-30"}, id="birthday-feb-30"),
        pytest.param({"name": "A B", "birthday": "2020-00-15"}, id="birthday-month-zero"),
        pytest.param({"name": "A B", "birthday": "2020-01-00"}, id="birthday-day-zero"),
        pytest.param({"name": "A B", "birthday": "1906-12-09T00:00:00"}, id="birthday-has-time-component"),
        pytest.param({"name": "A B", "birthday": "not-a-date-at-all"}, id="birthday-garbage"),
        pytest.param({"name": "A B", "birthday": "--02-30"}, id="birthday-yearless-feb-30"),
        pytest.param({"name": "A B", "birthday": "--13"}, id="birthday-yearless-too-short"),
        pytest.param({"name": "A B", "nickname": ["Ada"]}, id="nickname-is-array"),
        pytest.param({"name": "A B", "organisation": 7}, id="organisation-is-number"),
        pytest.param({"name": "A B", "job_title": {"a": 1}}, id="job-title-is-object"),
    ],
)
def test_malformed_body_returns_400_not_500(app, body):
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.put("/contacts/x", json=body, headers=AUTH)
    assert resp.status_code == 400, f"got {resp.status_code}: {resp.text}"
    assert resp.json()["error"]["code"] == "validation_error"


def test_string_emails_never_reach_the_address_book(app, fake_cn):
    """Regression: `emails: "a@b.c"` used to iterate the string and write one
    labelled value per character into Contacts.app."""
    client = TestClient(app, raise_server_exceptions=False)
    client.put("/contacts/x", json={"name": "A B", "emails": "ada@example.com"}, headers=AUTH)
    assert fake_cn.contacts == {}


def test_validation_error_message_names_the_field(app):
    client = TestClient(app)
    resp = client.put("/contacts/x", json={"name": "A B", "emails": "nope"}, headers=AUTH)
    assert "emails" in resp.json()["error"]["message"]


@pytest.mark.parametrize("birthday", ["1906-12-09", "--12-09", "2000-02-29", "--02-29"])
def test_valid_birthdays_are_accepted(app, birthday):
    client = TestClient(app)
    resp = client.put("/contacts/bd", json={"name": "A B", "birthday": birthday}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["birthday"] == birthday


def test_empty_string_birthday_clears_the_field(app):
    client = TestClient(app)
    resp = client.put("/contacts/bd", json={"name": "A B", "birthday": ""}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["birthday"] is None


# --- Consistent {"error": {"code", "message"}} envelope, even for framework/routing errors ------

@pytest.mark.parametrize(
    "method,path",
    [("post", "/contacts/x"), ("patch", "/contacts/x"), ("get", "/nope"), ("delete", "/contacts")],
)
def test_routing_errors_use_the_documented_error_shape(app, method, path):
    """Starlette's own 404/405 default to a plain-text body — a different shape
    to every handler error, which returns {"error": {"code", "message"}}."""
    client = TestClient(app)
    resp = getattr(client, method)(path, headers=AUTH)
    assert resp.status_code in (404, 405)
    assert resp.headers["content-type"].startswith("application/json"), resp.text
    assert set(resp.json()["error"]) == {"code", "message"}


@pytest.mark.parametrize(
    "method,route",
    [("fetch_all_contacts", "list"), ("contact_by_identifier", "get")],
)
def test_contacts_failure_returns_json_error_envelope(app, fake_cn, store_module, method, route):
    """AccessDenied/SaveFailed used to escape http.py uncaught, so a revoked TCC
    grant or an unreachable store returned a bare 500 with a plain-text body."""
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


# --- Handlers no longer block the event loop -----------------------------------

async def test_contacts_calls_do_not_block_the_event_loop(app, fake_cn):
    """Handlers call `store` through `run_in_threadpool`; enumerating a large
    address book must not stall every other in-flight request."""
    import asyncio
    import time

    import httpx

    original = fake_cn.fetch_all_contacts

    def slow_fetch(store):
        time.sleep(0.4)
        return original(store)

    fake_cn.fetch_all_contacts = slow_fetch

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = time.perf_counter()
        await asyncio.gather(*(client.get("/contacts", headers=AUTH) for _ in range(3)))
        elapsed = time.perf_counter() - started

    assert elapsed < 0.9, f"3 concurrent requests took {elapsed:.2f}s — they serialised"
