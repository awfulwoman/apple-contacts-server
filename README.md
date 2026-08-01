# apple-contacts-server

A small authorised REST API in front of the real macOS Contacts app (via the
`Contacts` framework/`CNContactStore`), so [`gateway`](https://github.com/awfulwoman/gateway)'s
contacts can be backed by the Contacts app the user actually uses — on any device,
via Siri, or the Contacts UI — instead of a CardDAV store nothing else syncs with.
It replaces Radicale as gateway's contacts backend (mirrors how
[`apple-reminders-server`](https://github.com/awfulwoman/apple-reminders-server)
replaced Radicale for reminders). Runs on **Malcolm** (`apple-macmini-m4-16gb-malcolm`),
the always-on Mac.

## Why a sidecar database

`CNContact.identifier` is system-assigned, not client-choosable, so Gateway's own
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
daemon never sees the prompt. In production this is installed by the infra role
`system-apple-contacts-server` instead of the script above.

### Why the interpreter is code-signed (permission stability)

macOS TCC grants Contacts access to a **code identity**. An unsigned or
ad-hoc-signed Python interpreter is identified only by its `cdhash`, which changes
on every `uv sync`, venv rebuild, or Python patch bump — so the grant silently
reverts to *denied*, and a headless LaunchAgent can never re-prompt. That was the
cause of the same "permission randomly drops" failure class documented in
`apple-reminders-server`.

The fix, identical in shape to `apple-reminders-server`:

- **`install_service.sh` no longer launches via `uv run`.** `uv run` re-resolves
  the venv and can swap the interpreter at launch. The plist now execs the venv
  interpreter directly (`.venv/bin/python3 -m apple_contacts_server.main`).
- **The interpreter is signed with a stable identity.**
  `scripts/setup_signing_cert.sh` creates a long-lived self-signed code-signing
  cert once (in the login keychain of the user the agent runs as);
  `scripts/sign_runtime.sh` signs the interpreter with a fixed identifier
  (`com.awfulwoman.apple-contacts-server`). TCC then matches on the Designated
  Requirement (identifier + cert) instead of the cdhash, so the grant **survives
  rebuilds and upgrades**. Re-run `sign_runtime.sh` after any manual rebuild; the
  infra role runs it on every deploy.
- **`.python-version` is pinned to an exact patch** so uv stops auto-swapping the
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

The contact dict shape (`id`, `name`, `nickname`, `organisation`, `job_title`,
`emails`, `phones`, `addresses`, `birthday`, `urls`) matches gateway's own
`tools/contacts.py` — see
`gateway/docs/superpowers/specs/2026-07-19-radicale-contacts-reminders-design.md`
for the original vCard-backed design this backend swap builds on. `birthday` is
`YYYY-MM-DD`, or `--MM-DD` for a year-less birthday (Contacts.app supports both).

## Testing

```bash
uv run pytest
```

`Contacts` calls are mocked (`tests/conftest.py`'s `FakeContacts`) — no permission
prompt, no real Contacts data touched. `apple_contacts_server/contacts_client.py`
is the only module that imports `Contacts` directly, kept thin so it's the one
thing that needs occasional live verification against real Contacts.app.
