# Design: Pluggable secret store for the Jira OAuth2 client secret

**Date:** 2026-07-29
**Status:** Draft — awaiting review
**Author:** Bastian (with Claude)

## Problem

The configuration wizard currently writes the Jira OAuth2 client secret to a
plaintext `.env` file in the working directory (`store_client_secret_in_env` in
`utils/config_wizard.py`) and tells the user to keep it out of version control. This has
two weaknesses:

1. **Location** — the `.env` lands in the working directory (the repo checkout), one
   `git add .` away from being committed and inheriting the directory's permissions.
2. **At-rest protection** — the secret is plaintext.

We want a secret store that is **encrypted/protected at rest** and works on the two
deployment targets we care about:

- **Linux, systemd, headless bare-metal/VM servers** (primary production target)
- **Windows** (also a production target)

No single OS mechanism covers both a headless Linux server and Windows, so the design
introduces a small pluggable abstraction with platform-specific backends.

## Goals / Non-goals

**Goals**
- Encrypted-at-rest storage of the Jira OAuth2 client *secret* on Linux (systemd) and
  Windows.
- Keep the plaintext secret out of the generated TOML config (already true) and out of
  the working directory.
- Graceful degradation: `.env` remains a universal fallback for dev / non-systemd /
  unsupported setups. Existing installs keep working.
- Runtime resolution that still honours an injected `JIRA_OAUTH2_CLIENT_SECRET`
  environment variable (Docker, CI, manual override).

**Non-goals**
- Migrating the *other* sensitive fields (basic password, token, oauth1 secrets) into the
  store. The interface is designed to allow it later, but only the OAuth2 client secret is
  wired in this change.
- Managing the client *id* (`oauth2_client_id`) — it is not secret and stays in
  config/env.
- An external secret manager (Vault, AWS Secrets Manager). Out of scope.
- macOS as a first-class deploy target (the keyring backend will happen to work there, but
  it is not a tested target).

## Decisions (settled during brainstorming)

| Topic | Decision |
|---|---|
| Linux backend | `systemd-creds` encrypted credential, `.cred` file referenced via `LoadCredentialEncrypted=` |
| Linux key binding | `--with-key=auto` (TPM2 if present, else host key), **no PCR pinning** |
| Windows backend | Windows Credential Manager via the `keyring` library (per-user / DPAPI) |
| Windows service account | Unknown for now → design keyring (per-user) as default; document machine-scope DPAPI as a future alternative |
| `.env` mode | Kept as a universal fallback; not removed |
| Wizard root/permission handling (Linux) | Encrypt directly when root + `systemd-creds` present; otherwise print exact commands + unit snippet |
| `keyring` dependency | Added as a **base** dependency |
| Backend selection persistence | New non-sensitive config field `client_secret_store` written to TOML |

## Architecture

### New module: `utils/secret_store.py`

Defines the abstraction and the concrete backends. Methods take a logical credential
*key* so the store is reusable for other secrets later, but only
`jira_oauth2_client_secret` is wired now.

```python
CredentialKey = str  # e.g. "jira_oauth2_client_secret"

class SecretStore(Protocol):
    name: str  # persisted identifier: "systemd-creds" | "keyring" | "env"

    def available(self) -> bool:
        """True if this backend can be used on the current host."""

    def store(self, key: CredentialKey, secret: str) -> StoreResult:
        """Persist the secret (wizard-time). May print guidance / manual commands.
        Raises SecretStoreError on hard failure (never silently downgrades)."""

    def load(self, key: CredentialKey) -> str | None:
        """Retrieve the secret (runtime). Returns None when absent."""
```

`StoreResult` carries whether the secret was actually persisted vs. whether the user must
run manual commands (Linux non-root case), plus any message already printed. A
`SecretStoreError` type signals hard failures so the wizard fails closed.

`get_secret_store(name: str) -> SecretStore` and
`default_store_name() -> str` (best available backend for the current platform) are the
module entry points.

### Backends

| Backend | `name` | `available()` | At-rest protection | Bound to |
|---|---|---|---|---|
| `SystemdCredsStore` | `systemd-creds` | Linux **and** `shutil.which("systemd-creds")` | TPM/host-key encrypted `.cred` | that host |
| `KeyringStore` | `keyring` | `keyring` importable **and** a working (non-fail, non-null) backend | Windows Credential Manager (DPAPI) | that host **+ user account** |
| `EnvFileStore` | `env` | always | none (filesystem permissions only) | file |

