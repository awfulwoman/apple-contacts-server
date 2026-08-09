# apple-contacts-server

A small authorised REST API in front of the real macOS Contacts app (via the
`Contacts` framework/`CNContactStore`), so client applications can read and write
the Contacts the user actually uses — on any device, via Siri, or the Contacts UI —
instead of a CardDAV store nothing else syncs with. It's the sibling of
[`apple-reminders-server`](https://github.com/awfulwoman/apple-reminders-server) and
[`apple-calendar-server`](https://github.com/awfulwoman/apple-calendar-server) and
follows the same principles (thin framework wrapper, sidecar SQLite for
bookkeeping, native-edit adoption, stable code-signed interpreter).

## Why a sidecar database

`CNContact.identifier` is system-assigned, not client-choosable, so a caller's own
`id` still needs somewhere to live. `apple_contacts_server/sidecar.py` keeps a small
local SQLite table — `id ↔ identifier`, nothing else — purely for that mapping. The
contact *content* always lives in the real Contacts.app; the sidecar is never
authoritative for it.

Unlike [`apple-reminders-server`](https://github.com/awfulwoman/apple-reminders-server),
there's no offline-sync client for contacts today, so this is deliberately simpler
than the reminders sidecar: no `updated_at`/LWW, no tombstones. Writes are plain
last-write-wins and deletes are real `CNContact` deletes. See `store.py`'s module
docstring if that ever needs to change.

Because of this, contacts created outside the API (Contacts.app, Siri, another
device) are transparently **adopted** the first time they're observed — see the
`store.py` module docstring.

## Running locally

```bash
uv sync
cp .env.example .env   # set CONTACTS_SERVER_BEARER_TOKENS at minimum
uv run apple-contacts-server
```

First run triggers a macOS permission dialog for Contacts access — approve it once.

## Installing as a LaunchAgent

```bash
./scripts/install_service.sh    # ./scripts/uninstall_service.sh to remove
```

Must run as a **LaunchAgent** (`gui/<uid>` domain), not a LaunchDaemon — Contacts'
TCC permission is granted per logged-in user in a GUI session; a root-owned system
daemon never sees the prompt. In practice that means running it on a Mac that stays
logged into a GUI session — a headless box can never hold the grant.

### Why the interpreter is code-signed (permission stability)

macOS TCC grants Contacts access to a **code identity**. An unsigned or
ad-hoc-signed Python interpreter is identified only by its `cdhash`, which changes
on every `uv sync`, venv rebuild, or Python patch bump — so an interpreter signed
that way would have its grant silently revert to *denied* on the next rebuild, and
a headless LaunchAgent can never re-prompt to recover it.

To keep the grant stable across rebuilds (same approach as apple-reminders-server):

- **The LaunchAgent execs the venv interpreter directly**
  (`.venv/bin/python3 -m apple_contacts_server.main`), not via `uv run` — `uv run`
  re-resolves the venv and can swap the interpreter out from under it, changing
  its identity.
- **The interpreter is signed with a stable identity.**
  `scripts/setup_signing_cert.sh` creates a long-lived self-signed code-signing
  cert once (in the login keychain of the user the agent runs as);
  `scripts/sign_runtime.sh` signs the interpreter with a fixed identifier
  (`com.awfulwoman.apple-contacts-server`). TCC then matches on the Designated
  Requirement (identifier + cert) instead of the cdhash, so the grant **survives
  rebuilds and upgrades**. Re-run `sign_runtime.sh` after any manual rebuild.
- **`.python-version` is pinned to an exact patch** so uv doesn't swap the
  interpreter underneath the grant.

You still approve Contacts access **once** at first launch
(System Settings › Privacy & Security › Contacts). After that it persists.

## API

All endpoints require `Authorization: Bearer <token>` (one of
`CONTACTS_SERVER_BEARER_TOKENS`).

| Method | Path | |
|---|---|---|
| GET | `/contacts` | List all contacts |
| GET | `/contacts/{id}` | Fetch one |
| PUT | `/contacts/{id}` | Create (unknown id) or update (known id) |
| DELETE | `/contacts/{id}` | Delete |

The contact dict shape is `id`, `name`, `nickname`, `organisation`, `job_title`,
`emails`, `phones`, `addresses`, `birthday`, `urls` — chosen to round-trip cleanly
with a vCard 4.0 representation, since that's the most common interchange format
for contacts. `birthday` is `YYYY-MM-DD`, or `--MM-DD` for a year-less birthday
(Contacts.app supports both).

`PUT` bodies are validated against `apple_contacts_server/models.py` before
anything reaches the Contacts framework; a wrong type, or a `birthday` that
isn't a real calendar date, is a `400` with
`{"error": {"code": "validation_error", "message": …}}`. Only `name` is required
— omitted fields take their empty default, and an explicit `null` (or, for
`birthday`, an empty string) clears a field. Any `id` in the body is ignored in
favour of the path.

## Testing

```bash
uv run pytest -m "not known_issues"   # the suite that should be green
uv run pytest                          # everything, including the known-issue tests
```

`Contacts` calls are mocked (`tests/conftest.py`'s `FakeContacts`) — no permission
prompt, no real Contacts data touched. `apple_contacts_server/contacts_client.py`
is the only module that imports `Contacts` directly, kept thin so it's the one
thing that needs occasional live verification against real Contacts.app.

`tests/test_known_issues.py` is **expected to fail**. It holds executable
descriptions of defects found in review but not yet fixed — currently, label
loss on a native contact's read-modify-write round-trip, and organisation-only
/ middle-name / repeated-space contacts not round-tripping cleanly. They're
deliberately not `xfail`-marked so a regression can't hide in them; see that
module's docstring for the full list, and delete each test as its defect is
fixed.
