# Branch Review Report: `support-oauth2` vs `origin/main`

**Reviewed on:** 2026-07-30
**Diff command used:** `git diff --merge-base origin/main HEAD` (split by path: `-- src tests` and `-- docs CHANGELOG.md`)
**Files changed:** 13
**Semgrep:** unavailable (MCP tool not connected, CLI not installed) — security review done manually with extra scrutiny given the OAuth2/credential focus of this branch
**Total findings (branch-introduced):** 9

---

## Executive Summary

This branch adds a second Jira OAuth2 flow (2LO / `client_credentials`, service-account) alongside the existing 3LO refresh-token flow, splits the `auth_type` config literal accordingly, stops persisting access tokens to disk, folds in a previously-unreviewed proxy-support branch, and adds a wizard feature that writes the OAuth2 client secret to `.env` instead of the config file. The core OAuth2/token-refresh logic is well tested and the new code is generally clean, but the `auth_type` literal rename is a breaking change shipped without any migration path or back-compat shim, and it silently breaks a sibling call site (`src/testbench_defect_service/config.py`) that still compares against the old `"oauth2"` string — the interactive "prompt for missing refresh token at startup" feature is now permanently dead for the 3LO flow. There is also a real (if narrow) double-checked-locking bug in the new 2LO token-minting path, and a security-relevant gap where the client secret this branch writes to `.env` is not covered by the CLI's secret-masking allowlist, so it can be echoed in cleartext by the `view` command. A pre-existing, unrelated bug was also found while reading `jira_client.py` in full: the shared/service connection path never applies `proxy_url` to the actual Jira API client (only per-user connections and the tenant-info lookup are proxied), which is worth flagging even though it predates this branch.

No prior review file existed for this branch before this run, so there is no "Prior findings resolution" section.

---

## Part 1: Issues Introduced by This Branch

> These findings are for code that was written or changed by this branch. The branch author is responsible for addressing these before merge.

---

### `src/testbench_defect_service/clients/jira/jira_oauth.py`

**[F3] [SEVERITY: MEDIUM]** — Double-checked lock recheck is dead code for `is_first_call=True` in the new 2LO path

- **Location:** `_is_cached_2lo_token_valid` (lines 220–228) and `_get_valid_client_credentials_token` (lines 231–246)
- **Confidence:** 🔴 Certain — provable from the code alone.
- **Issue:**

  ```python
  def _is_cached_2lo_token_valid(is_first_call: bool) -> str | None:
      if is_first_call:
          return None
      ...

  def _get_valid_client_credentials_token(is_first_call: bool) -> str:
      cached = _is_cached_2lo_token_valid(is_first_call)
      if cached is not None:
          return cached
      with refresh_lock_sync:
          # Re-check inside the lock in case another thread just minted a token.
          cached = _is_cached_2lo_token_valid(is_first_call)
          if cached is not None:
              return cached
          data = _mint_client_credentials_token_sync()
          ...
  ```

  Both the outer check and the "re-check inside the lock" call `_is_cached_2lo_token_valid` with the **same** `is_first_call` value. When `is_first_call=True` (the value used at `JiraClient` construction time, in `_connect_via_gateway`), the recheck *always* returns `None`, regardless of whether another thread just minted a perfectly valid token while this thread was waiting on `refresh_lock_sync`. The comment ("Re-check inside the lock in case another thread just minted a token") is therefore incorrect for exactly the call site it was written for — concurrent first-time construction of a 2LO `JiraClient` (e.g. two requests racing to lazily initialize the shared `JiraDefectClient.jira_client` property, which is not itself lock-protected) will make two live token-mint HTTP calls to Atlassian instead of one. This doesn't corrupt state (both tokens are valid), but it defeats the purpose of the lock and wastes a network round-trip / rate-limit budget on every cold start under concurrency.