#### `SystemdCredsStore`

Constants:
- `CREDENTIAL_ID = "jira_oauth2_client_secret"`
- default blob path: `/etc/testbench-defect-service/jira_oauth2_client_secret.cred`
- default unit drop-in path (printed, not auto-written):
  `/etc/systemd/system/testbench-defect-service.service.d/credentials.conf`

`store()`:
1. If root and `systemd-creds` present:
   - Ensure `/etc/testbench-defect-service/` exists (`0700`, `root:root`).
   - Run
     `systemd-creds encrypt --name=jira_oauth2_client_secret --with-key=auto - <blob_path>`
     with the plaintext piped via **stdin** (`subprocess.run(input=secret, text=True, check=True)`).
     The secret never touches argv or a temp file.
   - `chmod 0600` / `chown root:root` the blob.
   - Print the drop-in snippet + `systemctl daemon-reload && systemctl restart <unit>`.
   - Return `StoreResult(persisted=True)`.
2. If not root, or `systemd-creds` missing: print the exact manual commands (with a
   `YOUR_CLIENT_SECRET` placeholder — **never** the real secret) and the drop-in snippet,
   and return `StoreResult(persisted=False, manual=True)`. The wizard still records
   `client_secret_store="systemd-creds"` because that is where the secret will live once
   the admin runs the commands.
3. On `systemd-creds` non-zero exit: raise `SecretStoreError` (surface stderr). Do **not**
   fall back to writing plaintext.

`load()`: read `$CREDENTIALS_DIRECTORY/<CREDENTIAL_ID>`, `rstrip("\n")` only (systemd
stores exactly the bytes we encrypted; we encrypt without a trailing newline). Returns
`None` if `$CREDENTIALS_DIRECTORY` is unset or the file is missing.

Drop-in snippet emitted:
```ini
[Service]
LoadCredentialEncrypted=jira_oauth2_client_secret:/etc/testbench-defect-service/jira_oauth2_client_secret.cred
```

#### `KeyringStore`

- Service/namespace: `SERVICE_NAME = "testbench-defect-service"`.
- `store()`: `keyring.set_password(SERVICE_NAME, key, secret)`.
- `load()`: `keyring.get_password(SERVICE_NAME, key)`.
- `available()`: import succeeds and the active backend is not the `fail` or `null`
  backend (guard against a headless Linux box with no Secret Service — there we prefer
  systemd-creds or env, never keyring).
- **Backend pinning for PyInstaller:** explicitly select the Windows backend rather than
  relying on entry-point discovery (which the frozen binary strips):
  ```python
  import keyring.backends.Windows
  keyring.set_keyring(keyring.backends.Windows.WinVaultKeyring())
  ```
  Done lazily inside `KeyringStore` on Windows so non-Windows imports don't fail.

#### `EnvFileStore`

Current behaviour, refactored behind the interface:
- `store()`: `set_key(dotenv_path, JIRA_OAUTH2_CLIENT_SECRET, secret)` + `os.environ[...] = secret`; print the "keep out of version control" guidance.
- `load()`: return `os.getenv("JIRA_OAUTH2_CLIENT_SECRET")` (dotenv is already loaded elsewhere at startup).
- `available()`: always `True`.

### Runtime resolution (`clients/jira/config.py`)

Add a **non-sensitive** field to `JiraDefectClientConfig`:

```python
client_secret_store: Literal["env", "systemd-creds", "keyring"] | None = Field(
    None,
    description="Which backend stores the OAuth2 client secret; used at runtime to load it.",
    json_schema_extra={"skip_if_wizard": True},  # set programmatically by the wizard
)
```

Extend `_resolve_oauth2_client_credentials` precedence for the secret:

```
1. explicit config value (self.oauth2_client_secret)         # discouraged
2. os.getenv("JIRA_OAUTH2_CLIENT_SECRET")                    # universal override/injection
3. get_secret_store(self.client_secret_store).load(CREDENTIAL_ID)  # if client_secret_store set
```

Rationale: the env var stays the universal escape hatch (Docker/K8s secrets, systemd
`EnvironmentFile=`, CI, manual), so injection-based deploys keep working regardless of the
recorded backend. The store is the persistent home when nothing is injected. The client
*id* resolution is unchanged.

### Wizard (`utils/config_wizard.py`)

Replace the direct `store_client_secret_in_env` call for Jira with:

