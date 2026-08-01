from __future__ import annotations
import hmac
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from apple_contacts_server import store
from apple_contacts_server.config import Config

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


async def _json_body(request: Request) -> tuple[dict, JSONResponse | None]:
    try:
        return (await request.json()), None
    except Exception:
        return {}, _err(400, "invalid_json", "body must be valid JSON")


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
    body["id"] = request.path_params["id"]
    try:
        stored = store.upsert(body)
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
