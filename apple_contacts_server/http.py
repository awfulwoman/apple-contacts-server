from __future__ import annotations
import hmac
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from pydantic import ValidationError
from apple_contacts_server import store
from apple_contacts_server.config import Config
from apple_contacts_server.models import ContactBody, format_validation_error

_config: Config | None = None


def init(config: Config) -> None:
    global _config
    _config = config


def _authorized(request: Request) -> bool:
    if not _config or not _config.bearer_tokens:
        return False
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return False
    token = header[len("Bearer "):]
    return any(hmac.compare_digest(token, t) for t in _config.bearer_tokens)


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


async def _json_body(request: Request) -> tuple[object, JSONResponse | None]:
    """Returns whatever JSON the body decodes to — not necessarily a dict; shape
    is `ContactBody`'s problem."""
    try:
        return (await request.json()), None
    except Exception:
        return None, _err(400, "invalid_json", "body must be valid JSON")


async def get_contacts(request: Request) -> JSONResponse:
    if not _authorized(request):
        return _err(401, "unauthorized", "missing or invalid bearer token")
    return JSONResponse({"contacts": store.list_contacts()})


async def get_contact(request: Request) -> JSONResponse:
    if not _authorized(request):
        return _err(401, "unauthorized", "missing or invalid bearer token")
    id = request.path_params["id"]
    contact = store.get(id)
    if contact is None:
        return _err(404, "not_found", f"no contact with id {id!r}")
    return JSONResponse(contact)


async def put_contact(request: Request) -> JSONResponse:
    if not _authorized(request):
        return _err(401, "unauthorized", "missing or invalid bearer token")
    body, error = await _json_body(request)
    if error:
        return error
    try:
        contact = ContactBody.model_validate(body)
    except ValidationError as e:
        return _err(400, "validation_error", format_validation_error(e))

    # The path is authoritative for the id; any `id` in the body is ignored.
    payload = contact.model_dump()
    payload["id"] = request.path_params["id"]
    try:
        stored = store.upsert(payload)
    except (ValueError, KeyError) as e:
        return _err(400, "validation_error", str(e))
    return JSONResponse(stored)


async def delete_contact(request: Request) -> JSONResponse:
    if not _authorized(request):
        return _err(401, "unauthorized", "missing or invalid bearer token")
    id = request.path_params["id"]
    if not store.delete(id):
        return _err(404, "not_found", f"no contact with id {id!r}")
    return JSONResponse({"status": "deleted", "id": id})


routes: list[Route] = [
    Route("/contacts", get_contacts, methods=["GET"]),
    Route("/contacts/{id}", get_contact, methods=["GET"]),
    Route("/contacts/{id}", put_contact, methods=["PUT"]),
    Route("/contacts/{id}", delete_contact, methods=["DELETE"]),
]


def create_app() -> Starlette:
    return Starlette(routes=routes)