1. Determine the candidate stores and `default_store_name()` for the platform.
2. Prompt (`questionary.select`): *"How should the Jira OAuth2 client secret be stored?"*
   - Choices limited to `available()` backends, defaulting to the platform best
     (systemd-creds on systemd Linux, keyring on Windows, else env).
3. `store.store(CREDENTIAL_ID, secret)` — prints backend-specific guidance.
4. Record `client_config["client_secret_store"] = store.name`.
5. Pop `oauth2_client_secret` from `client_config` (unchanged) so it never enters TOML.
6. On `SecretStoreError`, report and re-prompt (do not silently fall back to plaintext).

## Dependencies & packaging

- Add `keyring` to `[project].dependencies` in `pyproject.toml`. Pin a range once the
  exact current transitive deps of the Windows backend are verified (recent `keyring`
  ships a ctypes-based Windows backend; confirm whether `pywin32-ctypes` is pulled in).
- **PyInstaller:** the build spec must include the keyring Windows backend module as a
  hidden import (or rely on the explicit `set_keyring` pin above and add
  `keyring.backends.Windows` to `hiddenimports`). Without this the frozen binary finds no
  backend and `load()` returns `None`. Verify against the existing PyInstaller spec during
  implementation.

## Operational caveats (to document in `docs/clients/jira-client.md`)

- **Linux:** the encrypted blob is host-bound. Migrating/rebuilding the host requires
  re-running the encrypt step. No PCR pinning, so kernel/firmware updates do not lock you
  out.
- **Windows:** the Credential Manager entry is **per-user (DPAPI)**. The secret is stored
  under the account that ran the wizard; **the service must run under that same account**
  to decrypt it. If the service runs as `LocalSystem`, a gMSA, or a rotating account,
  per-user keyring will not work — a machine-scope DPAPI backend (encrypted blob +
  `CRYPTPROTECT_LOCAL_MACHINE`, via `pywin32`/`ctypes`) is the alternative and is left as a
  documented future extension.
- **Env override everywhere:** setting `JIRA_OAUTH2_CLIENT_SECRET` always wins, which is
  the recommended path for container/orchestrated deploys.

## Testing

**Unit (CI-friendly, no systemd / no real keyring):**
- `SystemdCredsStore.load`: missing `$CREDENTIALS_DIRECTORY` → `None`; file present →
  value with trailing newline stripped.
- `SystemdCredsStore.store`: root branch calls `subprocess.run` with the secret passed via
  `input=` (mocked); not-root branch prints instructions and does **not** invoke
  subprocess; non-zero exit raises `SecretStoreError` and writes no `.env`.
- `KeyringStore.store`/`load`: `keyring` mocked; verifies service name + key; unavailable
  backend → `available()` is False.
- `EnvFileStore`: store writes env + dotenv, load reads env; behaviour parity with today.
- `_resolve_oauth2_client_credentials`: full precedence matrix (config value > env >
  store) including each `client_secret_store` value.
- Wizard: mode selection restricted to available backends; records `client_secret_store`;
  strips `oauth2_client_secret` from config in every mode; `SecretStoreError` re-prompts.

**Manual / integration (documented, not in CI):**
- Real `systemd-creds encrypt` + `LoadCredentialEncrypted` on a systemd host (CI is not
  root and has no systemd).
- Real Windows Credential Manager round-trip under a service account.
- Frozen PyInstaller binary on Windows actually loads the keyring backend.

## Files touched

- `src/testbench_defect_service/utils/secret_store.py` — **new**
- `src/testbench_defect_service/utils/config_wizard.py` — wire the store; keep/relocate
  the `.env` logic behind `EnvFileStore`
- `src/testbench_defect_service/clients/jira/config.py` — `client_secret_store` field +
  runtime resolution
- `pyproject.toml` — add `keyring` dependency
- PyInstaller spec — hidden imports for the keyring backend
- `docs/clients/jira-client.md` — document backends + caveats
- `CHANGELOG.md` — entry
- Tests under `tests/unit/…` — new `test_secret_store.py`, updates to
  `test_config_wizard.py` and `test_config.py`

## Open items to confirm during implementation

- Exact `keyring` version pin and its Windows transitive dependencies.
- The systemd **unit name** assumed in the printed snippet (`testbench-defect-service`);
  make it a constant, and consider printing the resolved unit name if detectable.
- Whether to offer a confirm-gated "write the systemd drop-in for me" when root (default:
  print only).
