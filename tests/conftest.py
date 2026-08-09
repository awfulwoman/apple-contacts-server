"""A fake standing in for `apple_contacts_server.contacts_client` — in-memory, so
the store/http tests touch no real Contacts data and trigger no TCC prompt.

Still macOS-only: `store.py` imports `Foundation` at module scope for
`NSDateComponents`, so the suite needs PyObjC even though it never reaches
Contacts.app."""
from __future__ import annotations
import uuid
import pytest


class FakeLabeledValue:
    def __init__(self, label, value):
        self._label = label
        self._value = value

    def label(self):
        return self._label

    def value(self):
        return self._value


class FakePhoneNumber:
    def __init__(self, value):
        self._value = value

    def stringValue(self):
        return self._value


class FakePostalAddress:
    def __init__(self):
        self._street = ""
        self._city = ""
        self._state = ""
        self._postal_code = ""
        self._country = ""

    def street(self):
        return self._street

    def setStreet_(self, v):
        self._street = v

    def city(self):
        return self._city

    def setCity_(self, v):
        self._city = v

    def state(self):
        return self._state

    def setState_(self, v):
        self._state = v

    def postalCode(self):
        return self._postal_code

    def setPostalCode_(self, v):
        self._postal_code = v

    def country(self):
        return self._country

    def setCountry_(self, v):
        self._country = v


class FakeContact:
    def __init__(self, identifier):
        self._identifier = identifier
        self._given_name = ""
        self._middle_name = ""
        self._family_name = ""
        self._nickname = ""
        self._organization_name = ""
        self._job_title = ""
        self._email_addresses = []
        self._phone_numbers = []
        self._postal_addresses = []
        self._birthday = None
        self._url_addresses = []
        self._removed = False

    def identifier(self):
        return self._identifier

    def givenName(self):
        return self._given_name

    def setGivenName_(self, v):
        self._given_name = v

    def middleName(self):
        return self._middle_name

    def setMiddleName_(self, v):
        self._middle_name = v

    def familyName(self):
        return self._family_name

    def setFamilyName_(self, v):
        self._family_name = v

    def nickname(self):
        return self._nickname

    def setNickname_(self, v):
        self._nickname = v

    def organizationName(self):
        return self._organization_name

    def setOrganizationName_(self, v):
        self._organization_name = v

    def jobTitle(self):
        return self._job_title

    def setJobTitle_(self, v):
        self._job_title = v

    def emailAddresses(self):
        return self._email_addresses

    def setEmailAddresses_(self, v):
        self._email_addresses = v

    def phoneNumbers(self):
        return self._phone_numbers

    def setPhoneNumbers_(self, v):
        self._phone_numbers = v

    def postalAddresses(self):
        return self._postal_addresses

    def setPostalAddresses_(self, v):
        self._postal_addresses = v

    def birthday(self):
        return self._birthday

    def setBirthday_(self, v):
        self._birthday = v

    def urlAddresses(self):
        return self._url_addresses

    def setUrlAddresses_(self, v):
        self._url_addresses = v

    def mutableCopy(self):
        clone = FakeContact(self._identifier)
        clone.__dict__.update(self.__dict__)
        return clone


class FakeContacts:
    """Implements the same functions as `contacts_client`, backed by an in-memory dict."""

    LABEL_HOME = "home"
    LABEL_WORK = "work"
    LABEL_OTHER = "other"

    def __init__(self):
        self.contacts: dict[str, FakeContact] = {}
        # Framework failures the real Contacts store can raise (access revoked,
        # save rejected, store unreachable). Map method name -> exception to raise.
        self.failures: dict[str, Exception] = {}

    def _maybe_fail(self, method: str) -> None:
        exc = self.failures.get(method)
        if exc is not None:
            raise exc

    def new_store(self):
        return self

    def request_access(self, store):
        self._maybe_fail("request_access")

    def fetch_all_contacts(self, store):
        self._maybe_fail("fetch_all_contacts")
        return [c for c in self.contacts.values() if not c._removed]

    def contact_by_identifier(self, store, cn_identifier):
        self._maybe_fail("contact_by_identifier")
        c = self.contacts.get(cn_identifier)
        return c if c and not c._removed else None

    def new_contact(self):
        return FakeContact(str(uuid.uuid4()))

    def save_contact(self, store, contact, is_new):
        self._maybe_fail("save_contact")
        self.contacts[contact._identifier] = contact

    def remove_contact(self, store, cn_identifier):
        self._maybe_fail("remove_contact")
        contact = self.contacts.get(cn_identifier)
        if contact:
            contact._removed = True

    def make_labeled_value(self, label, value):
        return FakeLabeledValue(label, value)

    def make_phone_number(self, value):
        return FakePhoneNumber(value)

    def make_postal_address(self, street, city, state, postal_code, country):
        addr = FakePostalAddress()
        addr.setStreet_(street)
        addr.setCity_(city)
        addr.setState_(state)
        addr.setPostalCode_(postal_code)
        addr.setCountry_(country)
        return addr


@pytest.fixture
def fake_cn():
    return FakeContacts()


@pytest.fixture
def store_module(fake_cn, tmp_path, monkeypatch):
    from apple_contacts_server import store as store_mod
    from apple_contacts_server.config import Config

    monkeypatch.setattr(store_mod, "cn", fake_cn)
    config = Config(bearer_tokens=["test-token"], db_path=str(tmp_path / "meta.db"))
    store_mod.init(config)
    return store_mod


@pytest.fixture
def app(store_module):
    from apple_contacts_server import http

    http.init(store_module._config)
    return http.create_app()
