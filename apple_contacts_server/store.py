"""Contacts store backed by real Contacts.app content plus the `sidecar` id-mapping
table. Public interface (id, name, nickname, organisation, job_title, emails,
phones, addresses, birthday, urls) is designed so a caller can treat this as a
thin HTTP client over a REST API, without needing its own Contacts framework
access.

`emails`/`phones`/`urls`/`addresses` entries carry a `label` (e.g. `"home"`,
`"work"`, or a raw Contacts framework token like `"_$!<Work>!$_"` on a native
contact) — see `models.LabeledValue`'s docstring for how that round-trips.

Contacts created outside this service — Contacts.app, Siri, another device — are
"adopted" on first sight: the first list/get call that observes a CNContact with no
sidecar row mints one. That's what makes native edits show up through this API
too, unlike a naive backend that only ever saw writes that went through it.

Unlike reminders, there's no offline-sync client for contacts today, so this store
skips the LWW/tombstone machinery entirely: `upsert` is plain last-write-wins and
`delete` is a real CNContact delete, not a soft-delete.
"""
from __future__ import annotations
import uuid
from Foundation import NSDateComponents, NSDateComponentUndefined
from apple_contacts_server import contacts_client as cn
from apple_contacts_server.config import Config
from apple_contacts_server.sidecar import Sidecar

_config: Config | None = None
_store = None
_sidecar: Sidecar | None = None


def init(config: Config) -> None:
    global _config, _store, _sidecar
    _config = config
    _store = cn.new_store()
    cn.request_access(_store)
    _sidecar = Sidecar(config.db_path)


def new_id() -> str:
    return str(uuid.uuid4())


def _birthday_to_components(birthday: str) -> NSDateComponents:
    comps = NSDateComponents.alloc().init()
    if birthday.startswith("--"):
        month, day = birthday[2:].split("-")
    else:
        year, month, day = birthday.split("-")
        comps.setYear_(int(year))
    comps.setMonth_(int(month))
    comps.setDay_(int(day))
    return comps


def _components_to_birthday(comps) -> str | None:
    if comps is None:
        return None
    month, day = comps.month(), comps.day()
    if month == NSDateComponentUndefined or day == NSDateComponentUndefined:
        return None
    year = comps.year()
    if year == NSDateComponentUndefined or not year:
        return f"--{month:02d}-{day:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _resolve_label(label: str):
    """Friendly aliases accepted on the way in (case-insensitive); anything
    else — including a framework's raw internal token fetched via GET and sent
    back unchanged — is passed straight through as a literal (possibly custom)
    label. Built per-call, not at module scope: `cn` is swapped for a fake in
    tests, and a module-level dict would freeze in the real constants first."""
    friendly = {"home": cn.LABEL_HOME, "work": cn.LABEL_WORK, "other": cn.LABEL_OTHER}
    return friendly.get(label.lower(), label)


def _labeled_values(values) -> list[dict]:
    return [{"label": str(v.label() or ""), "value": str(v.value())} for v in (values or [])]


def _labeled_phones(values) -> list[dict]:
    return [{"label": str(v.label() or ""), "value": str(v.value().stringValue())} for v in (values or [])]


def _addresses(values) -> list[dict]:
    out = []
    for v in values or []:
        a = v.value()
        out.append({
            "label": str(v.label() or ""),
            "street": str(a.street() or ""),
            "city": str(a.city() or ""),
            "state": str(a.state() or ""),
            "postal_code": str(a.postalCode() or ""),
            "country": str(a.country() or ""),
        })
    return out


def _contact_to_dict(contact, id: str) -> dict:
    name_parts = [str(contact.givenName() or ""), str(contact.middleName() or ""), str(contact.familyName() or "")]
    name = " ".join(p for p in name_parts if p)
    return {
        "id": id,
        "name": name,
        "nickname": str(contact.nickname() or ""),
        "organisation": str(contact.organizationName() or ""),
        "job_title": str(contact.jobTitle() or ""),
        "emails": _labeled_values(contact.emailAddresses()),
        "phones": _labeled_phones(contact.phoneNumbers()),
        "addresses": _addresses(contact.postalAddresses()),
        "birthday": _components_to_birthday(contact.birthday()),
        "urls": _labeled_values(contact.urlAddresses()),
    }


