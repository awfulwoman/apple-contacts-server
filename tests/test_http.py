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
