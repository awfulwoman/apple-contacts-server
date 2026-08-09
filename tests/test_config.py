import pytest

from apple_contacts_server.config import Config


def _config(**kwargs):
    # `_env_file=None` keeps a developer's local .env out of the assertions.
    return Config(_env_file=None, **kwargs)


def test_defaults():
    config = _config()
    assert config.host == "127.0.0.1"
    assert config.port == 4102
    assert config.bearer_tokens == []
    assert config.db_path == "~/.local/state/apple-contacts-server/meta.db"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("one", ["one"]),
        ("one,two", ["one", "two"]),
        ("one, two ,three", ["one", "two", "three"]),
        ("  spaced  ", ["spaced"]),
        ("one,,two", ["one", "two"]),
        ("one,   ,two", ["one", "two"]),
        (",", []),
        ("", []),
        ("   ", []),
    ],
)
def test_bearer_tokens_csv_parsing(raw, expected):
    assert _config(bearer_tokens=raw).bearer_tokens == expected


def test_bearer_tokens_accepts_a_list_unchanged():
    assert _config(bearer_tokens=["a", "b"]).bearer_tokens == ["a", "b"]


def test_reads_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("CONTACTS_SERVER_BEARER_TOKENS", "env-one,env-two")
    monkeypatch.setenv("CONTACTS_SERVER_PORT", "9999")
    monkeypatch.setenv("CONTACTS_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("CONTACTS_SERVER_DB_PATH", "/tmp/somewhere.db")

    config = _config()
    assert config.bearer_tokens == ["env-one", "env-two"]
    assert config.port == 9999
    assert config.host == "0.0.0.0"
    assert config.db_path == "/tmp/somewhere.db"


def test_ignores_unprefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("BEARER_TOKENS", "should-be-ignored")
    monkeypatch.setenv("PORT", "1234")

    config = _config()
    assert config.bearer_tokens == []
    assert config.port == 4102


def test_environment_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("contacts_server_port", "8080")
    assert _config().port == 8080


def test_non_numeric_port_is_rejected(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("CONTACTS_SERVER_PORT", "not-a-port")
    with pytest.raises(ValidationError):
        _config()


def test_reads_an_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CONTACTS_SERVER_BEARER_TOKENS=file-token\nCONTACTS_SERVER_PORT=5000\n",
        encoding="utf-8",
    )
    config = Config(_env_file=str(env_file))
    assert config.bearer_tokens == ["file-token"]
    assert config.port == 5000


def test_environment_beats_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CONTACTS_SERVER_PORT=5000\n", encoding="utf-8")
    monkeypatch.setenv("CONTACTS_SERVER_PORT", "6000")
    assert Config(_env_file=str(env_file)).port == 6000
