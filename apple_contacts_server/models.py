"""Request-body schema for `PUT /contacts/{id}`.

Type validation only. Everything downstream — `store._apply_dict` in particular —
hands values straight to the Contacts framework, so an unvalidated body doesn't
just crash: `{"emails": "ada@example.com"}` iterates the *string* and writes
fifteen single-character email addresses into the user's real address book. The
model exists so malformed input is a 400 before it can reach `CNSaveRequest`.

Deliberately *not* enforced here (left to `store`, or not yet enforced at all):
non-empty `name`, and `birthday` calendar validity — `birthday` is checked only
for being a string.
"""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


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


def format_validation_error(exc: ValidationError) -> str:
    """Flatten pydantic's multi-line report into one line for the JSON error body."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(p) for p in error["loc"]) or "body"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
