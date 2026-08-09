from __future__ import annotations
import hmac
import logging
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from pydantic import ValidationError
from apple_contacts_server import store
from apple_contacts_server.config import Config
from apple_contacts_server.models import ContactBody, format_validation_error

logger = logging.getLogger("apple_contacts_server")

_config: Config | None = None

_CODE_BY_STATUS = {404: "not_found", 405: "method_not_allowed"}


def init(config: Config) -> None:
    global _config
    _config = config


def _authorized(request: Request) -> bool:
    if not _config or not _config.bearer_tokens:
        return False
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    # Compare as bytes: `hmac.compare_digest` raises TypeError on a non-ASCII
    # `str`, which would otherwise turn an attacker-controlled header into a 500.
    token_bytes = token.encode("utf-8")
    return any(hmac.compare_digest(token_bytes, t.encode("utf-8")) for t in _config.bearer_tokens)


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
    contacts = await run_in_threadpool(store.list_contacts)
    return JSONResponse({"contacts": contacts})


async def get_contact(request: Request) -> JSONResponse:
    if not _authorized(request):
        return _err(401, "unauthorized", "missing or invalid bearer token")
    id = request.path_params["id"]
    contact = await run_in_threadpool(store.get, id)
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
        stored = await run_in_threadpool(store.upsert, payload)
    except (ValueError, KeyError) as e:
        return _err(400, "validation_error", str(e))
    return JSONResponse(stored)


async def delete_contact(request: Request) -> JSONResponse:
    if not _authorized(request):
        return _err(401, "unauthorized", "missing or invalid bearer token")
    id = request.path_params["id"]
    if not await run_in_threadpool(store.delete, id):
        return _err(404, "not_found", f"no contact with id {id!r}")
    return JSONResponse({"status": "deleted", "id": id})


routes: list[Route] = [
    Route("/contacts", get_contacts, methods=["GET"]),
    Route("/contacts/{id}", get_contact, methods=["GET"]),
    Route("/contacts/{id}", put_contact, methods=["PUT"]),
    Route("/contacts/{id}", delete_contact, methods=["DELETE"]),
]


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette's own routing errors (404/405) raise HTTPException, which by
    default renders as a plain-text body — a different shape to every handler
    error above. Route it through the same {"error": {"code", "message"}} envelope."""
    code = _CODE_BY_STATUS.get(exc.status_code, "http_error")
    return _err(exc.status_code, code, str(exc.detail))


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything store/contacts_client raises that a handler didn't anticipate
    (AccessDenied, SaveFailed, a revoked TCC grant) would otherwise reach the
    client as a bare 500 with no body a caller can parse."""
    logger.exception("unhandled error handling %s %s", request.method, request.url.path)
    return _err(500, "internal_error", str(exc) or type(exc).__name__)


def create_app() -> Starlette:
    return Starlette(
        routes=routes,
        exception_handlers={
            StarletteHTTPException: _http_exception_handler,
            Exception: _unhandled_exception_handler,
        },
    )