- **Category:** Bug (concurrency)
- **Missing Test:** No test exercises the "two concurrent first-calls" scenario; `test_mints_on_first_call` only checks the single-caller path.
- **Recommendation:** Pass `is_first_call=False` for the *inner* recheck (or better, drop the parameter from the recheck and always do a real cache-validity check inside the lock, only forcing a mint on the very first call site outside the lock):

  ```python
  with refresh_lock_sync:
      cached = _is_cached_2lo_token_valid(is_first_call=False)
      if cached is not None:
          return cached
      ...
  ```

**[F4] [SEVERITY: MEDIUM]** — Process-global, sticky `grant_type` limits the service to one OAuth2 client configuration per process

- **Location:** `_oauth2_settings` module-level dict (lines 37–41), `configure_oauth2_runtime` (lines 122–154), `get_valid_jira_token_sync` (lines 249–260)
- **Confidence:** 🟡 Medium — no correctness bug is triggered under the current single-`JiraDefectClient`-per-process architecture, but the design is fragile and the new `grant_type` field makes the existing global-state smell (already noted in this author's history) worse.
- **Issue:** `_oauth2_settings["grant_type"]` (new in this branch) is set once by whichever `configure_oauth2_runtime(...)` call happens to run last, and `get_valid_jira_token_sync` dispatches its *entire* behavior (2LO mint vs. 3LO refresh) off that single global flag. Today this is safe only because exactly one `JiraDefectClient`/`JiraClient` combination exists per process and `_connect_via_gateway()` configures the runtime exactly once at construction. But there is no structural guard preventing a future change (e.g. a second Jira tenant, or a per-project client with a different auth flow) from constructing a second `JiraClient` with a different `grant_type` and silently corrupting the shared `token_store`/`_oauth2_settings` for the first one — `get_valid_jira_token_sync` would then serve the wrong kind of token to the wrong client. The unit tests already have to manually poke `jira_oauth._oauth2_settings["grant_type"]` directly, which is itself a symptom of this being global mutable module state rather than instance state.
- **Category:** Code Quality / Design (Global mutable state)
- **Recommendation:** At minimum, document this single-instance assumption prominently at the top of the module (a docstring note), and consider gating `configure_oauth2_runtime` so it raises/logs loudly if called with a different `grant_type` than what's already configured (a "configuration changed unexpectedly" guard) rather than silently overwriting. Longer term, this state belongs on a per-`JiraClient` (or per-config) object rather than module globals, as flagged previously for this author's other OAuth work.

**[F5] [SEVERITY: LOW]** — Duplicated credential-validation logic between the two token-request functions

- **Location:** `_refresh_jira_token_sync` (lines 184–196) vs. `_mint_client_credentials_token_sync` (lines 199–217)
- **Confidence:** 🟢 Low — this is a minor readability nit, not a bug; the two functions build slightly different payloads so full unification may not be worth the abstraction.
- **Issue:** Both functions duplicate the `client_id = str(...); client_secret = str(...); if <missing/placeholder>: raise JiraAuthExpiredError(...)` block, with a subtly inconsistent check (`_refresh_jira_token_sync` only checks `_is_placeholder`, `_mint_client_credentials_token_sync` additionally checks `not client_id or not client_secret`). This is a small, latent "fixed it here but not there" risk if the placeholder-detection logic ever needs to change.
- **Category:** Code Duplication
- **Recommendation:** Extract a small `_require_client_credentials() -> tuple[str, str]` helper that both functions call, applying the same (more defensive) check in both places.

---

### `src/testbench_defect_service/utils/config_wizard.py`

**[F6] [SEVERITY: MEDIUM]** — Plaintext secret written to `.env` with no permission hardening; combines with a pre-existing masking gap into a real cleartext-exposure path

- **Location:** `store_client_secret_in_env` (lines 152–175)
- **Confidence:** 🟠 High
- **Issue:** `set_key(str(dotenv_path), JIRA_CLIENT_SECRET_ENV_VAR, secret)` writes the plaintext OAuth2 client secret to `.env` using python-dotenv's default file creation (no explicit `chmod`/`os.open(..., mode=0o600)`), so the file inherits the process umask (commonly world- or group-readable on Linux). More importantly, this newly-written `.env` entry is then displayable in cleartext by the pre-existing `view_env_config()` / `is_sensitive_config_key()` function — see F11 in Part 2, which is the concrete mechanism by which this new write path becomes a real disclosure. The accompanying design spec (`docs/superpowers/specs/2026-07-29-...md`) already correctly identifies "at-rest protection" and "location" as open problems for a *future* pluggable secret store, but doesn't mention the more immediate `view_env_config` masking gap this branch's own feature newly makes exploitable in practice, since previously it required a user to manually add the secret to `.env` themselves.
- **Category:** Security
- **Recommendation:** 1) Set restrictive permissions on the `.env` file after writing (`Path(dotenv_path).chmod(0o600)` on POSIX), matching the design spec's stated intent for the eventual `systemd-creds`/`keyring` backends. 2) Extend `is_sensitive_config_key`'s keyword set to include `"secret"`/`"client_secret"` so `view_env_config`/`view_client_config` mask it (see F11 — same fix serves both).