def _split_name(name: str) -> tuple[str, str, str]:
    """First word is given, last is family, anything between is middle — a
    heuristic, but the same one most contact-import tools use. `str.split()`
    with no argument also collapses repeated/leading/trailing whitespace, so
    "Ada  Lovelace" doesn't leak a leading space into family_name."""
    parts = name.split()
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def _apply_dict(mutable, contact: dict) -> None:
    given, middle, family = _split_name(contact["name"])
    mutable.setGivenName_(given)
    mutable.setMiddleName_(middle)
    mutable.setFamilyName_(family)
    mutable.setNickname_(contact.get("nickname") or "")
    mutable.setOrganizationName_(contact.get("organisation") or "")
    mutable.setJobTitle_(contact.get("job_title") or "")
    mutable.setEmailAddresses_([
        cn.make_labeled_value(_resolve_label(e.get("label", "home")), e["value"])
        for e in contact.get("emails") or []
    ])
    mutable.setPhoneNumbers_([
        cn.make_labeled_value(_resolve_label(p.get("label", "home")), cn.make_phone_number(p["value"]))
        for p in contact.get("phones") or []
    ])
    mutable.setPostalAddresses_([
        cn.make_labeled_value(_resolve_label(a.get("label", "home")), cn.make_postal_address(
            a.get("street", ""), a.get("city", ""), a.get("state", ""),
            a.get("postal_code", ""), a.get("country", ""),
        ))
        for a in contact.get("addresses") or []
    ])
    mutable.setUrlAddresses_([
        cn.make_labeled_value(_resolve_label(u.get("label", "home")), u["value"])
        for u in contact.get("urls") or []
    ])
    mutable.setBirthday_(_birthday_to_components(contact["birthday"]) if contact.get("birthday") else None)


def _adopt(contact) -> dict:
    id = new_id()
    _sidecar.put(id, contact.identifier())
    return _contact_to_dict(contact, id)


def get(id: str) -> dict | None:
    cn_identifier = _sidecar.by_id(id)
    if cn_identifier is None:
        return None
    contact = cn.contact_by_identifier(_store, cn_identifier)
    if contact is None:
        # Deleted natively (outside `delete`) since we last saw it — forget the mapping.
        _sidecar.delete_row(id)
        return None
    return _contact_to_dict(contact, id)


def list_contacts() -> list[dict]:
    live = cn.fetch_all_contacts(_store)
    seen_cn_identifiers = set()
    results = []

    for contact in live:
        cn_identifier = contact.identifier()
        seen_cn_identifiers.add(cn_identifier)
        id = _sidecar.by_cn_identifier(cn_identifier)
        results.append(_adopt(contact) if id is None else _contact_to_dict(contact, id))

    for id, cn_identifier in _sidecar.all():
        if cn_identifier not in seen_cn_identifiers:
            # Sidecar knows this contact but it's no longer live — deleted natively.
            _sidecar.delete_row(id)

    results.sort(key=lambda c: c["name"].lower())
    return results


def upsert(contact: dict) -> dict:
    # A company contact (Contacts.app allows these) has no given/family name at
    # all — organisation is its only identifying field. Require at least one.
    if not (contact.get("name") or "").strip() and not (contact.get("organisation") or "").strip():
        raise ValueError("name or organisation is required")

    id = contact["id"]
    cn_identifier = _sidecar.by_id(id)
    existing = cn.contact_by_identifier(_store, cn_identifier) if cn_identifier else None
    is_new = existing is None
    mutable = existing.mutableCopy() if existing is not None else cn.new_contact()

    _apply_dict(mutable, contact)
    cn.save_contact(_store, mutable, is_new)
    new_cn_identifier = mutable.identifier()
    _sidecar.put(id, new_cn_identifier)
    saved = cn.contact_by_identifier(_store, new_cn_identifier)
    return _contact_to_dict(saved, id)


def delete(id: str) -> bool:
    cn_identifier = _sidecar.by_id(id)
    if cn_identifier is None:
        return False
    cn.remove_contact(_store, cn_identifier)
    _sidecar.delete_row(id)
    return True
