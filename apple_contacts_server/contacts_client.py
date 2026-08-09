"""Thin wrapper around PyObjC's Contacts bindings — the only module that imports
Contacts directly, so tests can substitute a fake without touching real Contacts data.

Selectors confirmed against pyobjc-framework-Contacts 12.2.1 by introspecting the
installed bindings (`dir(CN.CNContactStore)` etc.) rather than from memory/docs.
"""
from __future__ import annotations
import threading
import Contacts as CN

ENTITY_TYPE_CONTACTS = CN.CNEntityTypeContacts

ALL_KEYS = [
    CN.CNContactGivenNameKey,
    CN.CNContactMiddleNameKey,
    CN.CNContactFamilyNameKey,
    CN.CNContactNicknameKey,
    CN.CNContactOrganizationNameKey,
    CN.CNContactJobTitleKey,
    CN.CNContactEmailAddressesKey,
    CN.CNContactPhoneNumbersKey,
    CN.CNContactPostalAddressesKey,
    CN.CNContactBirthdayKey,
    CN.CNContactUrlAddressesKey,
]

LABEL_HOME = CN.CNLabelHome

# How long to wait for the TCC permission dialog. Generous — it's a one-time,
# in-person interaction — but bounded: without a timeout, a completion handler
# that never fires (dialog dismissed some other way, TCC daemon wedged) hangs
# a headless LaunchAgent forever with no way to recover.
REQUEST_ACCESS_TIMEOUT_SECONDS = 300


class AccessDenied(Exception):
    pass


class SaveFailed(Exception):
    pass


def _run_sync(start, timeout: float | None = None):
    """Bridge a Contacts completion-handler call to a blocking call. `start` is
    given a callback and must invoke it exactly once; returns the callback's
    args. `timeout` is in seconds; `None` waits indefinitely."""
    done = threading.Event()
    result: list = []

    def callback(*args):
        result.extend(args)
        done.set()

    start(callback)
    if not done.wait(timeout):
        raise TimeoutError(f"Contacts framework did not respond within {timeout}s")
    return tuple(result)


def new_store() -> CN.CNContactStore:
    return CN.CNContactStore.alloc().init()


def request_access(store: CN.CNContactStore) -> None:
    """Blocks on the TCC prompt the first time it's called for this binary. Must run
    in a GUI session — a LaunchAgent (gui/<uid>), not a LaunchDaemon (no TCC identity)."""
    status = CN.CNContactStore.authorizationStatusForEntityType_(ENTITY_TYPE_CONTACTS)
    if status == CN.CNAuthorizationStatusAuthorized:
        return
    granted, error = _run_sync(
        lambda cb: store.requestAccessForEntityType_completionHandler_(ENTITY_TYPE_CONTACTS, cb),
        timeout=REQUEST_ACCESS_TIMEOUT_SECONDS,
    )
    if not granted:
        raise AccessDenied(f"Contacts access not granted: {error}")


def fetch_all_contacts(store: CN.CNContactStore) -> list:
    request = CN.CNContactFetchRequest.alloc().initWithKeysToFetch_(ALL_KEYS)
    contacts: list = []
    ok, error = store.enumerateContactsWithFetchRequest_error_usingBlock_(
        request, None, lambda contact, stop: contacts.append(contact)
    )
    if not ok:
        raise SaveFailed(f"failed to enumerate contacts: {error}")
    return contacts


def contact_by_identifier(store: CN.CNContactStore, cn_identifier: str):
    contact, _error = store.unifiedContactWithIdentifier_keysToFetch_error_(cn_identifier, ALL_KEYS, None)
    return contact


def new_contact() -> CN.CNMutableContact:
    return CN.CNMutableContact.alloc().init()


def save_contact(store: CN.CNContactStore, contact: CN.CNMutableContact, is_new: bool) -> None:
    request = CN.CNSaveRequest.alloc().init()
    if is_new:
        request.addContact_toContainerWithIdentifier_(contact, None)
    else:
        request.updateContact_(contact)
    ok, error = store.executeSaveRequest_error_(request, None)
    if not ok:
        raise SaveFailed(str(error))


def remove_contact(store: CN.CNContactStore, cn_identifier: str) -> None:
    contact, _error = store.unifiedContactWithIdentifier_keysToFetch_error_(
        cn_identifier, [CN.CNContactIdentifierKey], None
    )
    if contact is None:
        return
    request = CN.CNSaveRequest.alloc().init()
    request.deleteContact_(contact.mutableCopy())
    ok, error = store.executeSaveRequest_error_(request, None)
    if not ok:
        raise SaveFailed(str(error))


def make_labeled_value(label, value):
    return CN.CNLabeledValue.alloc().initWithLabel_value_(label, value)


def make_phone_number(value: str):
    return CN.CNPhoneNumber.alloc().initWithStringValue_(value)


def make_postal_address(street: str, city: str, state: str, postal_code: str, country: str):
    addr = CN.CNMutablePostalAddress.alloc().init()
    addr.setStreet_(street)
    addr.setCity_(city)
    addr.setState_(state)
    addr.setPostalCode_(postal_code)
    addr.setCountry_(country)
    return addr