---

### `tests/unit/clients/jira/test_config.py`

**[F7] [SEVERITY: MEDIUM]** — `isolated_token_cache` fixture only isolates the disk cache, not the in-memory `jira_oauth` globals, creating order-dependent test fragility

- **Location:** `isolated_token_cache` fixture (lines 12–17)
- **Confidence:** 🟡 Medium — this is a latent fragility rather than a currently-observed failure; whether it bites depends on test collection/execution order.
- **Issue:** This fixture only patches `jira_oauth._TOKEN_CACHE_PATH`. It does **not** reset `jira_oauth.token_store` or `jira_oauth._oauth2_settings`, unlike the (better) `isolated_env` autouse fixture in `tests/unit/clients/jira/test_jira_oauth.py`, which snapshots and restores both dicts around every test. `TestOauth2ThreeLegged.test_requires_refresh_token` depends on `has_cached_refresh_token()` returning `False`, which in turn depends on `jira_oauth.token_store["refresh_token"]` still holding its pristine placeholder value — a global, shared, mutable piece of state that this file does nothing to guarantee. If test execution order changes (parallelization via `pytest-xdist`, explicit test selection, or a future test elsewhere in the suite that leaves a non-placeholder refresh token in `token_store` without cleaning it up), this test could silently start passing or failing for reasons unrelated to the code under test. Given the current within-directory alphabetical ordering (`test_config.py` before `test_jira_client.py`/`test_jira_oauth.py`), it happens to work today, but that's incidental, not structural.
- **Category:** Missing Test / Code Quality (test isolation)
- **Recommendation:** Have this fixture also snapshot/restore `jira_oauth.token_store` and `jira_oauth._oauth2_settings` (or better, import and reuse the `isolated_env` fixture from `test_jira_oauth.py` via a shared `conftest.py`), so this file's correctness doesn't depend on suite-wide execution order.

---

### `tests/unit/utils/test_config_wizard.py`

**[F8] [SEVERITY: LOW]** — Test mutates the real process environment without `monkeypatch` scoping

