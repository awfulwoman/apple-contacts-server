"""Wiring tests for `main.create_app`. `store.cn` is patched first — an unpatched
`create_app` would call the real `CNContactStore` and trigger a TCC prompt."""
import pytest
from starlette.testclient import TestClient

from apple_contacts_server.config import Config


@pytest.fixture
def make_app(fake_cn, tmp_path, monkeypatch):
    from apple_contacts_server import main, store

    monkeypatch.setattr(store, "cn", fake_cn)

    def build(**kwargs):
        kwargs.setdefault("bearer_tokens", ["test-token"])
        kwargs.setdefault("db_path", str(tmp_path / "meta.db"))
        return main.create_app(Config(_env_file=None, **kwargs))

    return build


def test_create_app_serves_an_authenticated_request(make_app):
    client = TestClient(make_app())
    assert client.get("/contacts", headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_create_app_wires_the_configured_tokens(make_app):
    client = TestClient(make_app(bearer_tokens=["alpha", "beta"]))
    assert client.get("/contacts", headers={"Authorization": "Bearer alpha"}).status_code == 200
    assert client.get("/contacts", headers={"Authorization": "Bearer beta"}).status_code == 200
    assert client.get("/contacts", headers={"Authorization": "Bearer gamma"}).status_code == 401


def test_create_app_creates_the_sidecar_database(make_app, tmp_path):
    make_app(db_path=str(tmp_path / "nested" / "meta.db"))
    assert (tmp_path / "nested" / "meta.db").exists()


def test_create_app_requests_contacts_access(make_app, fake_cn):
    from apple_contacts_server.contacts_client import AccessDenied

    fake_cn.failures["request_access"] = AccessDenied("Contacts access not granted")
    with pytest.raises(AccessDenied):
        make_app()


def test_missing_tokens_reject_every_request(make_app):
    """Not 'auth disabled' — with no tokens the server refuses everything."""
    client = TestClient(make_app(bearer_tokens=[]))
    assert client.get("/contacts").status_code == 401
    assert client.get("/contacts", headers={"Authorization": "Bearer anything"}).status_code == 401


def test_missing_tokens_logs_a_warning(make_app, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="apple_contacts_server"):
        make_app(bearer_tokens=[])
    warning = " ".join(r.message for r in caplog.records)
    assert "CONTACTS_SERVER_BEARER_TOKENS" in warning
    # The server 401s every request with no tokens configured — it's unusable,
    # not open, so the warning must not claim auth is "disabled".
    assert "disabled" not in warning.lower()
