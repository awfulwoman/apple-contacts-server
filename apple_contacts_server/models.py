"""Request-body schema for `PUT /contacts/{id}`.

Type validation only. Everything downstream — `store._apply_dict` in particular —
hands values straight to the Contacts framework, so an unvalidated body doesn't
just crash: `{"emails": "ada@example.com"}` iterates the *string* and writes
fifteen single-character email addresses into the user's real address book. The
model exists so malformed input is a 400 before it can reach `CNSaveRequest`.

Deliberately *not* enforced here (left to `store.upsert`): non-empty `name`.
"""
from __future__ import annotations
import re
from datetime import date
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

# `store._birthday_to_components` accepts exactly these two shapes (full date,
# or `--MM-DD` for a year-less birthday, matching Contacts.app).
_FULL_BIRTHDAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEARLESS_BIRTHDAY_RE = re.compile(r"^--\d{2}-\d{2}$")


def _validate_birthday(v: str) -> str:
    if _YEARLESS_BIRTHDAY_RE.match(v):
        month, day = int(v[2:4]), int(v[5:7])
        try:
            date(2000, month, day)  # 2000: a leap year, so Feb 29 is valid here too
        except ValueError as e:
            raise ValueError(f"not a valid calendar date: {v!r} ({e})") from e
        return v
    if _FULL_BIRTHDAY_RE.match(v):
        year, month, day = int(v[:4]), int(v[5:7]), int(v[8:10])
        try:
            date(year, month, day)
        except ValueError as e:
            raise ValueError(f"not a valid calendar date: {v!r} ({e})") from e
        return v
    raise ValueError(f"birthday must be YYYY-MM-DD or --MM-DD, got {v!r}")


class Address(BaseModel):
    model_config = ConfigDict(extra="ignore")

    street: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""


class ContactBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    nickname: str = ""
    organisation: str = ""
    job_title: str = ""
    emails: list[str] = []
    phones: list[str] = []
    addresses: list[Address] = []
    birthday: str | None = None
    urls: list[str] = []

    # An explicit JSON `null` for a scalar/list field means "empty", not "wrong
    # type" — a client clearing a field shouldn't get a 400.
    @field_validator("nickname", "organisation", "job_title", mode="before")
    @classmethod
    def _null_to_empty_string(cls, v):
        return "" if v is None else v

    @field_validator("emails", "phones", "addresses", "urls", mode="before")
    @classmethod
    def _null_to_empty_list(cls, v):
        return [] if v is None else v

    # `store.upsert` already treats "" the same as no birthday (a falsy check),
    # so an empty string clears the field rather than failing validation.
    @field_validator("birthday")
    @classmethod
    def _check_birthday(cls, v):
        if not v:
            return None
        return _validate_birthday(v)


def format_validation_error(exc: ValidationError) -> str:
    """Flatten pydantic's multi-line report into one line for the JSON error body."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(p) for p in error["loc"]) or "body"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