- **Location:** `test_exports_secret_to_process_environment` (implicitly, via `store_client_secret_in_env`'s `os.environ[JIRA_CLIENT_SECRET_ENV_VAR] = secret`)
- **Confidence:** 🟡 Medium — the `_clear_env` autouse fixture does clean up `JIRA_OAUTH2_CLIENT_SECRET` before each test in *this* file, so no failure is currently observed, but it only does so as pre-test setup, not post-test teardown, and only within this one module.
- **Issue:** `store_client_secret_in_env` writes directly to `os.environ[...]`, and the test asserts on that mutation. Because the assignment is a raw dict write rather than `monkeypatch.setenv(...)`, pytest's `monkeypatch` fixture cannot auto-revert it at teardown. The `_clear_env` fixture in this file happens to `delenv` the same key before every test, which papers over the leak *within this file*, but the mutation can still leak into any other test module that runs afterward in the same session and doesn't itself scrub `JIRA_OAUTH2_CLIENT_SECRET`.
- **Category:** Missing Test / Code Quality (test isolation)
- **Recommendation:** Use `monkeypatch.setenv`/rely on `monkeypatch`'s own cleanup where possible, or add a `_clear_env`-style teardown (not just setup) so the leaked value can't survive into unrelated test modules regardless of collection order.

**[F9] [SEVERITY: LOW]** — Test fixtures use ad-hoc `auth_type` strings that don't match the canonical constants

- **Location:** Lines 21, 32 — `{"auth_type": "oauth2_3lo", ...}` / `{"auth_type": "oauth2_2lo", ...}`
- **Confidence:** 🟢 Low — harmless today since `store_client_secret_in_env` doesn't branch on `auth_type` at all, but it's misleading test data.
- **Issue:** These values (`"oauth2_3lo"`, `"oauth2_2lo"`) don't match the real canonical `AUTH_OAUTH2_3LO`/`AUTH_OAUTH2_2LO` constants (`"oauth2 3LO (user account)"`/`"oauth2 2LO (service account)"`) defined in `clients/jira/config.py` and used everywhere else in this branch. A future reader skimming this test could reasonably (but incorrectly) conclude these are the real accepted values.
- **Category:** Code Quality
- **Recommendation:** Either import and use `AUTH_OAUTH2_2LO`/`AUTH_OAUTH2_3LO` from `clients.jira.config`, or use an unmistakably-fake value (e.g. `"irrelevant"`) since `auth_type` isn't actually exercised by the function under test.

---

## Files reviewed with no issues found

- `src/testbench_defect_service/clients/jira/client.py` (`JiraDefectClient`) — `is_oauth2()` substitution in `_resolve_jira_client` is correct and consistent with the rest of the file; full file read, no other concerns in the changed hunk.
- `src/testbench_defect_service/clients/jira/jira_client.py` — the `self._proxies` extraction and its use in `_fetch_cloud_id` is correct and covered by new tests (`TestFetchCloudId`); the 2LO/3LO dispatch in `_connect_via_gateway` (`GRANT_CLIENT_CREDENTIALS` vs `GRANT_REFRESH_TOKEN`, `expires_at=None if is_2lo else ...`) is logically sound. (A significant *pre-existing* proxy bug was found elsewhere in this same file — see F13 in Part 2.)
- `tests/unit/clients/jira/test_jira_client.py` — new `TestFetchCloudId` tests correctly assert `proxies` is passed/omitted for the tenant-info request.
- `tests/unit/clients/jira/test_jira_oauth.py` — good coverage of the new 2LO mint/cache/lock paths and the "only refresh token is persisted" behavior; the autouse `isolated_env` fixture correctly snapshots/restores both `token_store` and `_oauth2_settings` around every test (a positive pattern — see below).
- `tests/unit/utils/__init__.py` — empty marker file, nothing to review.
- `docs/clients/jira-client.md` — the OAuth2 sections are internally consistent, accurately describe the 2LO/3LO split, and no stale `"oauth2"` references remain.
- `docs/superpowers/specs/2026-07-29-jira-client-secret-secret-store-design.md` — a Draft design spec; internally consistent, and it does not contradict the shipped code (it correctly describes `store_client_secret_in_env` as the current behavior it intends to eventually replace).

---

## Part 1 Summary Table

| ID | Severity | File                                   | Short title                                                      |
| -- | -------- | -------------------------------------- | ---------------------------------------------------------------- |
| F1 | INFO     | CHANGELOG.md                           | Unreleased entry vs. staged 0.3.0 version bump                   |
| F2 | HIGH     | clients/jira/config.py                 | Breaking`auth_type` rename with no migration                   |
| F3 | MEDIUM   | clients/jira/jira_oauth.py             | Dead double-checked-lock recheck for`is_first_call=True` (2LO) |
| F4 | MEDIUM   | clients/jira/jira_oauth.py             | Sticky global`grant_type` limits to one OAuth2 client/process  |
| F5 | LOW      | clients/jira/jira_oauth.py             | Duplicated credential-validation logic                           |
| F6 | MEDIUM   | utils/config_wizard.py                 | Plaintext`.env` secret, no permission hardening                |
| F7 | MEDIUM   | tests/unit/clients/jira/test_config.py | Fixture doesn't isolate`jira_oauth` globals                    |
| F8 | LOW      | tests/unit/utils/test_config_wizard.py | Real`os.environ` mutation not scoped via monkeypatch           |
| F9 | LOW      | tests/unit/utils/test_config_wizard.py | Test auth_type literals don't match canonical constants          |

| Severity        | Count       |
| --------------- | ----------- |
| Critical        | 0           |
| High            | 1           |
| Medium          | 4           |
| Low             | 3           |
| Info            | 1           |
| **Total** | **9** |

---

## Positive Observations

- The `_load_token_store_from_disk`/`_persist_token_store_to_disk` rework (only persisting the refresh token, never the access token) is a genuine security improvement, and it's backed by thorough tests (`test_persists_refresh_token_only`, `test_seed_oauth2_refresh_token_writes_refresh_only_cache`, etc.).
- The `_post_oauth_token_request` extraction is a clean refactor: the 400/401 → `JiraAuthExpiredError` mapping and the "any other HTTP error propagates unchanged" behavior are preserved exactly, and the new docstring accurately describes it.
- `tests/unit/clients/jira/test_jira_oauth.py`'s autouse `isolated_env` fixture is a good pattern for isolating shared module-level mutable state (snapshot before, restore after) — worth using as the template to fix F7.
- The `dependency_matches` wizard helper already supported list-valued `depends_on.auth_type` (via `isinstance(expected, (list, tuple, set))`) before this branch needed it, so the new list-based `depends_on` for `oauth2_client_id`/`oauth2_client_secret` "just works" without any wizard changes — good reuse of existing generality, verified against `wizard.py`.
- New 2LO test coverage (`TestMintClientCredentialsTokenSync`, `TestGetValidJiraTokenSyncClientCredentials`) is solid for the happy paths and cache-expiry/placeholder edge cases.

---

## Recommended Actions Before Merge

1. **F2/F10 (breaking change):** Add a migration shim or at least a loud, documented breaking-change note for the `auth_type` rename, and fix the stale `"oauth2"` comparison in `src/testbench_defect_service/config.py` (F10) so the startup wizard prompt still works for 3LO.
2. **F3 (2LO double-checked lock):** Fix the inner recheck to not blindly return `None` for `is_first_call=True`.
3. **F6/F11 (secret masking):** Extend `is_sensitive_config_key` to cover `secret`/`client_secret`, and consider hardening `.env` file permissions after `store_client_secret_in_env` writes to it.
4. **F7 (test isolation):** Make `test_config.py`'s fixture reset `jira_oauth.token_store`/`_oauth2_settings` like `test_jira_oauth.py` already does, to remove order-dependence.
5. **F4 (sticky global state):** Not blocking, but document the single-instance assumption so a future multi-tenant change doesn't silently corrupt shared token state.
6. **F1/F5/F8/F9:** Low-cost cleanups, fine to batch into this PR or a fast-follow.

---

## Part 2: Pre-existing Issues Found While Reviewing

> These findings are for code that was **not introduced by this branch**. This includes issues in files not touched by this branch (read for context or duplication checks), and issues in files that were touched by this branch but in hunks that were **not changed**. The branch author is not obligated to fix these.

---

### `src/testbench_defect_service/clients/jira/jira_oauth.py`

**[F12] [SEVERITY: MEDIUM]** — Identical pre-existing double-checked-lock recheck defect in the 3LO path (mirrors F3)

- **Location:** `get_valid_jira_token_sync`, lines 262–274 (unchanged by this diff except for the `_post_oauth_token_request` extraction below it)
- **Confidence:** 🔴 Certain
- **Issue:** The same shape of bug flagged in F3 already existed in the pre-existing 3LO branch:

  ```python
  expires_at, access_token = _get_cached_token_data(fallback_token)
  if time.time() < (expires_at - 300) and access_token and not is_first_call:
      return access_token
  with refresh_lock_sync:
      _load_token_store_from_disk()
      expires_at, access_token = _get_cached_token_data(fallback_token)
      if time.time() < (expires_at - 300) and access_token and not is_first_call:
          return access_token
      ...
  ```

  When `is_first_call=True`, both the outer and inner (post-lock) checks are unconditionally bypassed via `and not is_first_call`, so two threads racing to establish the first connection will both perform a live refresh-token exchange against Atlassian, rather than the second one picking up the first one's freshly-cached token. This is not something this branch introduced or touched, but it's the same class of bug as F3 and worth fixing in one pass.
- **Category:** Bug (concurrency)
- **Recommendation:** Same fix shape as F3: pass `is_first_call=False` to the inner/post-lock cache check, or otherwise decouple "force a fetch on cold start" from "check whether another thread already refreshed while we waited for the lock."

---

### `src/testbench_defect_service/clients/jira/jira_client.py`

**[F13] [SEVERITY: HIGH]** — `proxy_url` is never applied to the primary/shared Jira connection (including the new OAuth2 gateway path)

- **Location:** `_build_jira_options` (lines 252–256) vs. `__init__`'s `self._options` (lines 56–67); consumed by `_create_jira_instance` (line 211, used by `_connect()` → `_connect_via_gateway()` for basic/token/oauth1/oauth2)
- **Confidence:** 🟠 High — established via static trace of the full file (this file was fully read, not inferred from the diff hunk); I did not execute the test suite to empirically confirm the resulting test failure, hence not "Certain."
- **Issue:** Two separate "build the JIRA `options` dict" code paths exist in this class:

  - `self._options` (built once in `__init__`) *does* include `proxies` when `config.proxy_url` is set, and is used only by `_connect_user()` (the per-principal/basic and per-principal/token branches).
  - `_build_jira_options()` (called fresh inside `_create_jira_instance`) only sets `verify` and `client_cert` — it never copies `proxies` from `self._proxies`/`self.config.proxy_url`. `_create_jira_instance` is the method used by the main `_connect()` path (i.e. the shared/service-account `JiraClient` constructed without a `principal`, which is the common case), for **every** auth type including the new OAuth2 gateway flow this branch centers on (`_connect_via_gateway` → `_create_jira_instance(gateway_url, token_override=...)`).

  Net effect: a configured `proxy_url` is silently **not** applied to the actual Jira REST API traffic for the shared client — only to (a) per-user connections and (b) the `_fetch_cloud_id()` tenant-info lookup (which this branch correctly wired to `self._proxies`). In an environment where outbound traffic is required to go through a proxy (the common reason to configure one), this could mean requests either fail outright or silently bypass an intended network egress control, which has security-adjacent implications beyond just "the feature doesn't work." The existing test `TestInit.test_proxy_url_passed_to_options` (unchanged by this diff) asserts `kwargs["options"]["proxies"] == {...}` against the `JIRA(...)` call made via `_create_jira_instance`'s `_build_jira_options()` output — based on the trace above, that dict never contains a `"proxies"` key, so this assertion appears to be checking a code path that cannot currently satisfy it.
- **Category:** Bug / Security (network egress control bypass)
- **Recommendation:** Have `_build_jira_options()` include `self._proxies` (or `self.config.proxy_url`) the same way `self._options` already does, so all connection paths are consistent:

  ```python
  def _build_jira_options(self) -> dict[str, Any]:
      options: dict[str, Any] = {"verify": self.config.ssl_verify}
      if self.config.client_cert is not None:
          options["client_cert"] = self.config.client_cert
      if self._proxies is not None:
          options["proxies"] = self._proxies
      return options
  ```

  Then re-run `TestInit.test_proxy_url_passed_to_options` to confirm it actually passes against the fixed code (worth double-checking whether it currently passes in CI at all, given the trace above).

---

## Verification performed after the review

The three HIGH findings were independently re-checked against the working tree, and the test
suite was executed on both this branch and `origin/main`.

**Confirmed by direct source inspection:**

- **F10** — `grep -rn '"oauth2"' src/ tests/` finds `src/testbench_defect_service/config.py:163`
  (`if client_config.get("auth_type") != "oauth2":`) as the only stale *comparison*. The other two
  hits are benign: `jira_oauth.py:23` is the TOML cache section name (`_TOKEN_CACHE_SECTION`), and
  `test_config.py:35` deliberately asserts the legacy value is rejected. Confirmed.
- **F11** — `is_sensitive_config_key`'s `sensitive_keys` set contains no bare `"secret"` entry, and
  no existing entry is a substring of `jira_oauth2_client_secret`. Confirmed — the key is not masked.
- **F13** — `_build_jira_options()` sets only `verify` and `client_cert`; it never adds `proxies`.
  Confirmed.

**Test suite results (`python -m pytest tests/unit -q`):**

> **Measurement caveat — read before trusting any cross-branch test numbers.** This project is
> installed as an **editable** install: `.venv/Lib/site-packages/testbench_defect_service.pth`
> pins the `testbench_defect_service` package to `E:/.../testbench-defect-service/src`, i.e. the
> *primary working tree*. Running `pytest` from inside a `git worktree` therefore executes **that
> worktree's tests against the primary working tree's source** — the checked-out `src/` in the
> worktree is silently ignored. An earlier run of this comparison was invalid for exactly this
> reason (it reported 13 failures for main, three of which were just main's *old* oauth tests run
> against the *branch's* new source). To compare branches correctly you must override the `.pth`:
>
> ```bash
> cd <worktree> && PYTHONPATH="<worktree>/src" python -m pytest tests/unit -q
> # verify with: python -c "import testbench_defect_service as m; print(m.__file__)"
> ```

Corrected numbers, each run against its own source tree:

|                                          | Failures     | Passes |
| ---------------------------------------- | ------------ | ------ |
| `origin/main`                          | **10** | 410    |
| `support-oauth2` (as reviewed)         | **10** | 431    |
| `support-oauth2` + fixes applied below | **9**  | 435    |

The branch's 10 failures are exactly the same 10 as main's — **this branch introduces no new test
failures**. (It does not fix any either; the "fixes three tests" claim in the invalid earlier run
was an artifact of the `.pth` issue described above.)

The 10 pre-existing failures:

- `test_jira_client.py::TestInit::test_proxy_url_passed_to_options` (1) — fails with
  `KeyError: 'proxies'`, empirically confirming **F13**. This raises F13's confidence from 🟠 High
  to 🔴 **Certain**: the assertion cannot be satisfied by `_build_jira_options()`. The test is
  *already red on main*, so the branch did not break it — but the branch's folded-in proxy-support
  work touched proxy handling in this very file (wiring `self._proxies` into `_fetch_cloud_id`)
  without fixing the broken primary-connection path or its red test.
- `test_client.py` (2) and `test_utils.py` (7) — all fail with
  `TypeError: object of type 'Mock' has no len()` in `models/defects.py:13` (`max_length_255`).
  Unrelated to this branch (Mock objects reaching a `len()` call in test fixtures).

**Practical consequence:** the branch is not regressing CI, but it is merging onto an already-red
baseline of 10 failures.

---

## Fixes applied (F3, F12, F13)

Applied to the working tree after the review, at the author's request. **Not committed.**

**F13 — `proxy_url` now reaches every connection path** (`jira_client.py`)

Rather than adding a third copy of the proxy logic, the two divergent options-builders were
consolidated: `__init__` now computes `self._proxies` first and then calls `_build_jira_options()`
for `self._options`, making that method the single source of truth for the JIRA `options` dict on
both the per-user and shared/service paths. This removes the duplication that allowed the two to
drift apart in the first place.

**F3 — 2LO post-lock re-check** (`jira_oauth.py`)

The inner re-check now passes `is_first_call=False`. Safe because `_is_cached_2lo_token_valid`
already rejects placeholder tokens, and the 2LO path never seeds a real access token
(`_connect_via_gateway` passes no `access_token`, `expires_at=None`, and skips the disk load) — so
the placeholder check alone provides the cold-start guarantee `is_first_call` was standing in for.

**F12 — 3LO post-lock re-check** (`jira_oauth.py`)

Naively dropping `and not is_first_call` would have been wrong: it would let a genuine cold start
return a config-supplied or placeholder-substituted token without ever validating it, which is the
exact thing `is_first_call` exists to prevent. Instead the token seen before acquiring the lock is
captured and compared inside it:

```python
refreshed_by_peer = access_token != token_before_lock
if time.time() < (expires_at - 300) and access_token and (not is_first_call or refreshed_by_peer):
    return access_token
```

A changed access token can only have come from a peer thread's refresh (the disk cache holds the
refresh token only, since this branch narrowed `_load_token_store_from_disk`), and that satisfies
the cold-start obligation just as our own refresh would. This needs no new module-level state, so
it adds no test-isolation surface, and it preserves the forced live fetch for a *later* first call
(e.g. a second `JiraClient`) — which a once-per-process flag would have wrongly skipped.

Benign residual: if Atlassian returns a byte-identical token to the peer, `refreshed_by_peer` is
false and one redundant refresh occurs. That matches today's behaviour and is not a regression.

**Regression tests added** — `TestConcurrentFirstCalls` in `tests/unit/clients/jira/test_jira_oauth.py`:
two threads released from a `threading.Barrier`, with the patched fetch sleeping 50 ms so the loser
is guaranteed to be waiting on `refresh_lock_sync` while the winner is in flight.

- `test_3lo_refreshes_only_once` / `test_2lo_mints_only_once` — assert exactly one token fetch.
  **Both verified to fail against the unfixed source** (`assert 2 == 1`) using the `PYTHONPATH`
  override above, and to pass after the fix. Without that override they vacuously pass, which is
  how the first attempt at validating them was misleading.
- `test_3lo_single_first_call_still_forces_refresh` — guards the other direction: a lone first call
  must still perform a live refresh and not be short-circuited by the new peer check.

**Verification:** `pytest tests/unit` → 9 failed / 435 passed (the 9 pre-existing `Mock`/`len`
failures above; `test_proxy_url_passed_to_options` now green). `ruff check src tests` → all checks
passed. `ruff format --check` → 3 files already formatted. `mypy` on both changed modules → no
issues.

**Still open from this review:** F2, F10, F11 (the three HIGH findings the author has not asked for
fixes on), plus F1, F4, F5, F6, F7, F8, F9.

---

**Files referenced for context (not part of the diff, read for call-site/consistency verification):**

- `E:/Testbench-ecosystem/testbench-defect-service/src/testbench_defect_service/config.py`
- `E:/Testbench-ecosystem/testbench-defect-service/src/testbench_defect_service/utils/wizard.py`
- `E:/Testbench-ecosystem/testbench-defect-service/tests/unit/clients/jira/conftest.py`
