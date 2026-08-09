"""Tests for the parts of the Contacts wrapper that are plain Python.

The framework calls themselves still need occasional live verification against a
real Contacts.app (see the README) — but `_run_sync`, the completion-handler
bridge every access request goes through, is pure Python and worth pinning down.
"""
import threading

from apple_contacts_server import contacts_client


def test_run_sync_returns_the_callback_arguments():
    assert contacts_client._run_sync(lambda cb: cb(True, None)) == (True, None)


def test_run_sync_returns_empty_tuple_for_a_bare_callback():
    assert contacts_client._run_sync(lambda cb: cb()) == ()


def test_run_sync_waits_for_a_callback_from_another_thread():
    """The real completion handler fires on a framework-owned thread, not ours."""

    def start(callback):
        threading.Timer(0.05, lambda: callback(False, "denied")).start()

    assert contacts_client._run_sync(start) == (False, "denied")


def test_run_sync_propagates_a_failure_to_start():
    class Boom(Exception):
        pass

    def start(callback):
        raise Boom

    try:
        contacts_client._run_sync(start)
    except Boom:
        return
    raise AssertionError("exception from `start` was swallowed")


def test_run_sync_times_out_if_the_callback_never_fires():
    """A completion handler that never fires must not hang forever — a headless
    LaunchAgent has no way to intervene and recover."""
    import pytest

    def never_calls_back(callback):
        pass

    with pytest.raises(TimeoutError):
        contacts_client._run_sync(never_calls_back, timeout=0.2)


def test_request_access_uses_a_bounded_timeout():
    assert contacts_client.REQUEST_ACCESS_TIMEOUT_SECONDS > 0


def test_all_keys_covers_every_public_field():
    """`ALL_KEYS` drives both fetching and what `store` can read back — if a field
    is added to the public dict it must be fetched too."""
    import Contacts as CN

    required = {
        CN.CNContactGivenNameKey,
        CN.CNContactFamilyNameKey,
        CN.CNContactNicknameKey,
        CN.CNContactOrganizationNameKey,
        CN.CNContactJobTitleKey,
        CN.CNContactEmailAddressesKey,
        CN.CNContactPhoneNumbersKey,
        CN.CNContactPostalAddressesKey,
        CN.CNContactBirthdayKey,
        CN.CNContactUrlAddressesKey,
    }
    assert required <= set(contacts_client.ALL_KEYS)


def test_make_postal_address_sets_every_component():
    address = contacts_client.make_postal_address("1 Infinite Loop", "Cupertino", "CA", "95014", "USA")
    assert str(address.street()) == "1 Infinite Loop"
    assert str(address.city()) == "Cupertino"
    assert str(address.state()) == "CA"
    assert str(address.postalCode()) == "95014"
    assert str(address.country()) == "USA"


def test_make_phone_number_round_trips():
    assert str(contacts_client.make_phone_number("+15551234567").stringValue()) == "+15551234567"


def test_make_labeled_value_keeps_label_and_value():
    labeled = contacts_client.make_labeled_value(contacts_client.LABEL_HOME, "ada@example.com")
    assert str(labeled.label()) == str(contacts_client.LABEL_HOME)
    assert str(labeled.value()) == "ada@example.com"


def test_new_contact_starts_empty():
    contact = contacts_client.new_contact()
    assert str(contact.givenName()) == ""
    assert str(contact.familyName()) == ""
