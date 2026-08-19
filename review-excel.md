# Branch Review Report: `excel` vs `origin/main`

**Reviewed on:** 2026-08-17
**Diff command used:** `git diff --merge-base origin/main HEAD`
**Merge-base:** `71b4331ab3d5a5e9b1031aa17e0e6bc293f6eff6` (= `origin/main` tip)
**Topology:** normal feature branch — 47 non-merge commits, 0 merge commits
**Files changed:** 38 (+7747 / −169), of which 3 are binary workbook fixtures
**Semgrep:** unavailable — no MCP server, no local CLI/module. Compensated with manual focus on injection, path traversal, resource handling, and concurrency.
**Prior review:** `review-excel.md` (2026-08-13, against merge-base `48d0eba`) — resolution section below.
**Total findings (branch-introduced):** 44

---

## Executive Summary

This branch adds a complete Excel/CSV `DefectClient` (config with legacy `.properties` compatibility, file I/O, cross-process locking, buffering, column mapping), registers it in the client registry and wizard, and hoists the pre/post-sync hook execution out of the Jira and JSONL clients into a shared `execute_sync_hook`. The Excel client itself is in good shape: every substantive finding from the prior review that concerned data integrity or security (F1, F5, F6, F7, F8, F9, F3) has been genuinely fixed, and the locking/concurrency work remains the strongest part of the branch.

The serious problems are now in the **shared-hook migration**, not in the Excel client. `JiraDefectClient.before_sync`/`after_sync` were switched to look up a config key `sync_commands` that exists on no config model in the repository, so every Jira pre/post-sync hook is now silently dead and reports success (**F1**). `execute_sync_hook`'s `commands` parameter is annotated `str` while callers pass a `PhaseCommands | None`, and the body reaches into it with `getattr` — which is precisely what turns F1 from a crash into a silent no-op (**F2**). Sixteen Jira/JSONL tests still call the deleted `_execute_sync_hook` and fail (**F40**), and the shared helper's only coverage is now indirect, through the Excel tests. Separately, `check_dependencies` was tightened to a fully-qualified class path, which breaks the short-form `client_class = "JiraDefectClient"` that `docs/clients/index.md` documents (**F7**), and a boolean UDF configured without `trueValue`/`falseValue` no longer honours the documented `"true"`/`"false"` defaults on the read/write path (**F9**).

Also worth flagging: the F7/F8 UDF-clearing fix from the prior review is still in the code, but the `TestUdfClearingOnUpdate` regression tests the prior review recorded as added are **not present at the branch tip** — the fix is now unpinned (**F41**). Those tests were never committed on any branch; they are sitting in `stash@{0}` and can be recovered intact.

---

## Prior findings resolution

Re-verified against the working tree at the branch tip, not taken from the prior report's own verdicts.

| Prior ID | Severity | Status | Evidence at tip |
| --- | --- | --- | --- |
| F1 | MEDIUM | **Resolved** | `_resolve_project_path` at `clients/excel/client.py:280-289` does `resolve()` + `is_relative_to()` and raises `FileNotFoundError`; `_get_file_path` (`:292`) delegates to it. `TestProjectPathSandboxing` (`tests/unit/clients/excel/test_client.py:1064`) covers 4 traversal spellings, an absolute path, `check_login`, and the `update_defect` write path. |
| F2 | LOW | **Still open** | `get_defects_batch` (`client.py:319-332`) still carries the verbatim `requested_ids` set-comprehension and missing-ID loop; no shared helper in `clients/utils.py`. Re-listed as **F25**. |
| F3 | LOW | **Resolved** | `_start_buffer_cleanup_thread` (`client.py:713-754`) sizes itself from `[self.config, *effective configs]`, `min(intervals)` / `max(max_ages)`. Covered by `TestBufferCleanupThreadSizing` (3 tests). |
| F4 | INFO | **Not applicable** | Withdrawn in the prior re-review; no `TODO` in `clients/excel/*.py`. |
| F5 | MEDIUM | **Resolved** | `legacy_scalar_fields` is gone. `_normalize_legacy_excel_config` (`config.py:128-160`) now folds only composite keys, with a docstring saying so. `TestLegacyScalarKeys` pins every documented scalar key against the field aliases. |
| F6 | LOW | **Resolved** | Repo-wide grep for `column_settings` matches only `review-excel.md`. Both properties and the `FieldInfo` import are gone. |
| F7 | HIGH | **Resolved (but now untested — see F41)** | `utils.py:460-461` routes UDF values through `_cell_for_optional_field`. |
| F8 | MEDIUM | **Resolved (but now untested — see F41)** | Same line carries the explicit `if udf.value is not None or udf.name not in ...` precedence guard. |
| F9 | MEDIUM | **Resolved** | `utils.py:413` uses `int(id_val[len(prefix) :])`, matching the `isdigit()` guard on the next line. |
| F10 | MEDIUM | **Still open** | `_register_column` (`utils.py:129-139`) dedupes only within one column index; `get_column_mapping_for_config` still has no cross-index name check. Re-listed as **F16**. |
| F11 | LOW | **Still open, and worse** | `clients/utils.py:173:extract_static_attributes` now has **zero** importers — `jira/client.py:18` imports the 4-arg version from `jira/utils.py` and calls it at `:733`. Re-listed as **F3**. |
| F12 | LOW | **Still open** | `CHANGELOG.md` `## [Unreleased]` has only `### Fixed` with two bullets; no `### Added`. Re-listed as **F37**. |
| F13 | LOW | **Resolved** | `TestProjectPathSandboxing` — 7 tests. |
| F14 | LOW | **Still open** | The prior review recorded `TestUdfClearingOnUpdate` as added, but no such class exists in `tests/unit/clients/excel/test_client.py` at the tip (classes present: `TestSyncHookCommands`, `TestProjectPathSandboxing`, `TestBufferCleanupThreadSizing`), and no test anywhere under `tests/unit/clients/excel/` constructs a `UserDefinedFieldProperties(..., value=None)`. Re-listed as **F41** with severity raised. **Corrected by the caller after the review:** the reviewing agent speculated the tests were "lost in the rebase" — they were not. `git log --all -S"TestUdfClearingOnUpdate"` matches no commit on any branch; the class exists only in **`stash@{0}`** (`WIP on excel: 0bbadb5`), at `tests/unit/clients/excel/test_client.py:1241`, holding **4** tests, not 5. They were never committed, so nothing was dropped by the rebase — they are recoverable intact from the stash. |
| F15 | LOW | **Still open** (pre-existing) | `jsonl/client.py:378-392` still inlines the loop. Re-listed as **F46**. |
| F16 | INFO | **Still open** (pre-existing) | `jsonl/client.py:55` and `:58` still `return bool(exists)`. Re-listed as **F47**. |

**Net:** 8 resolved, 1 withdrawn, 5 still open (F2, F10, F11, F12, F14), 2 pre-existing carried forward. **F14 regressed from "fixed" to "open."**

---

## Part 1: Issues Introduced by This Branch

### `src/testbench_defect_service/clients/jira/client.py`

**[F1] [SEVERITY: HIGH]** — Jira pre/post-sync hooks are silently disabled: the client looks up a config key that no model defines

- **Location:** `before_sync` (`:694-696`), `after_sync` (`:698-700`)
- **Confidence:** 🔴 Certain — verified by grepping every config model in `src/`.
- **Issue:** Both methods now read

  ```python
  commands = self._get_config_value("sync_commands", project=project)
  return execute_sync_hook(project, sync_type, "presync", commands)
  ```

  but neither `JiraDefectClientConfig` (`clients/jira/config.py:303`) nor `JiraProjectConfig` (`:41`) has a `sync_commands` field — both declare `commands: PhaseCommands | None`. `_get_config_value` ends in `getattr(self.config, attr, None)`, so the lookup returns `None` for every project. `execute_sync_hook` then does `getattr(None, "presync", None)` → `None` → `command_str` falsy → it adds a `PUBLISH_SUCCESS` "hook acknowledged; no command configured" entry and returns.

  The consequence is the worst shape a regression can take: an existing Jira deployment whose `config.toml` configures `[...client_config.commands.presync]` scripts (checkout/checkin, VCS sync, etc.) stops running them entirely, and TestBench is told the hook succeeded. Nothing logs a warning. The Excel and JSONL clients still read `"commands"` (`excel/client.py:675`, `jsonl/client.py:324`), so this is Jira-only — which also means the three built-in clients now disagree about the config key for the same documented feature. No migration shim, no changelog entry, no doc update (see **F36**, **F37**).
- **Category:** Bug / Code Quality
- **Recommendation:** Revert to `"commands"` in both methods. If the rename to `sync_commands` is genuinely wanted, it has to land as a coordinated change: rename the field on `JiraDefectClientConfig`, `JiraProjectConfig`, `JsonlDefectClientConfig`, `ProjectConfig` (jsonl), `ExcelDefectClientConfig` and `ProjectConfig` (excel), add `validation_alias=AliasChoices("sync_commands", "commands")` so existing config files keep working, update `docs/configuration.md` and all three client docs, and add a CHANGELOG entry. Whichever way it goes, add a test that a configured hook actually runs for Jira (**F42**).

---

### `src/testbench_defect_service/clients/utils.py`

**[F2] [SEVERITY: MEDIUM]** — `execute_sync_hook`'s `commands` parameter is annotated `str` but receives a `PhaseCommands | None`; the `getattr` body makes the mistype undetectable

- **Location:** `execute_sync_hook` (`:200`, body at `:205-206`)
- **Confidence:** 🔴 Certain
- **Issue:**

  ```python
  def execute_sync_hook(project: str, sync_type: str, hook_type: str, commands: str) -> Protocol:
      ...
      hook_commands = getattr(commands, hook_type, None)
      command_str = getattr(hook_commands, sync_type, None) if hook_commands else None
  ```

  Every call site passes the result of `_get_config_value(...)`, i.e. `PhaseCommands | None`, never a `str`. Because `_get_config_value` is annotated `-> Any`, mypy accepts the call; because the body uses `getattr(..., default)` rather than attribute access, the runtime accepts *any* object — including `None` and including a `str`. That is exactly the mechanism that lets **F1** degrade into a silent success instead of an `AttributeError` that would have been caught by the first sync.

  The original per-client implementations had the same `getattr` shape, but they were private methods that read the config themselves, so there was no parameter to mistype. Extracting the function made the type contract load-bearing, and the annotation is wrong.
- **Category:** Type/Data Modeling / Bug
- **Recommendation:** Type the parameter honestly and dispatch explicitly:

  ```python
  def execute_sync_hook(
      project: str,
      sync_type: str,
      hook_type: Literal["presync", "postsync"],
      commands: PhaseCommands | None,
  ) -> Protocol:
      phase = commands.presync if hook_type == "presync" else commands.postsync if commands else None
      command_str = getattr(phase, sync_type, None) if phase else None
  ```

  Note the import direction: `models/config.PhaseCommands` is importable from `clients/utils.py` without a cycle. See also **F6** on the three duplicate `PhaseCommands` classes, which is why an honest type is awkward today.

**[F3] [SEVERITY: MEDIUM]** — `extract_static_attributes` added to `clients/utils.py` is dead code and collides by name with the Jira-specific function

- **Location:** `clients/utils.py:173-185`
- **Confidence:** 🔴 Certain — repo-wide grep for `from testbench_defect_service.clients.utils import` shows only `get_client_config_class`, `get_defect_client`, `get_defect_client_from_client_class_str`, and `execute_sync_hook`.
- **Issue:** The prior review's F11 noted the shared helper had one consumer. It now has **zero**: `jira/client.py:18` imports `extract_static_attributes` from `clients.jira.utils` and calls the 4-arg version at `:733`. The 2-arg copy in `clients/utils.py` is never imported by anything, in `src/` or `tests/`.

  The caller's note says the two same-named functions are deliberate. Deliberate or not, shipping an unreferenced public function whose name shadows a live one in a sibling module is a maintenance hazard: a future reader who greps `extract_static_attributes` gets two hits with different arities and no indication of which is authoritative, and a mistaken `from clients.utils import extract_static_attributes` in `jira/client.py` would fail with a confusing arity error rather than an ImportError.
- **Category:** Code Quality / Code Duplication
- **Recommendation:** Either delete it until there is a consumer, or wire it up now — `JsonlDefectClient._build_defect_with_attributes` (`jsonl/client.py:378`) is a byte-for-byte behavioural match and would become a two-line method (see **F46**). If it stays, rename one of the two (e.g. `extract_static_attributes_from_defect` for the generic one) so the collision is not silent.

**[F4] [SEVERITY: LOW]** — `hook_type` and `sync_type` are bare strings resolved by reflection, so a typo is a silent success

- **Location:** `execute_sync_hook` (`:200`, `:205-206`)
- **Confidence:** 🔴 Certain
- **Issue:** `hook_type` has exactly two valid values (`"presync"`, `"postsync"`) and `sync_type` exactly three (`"scheduled"`, `"manual"`, `"partial"`), both fixed by `PhaseCommands` / `SyncCommandConfig`. Resolving them with `getattr(..., None)` means any misspelling — or a `sync_type` value TestBench sends that the model does not model — is indistinguishable from "no command configured", and the protocol reports success. That is the same failure mode as **F1**, one level down.
- **Category:** Type/Data Modeling
- **Recommendation:** Annotate both as `Literal[...]` (or a `StrEnum`) and dispatch on the literal rather than by reflection, as in **F2**'s snippet. At minimum, log a warning when `sync_type` is not one of the three known values.

**[F5] [SEVERITY: LOW]** — f-string logging throughout the new shared helper

- **Location:** `execute_sync_hook`, `:202`, `:209`, `:218`, `:222`, `:227`, `:231`, `:234`, `:241`, `:252`
- **Confidence:** 🔴 Certain
- **Issue:** Nine `logger.debug(f"...")` / `logger.info(f"...")` / `logger.warning(f"...")` calls. This was copied verbatim from the JSONL implementation, but the code it now also serves — `jira/client.py` and the whole new `clients/excel/` package — uses `%s`-style lazy formatting consistently (e.g. `excel/client.py:87`, `:107`, `:304`). Since this is now shared code, the mismatch is more visible than it was.
- **Category:** Pythonic Idiom
- **Recommendation:** Convert to `logger.debug("Executing %s hook for project '%s' with sync type: %s", hook_type, project, sync_type)` etc., matching the two clients that call it.

---

### `src/testbench_defect_service/models/config.py`

**[F6] [SEVERITY: MEDIUM]** — A third identical copy of `SyncCommandConfig` / `PhaseCommands`, and the shared helper now depends on all three being structurally identical

- **Location:** `:113-134` (new)
- **Confidence:** 🔴 Certain
- **Issue:** `clients/jira/config.py:26-34` and `clients/jsonl/config.py:6-14` already declare `SyncCommandConfig` and `PhaseCommands` with the same three/two fields. This branch adds a third copy to `models/config.py` for the Excel client to import, rather than consolidating the two existing ones onto it.

  Before this branch the duplication was inert — each client's private `_execute_sync_hook` only ever saw its own class. Now `execute_sync_hook` receives instances of *all three* and works only because they happen to have identical attribute names, resolved by `getattr`. Adding a fourth sync type (say `"incremental"`) to one copy and not the others produces a hook that runs for one client and silently no-ops for the others — the same failure signature as **F1**, and just as hard to spot.
- **Category:** Code Duplication / Type Modeling
- **Recommendation:** Make `models/config.py` the single definition and have `clients/jira/config.py` and `clients/jsonl/config.py` re-export it (`from testbench_defect_service.models.config import PhaseCommands, SyncCommandConfig`) rather than redeclaring. Then **F2**'s honest type annotation becomes trivially correct.

---

### `src/testbench_defect_service/app.py`

**[F7] [SEVERITY: MEDIUM]** — Tightening the dependency check to a fully-qualified path breaks the documented short-form `client_class`, including for Jira

- **Location:** `check_dependencies` (`:39-45`)
- **Confidence:** 🟠 High — the code paths are certain; the impact depends on how many deployments use the short form, which the docs actively encourage.
- **Issue:** The check changed from a bare class-name substring to the full dotted path:

  ```python
  if "testbench_defect_service.clients.ExcelDefectClient" in app.config.CLIENT_CLASS:
  if "testbench_defect_service.clients.JiraDefectClient"  in app.config.CLIENT_CLASS:
  ```

  But `get_client_class_from_module_str` (`clients/utils.py:116-127`) explicitly supports a bare class name, and `docs/clients/index.md:67` and `:78` document exactly that:

  ```toml
  client_class = "JsonlDefectClient"   # or ExcelDefectClient / JiraDefectClient
  ```

  With `client_class = "JiraDefectClient"`, the friendly "install with `pip install testbench-defect-service[jira]`" `ImportError` from `check_jira_dependencies` no longer fires. That is a **regression** for Jira — the old substring check worked with both spellings — and the new Excel client inherits the same hole. Instead of a startup message naming the missing extra, the operator gets whatever `clients/__init__.py` does: for Excel, `contextlib.suppress(ImportError)` swallows the import and the class simply is not there, so `get_defect_client_from_client_class_str` fails later with an opaque message.
- **Category:** Bug
- **Recommendation:** Match on the class name and the fully-qualified path, or better, reuse the resolution the wizard already has — `config_wizard.detect_client_type` (`:346-352`) already compares both the full path and the trailing class name against `CLIENT_CLASSES`. Extract that comparison into `clients/utils.py` and call it from `check_dependencies`:

  ```python
  client_type = client_type_for_class(app.config.CLIENT_CLASS)  # "excel" | "jira" | ...
  check_client_dependencies(client_type, raise_on_missing=True)  # already exists, unused
  ```

  Note `utils/dependencies.check_client_dependencies` (`:103`) already exists for exactly this and has no caller.

---

### `src/testbench_defect_service/clients/__init__.py`

**[F8] [SEVERITY: LOW]** — `__all__` lists `ExcelDefectClient` unconditionally although the import is suppressed, and two idioms are used for the same optional-import pattern four lines apart

- **Location:** `:6-19`
- **Confidence:** 🔴 Certain
- **Issue:** Two things:

  1. `from testbench_defect_service.clients import *` raises `AttributeError: module ... has no attribute 'ExcelDefectClient'` when the `[excel]` extra is not installed, because `__all__` names it unconditionally. This wart already existed for `JiraDefectClient`; the branch adds a second instance rather than fixing the pattern.
  2. Jira uses `try: ... except ImportError: pass  # noqa: SIM105` while Excel, immediately below, uses `with contextlib.suppress(ImportError):`. `contextlib.suppress` is the better form (it is what SIM105 asks for), but having both in a ten-line file is noise.
- **Category:** Code Quality / Pythonic Idiom
- **Recommendation:** Convert the Jira block to `contextlib.suppress` as well, and build `__all__` from what actually imported:

  ```python
  __all__ = ["AbstractDefectClient", "JsonlDefectClient"]
  for _name in ("ExcelDefectClient", "JiraDefectClient"):
      if _name in globals():
          __all__.append(_name)
  ```

---

### `src/testbench_defect_service/clients/excel/file_utils.py`

**[F9] [SEVERITY: MEDIUM]** — Boolean UDFs without an explicit `trueValue`/`falseValue` do not get the documented `"true"`/`"false"` defaults, and matching is case-sensitive here but case-insensitive in `parse_boolean_udf_value`

- **Location:** `_map_boolean_read_value` (`:81-89`), `_apply_boolean_udf_write_mapping` (`:330-348`)
- **Confidence:** 🟠 High — the code is unambiguous; "High" only because I could not run the service to confirm no caller pre-fills the defaults, and no test covers the unset case.
- **Issue:** `docs/clients/excel-client.md` states of `trueValue` / `falseValue`: *"Default to `"true"` / `"false"`."* `UserDefiendAttributes` declares both as `str | None = None` with no default value, and `parse_boolean_udf_value` (`utils.py:584-597`) correctly applies the documented fallback and normalises with `.strip().lower()`:

  ```python
  normalized_true  = (true_value  or "true").strip().lower()
  normalized_false = (false_value or "false").strip().lower()
  ```

  The read/write path does neither:

  ```python
  def _map_boolean_read_value(value, true_value):
      if is_blank_cell(value):
          return ""
      return "true" if value == true_value else "false"     # true_value may be None
  ```

  ```python
  return tv if str(v).lower() == "true" else fv             # tv/fv may be None
  ```

  Two consequences for a `BOOLEAN` UDF declared without the optional cell labels:

  - **Read:** `value == None` is never true, so *every* non-blank cell — including a literal `true` — is read as `"false"`. The user's `true` values disappear.
  - **Write:** `tv`/`fv` are `None`, which `to_csv(na_rep="")` / openpyxl render as an empty cell, so the column is blanked on every write.

  A separate, smaller mismatch: `_map_boolean_read_value` compares raw (`value == true_value`), so a cell reading `Yes` against `trueValue = "yes"`, or `" yes"`, reads as `false`, while `parse_boolean_udf_value` — used by `get_user_defined_attributes` (`client.py:657`) to report the same field's fallback value to TestBench — accepts both. So the service can advertise a value it cannot then read back from a cell.
- **Category:** Bug
- **Recommendation:** Route both directions through a single normaliser shared with `parse_boolean_udf_value`, so the documented defaults and the strip/lower rule are stated once:

  ```python
  def boolean_labels(udf) -> tuple[str, str]:
      return (udf.trueValue or "true"), (udf.falseValue or "false")

  def _map_boolean_read_value(value, true_value):
      if is_blank_cell(value):
          return ""
      return "true" if str(value).strip().casefold() == (true_value or "true").strip().casefold() else "false"
  ```

  Add tests for a `BOOLEAN` UDF with `trueValue`/`falseValue` unset, in both directions and for a full read→write round trip.

**[F10] [SEVERITY: MEDIUM]** — Import warnings raised while parsing the file are lost on every buffered read

- **Location:** `_validate_column_mapping` (`:122-126`) and `resolve_sheet_name` (`utils.py:376-380`), reached only from `read_data_frame_from_file_path`, which `client._get_dataframe` (`client.py:180-190`) skips on a buffer hit
- **Confidence:** 🟠 High — mechanism is certain; the practical severity depends on how much TestBench users rely on the import protocol.
- **Issue:** Buffering is on by default (`buffer_max_age_minutes = 1440`, `buffer_max_size_mib = 1024`). On a buffer hit, `_get_dataframe` returns `entry.data_frame` without calling `read_data_frame_from_file_path` at all, so the warnings that function raises into the protocol never reappear:

  - `"Optional column 'reporter' (index 4) is not present in the file (3 columns)."`
  - `"UDF column 'Customer' (index 10) is not present..."`
  - `"Worksheet 'Defects 2026' was not found or is hidden in 'car_config.xlsx'. Falling back to 'Sheet1'."`

  So a misconfigured column mapping is reported on the first sync after the file's mtime changes, and then goes quiet for up to 24 hours — the user sees a clean protocol and concludes the configuration is fine. The author is clearly aware of this class of problem: `test_get_defects_warns_about_empty_rows_on_a_buffered_read` (`test_client.py`) exists precisely to pin that *one* warning survives a buffered read, because it is recomputed per call in `_build_defects_from_dataframe`. The parse-time warnings are not.
- **Category:** Bug
- **Recommendation:** Store the parse-time protocol entries on `DataFrameBufferEntry` alongside the frame, and replay them into the caller's protocol on a buffer hit:

  ```python
  @dataclass
  class DataFrameBufferEntry:
      data_frame: pd.DataFrame
      import_warnings: list[ProtocolEntryWarning]
      ...
  ```

  Then extend the existing buffered-read test to assert a missing-optional-column warning also survives.

**[F11] [SEVERITY: LOW]** — `map_boolean_values` uses `try/except KeyError` around an assignment where a membership test is clearer, and logs with an f-string

- **Location:** `:70-78`
- **Confidence:** 🔴 Certain
- **Issue:**

  ```python
  try:
      df[udf.name] = df[udf.name].map(lambda v, t=udf.trueValue: _map_boolean_read_value(v, t))
  except KeyError:
      logger.warning(f"{udf.name} not in the dataframe")
  ```

  Wrapping an *assignment* statement in `except KeyError` is fragile: it happens to be safe today only because the RHS raises before the LHS is evaluated, and it would silently swallow a `KeyError` raised from inside `_map_boolean_read_value` if that function ever grew a dict lookup. The condition being tested is a one-liner. The f-string log is also inconsistent with the `%s` style used everywhere else in this same file (`:34`, `:62`, `:103`, `:261`), and the message itself is bare — it names no file and no column index, so it is hard to act on.
- **Category:** Pythonic Idiom
- **Recommendation:**

  ```python
  for udf in config.udfs:
      if udf.type is not ValueType.BOOLEAN:
          continue
      if udf.name not in df.columns:
          logger.warning("Boolean UDF column '%s' is not present in the dataframe.", udf.name)
          continue
      df[udf.name] = df[udf.name].map(lambda v, t=udf.trueValue: _map_boolean_read_value(v, t))
  ```

  Note `udf.type == ValueType.BOOLEAN` → `is` is also correct here for an `Enum` member and matches `client.py:656` (`udf.type is ValueType.BOOLEAN`), which currently disagrees with this file.

**[F12] [SEVERITY: LOW]** — Both writers return silently when the column mapping is empty, so the caller reports a successful create/update that never touched the file

- **Location:** `write_defect_data_to_excel` (`:251-253`), `write_defect_data_to_csv` (`:373-375`)
- **Confidence:** 🟠 High — reachable only via a config where every mapped column number is `0`/negative, which is unusual but not prevented.
- **Issue:** `if not column_positions: return` covers both `None` (missing control field, which `get_column_mapping_for_config` with `protocol=None` actually raises for) and `{}` (every column number disabled). In the `{}` case the function returns normally, so `_create_defect_in_locked_file` proceeds to `protocol.add_success(...)` and hands TestBench a new defect ID for a row that was never written. TestBench then tracks a defect that does not exist in the file, and the next sync cannot reconcile it. Two tests (`test_none_column_positions_returns_early_without_writing`, `test_empty_column_positions_returns_early_without_writing`) pin the silence but not the consequence.
- **Category:** Bug
- **Recommendation:** Distinguish the two: keep the early return for `None` (the protocol already carries the reason), and raise `ValueError("No columns are mapped for ...; nothing can be written.")` for `{}` so the caller's existing `except (OSError, ValueError)` turns it into an `INSERT_ERROR`/`PUBLISH_ERROR`.

**[F13] [SEVERITY: LOW]** — `_clear_stale_delimited_rows` deletes trailing all-blank rows, contradicting the documented and changelogged promise that empty rows are preserved

- **Location:** `:325-326`
- **Confidence:** 🟠 High — the code is certain; whether users care about a trailing blank line is a judgment call.
- **Issue:** `CHANGELOG.md` says empty rows *"are preserved in the file when defects are created, updated or deleted"*, and `docs/clients/excel-client.md` repeats it. But:

  ```python
  while len(grid_df) > end_row_idx and grid_df.iloc[-1].eq("").all():
      grid_df = grid_df.iloc[:-1]
  ```

  strips every entirely-blank row below the data. A user who keeps a blank separator row at the bottom of the sheet (or blank rows that happen to sit past the last defect) loses them on the first write. This also creates an asymmetry with the `.xlsx` writer, which only blanks the *mapped* columns of stale rows (`_clear_stale_excel_rows`) and never removes a row.
- **Category:** Bug / Documentation
- **Recommendation:** Either drop the trailing-blank compaction so the two writers agree and the doc holds, or narrow the doc to "empty rows *between* defects are preserved" and add a test pinning the trailing-row behaviour explicitly.

**[F14] [SEVERITY: LOW]** — `_apply_boolean_udf_write_mapping` mutates the caller's DataFrame in place, which neither its name nor its docstring says

- **Location:** `:330-348`, called from `write_defect_data_to_excel:275` and `write_defect_data_to_csv:419`
- **Confidence:** 🔴 Certain
- **Issue:** `df[col_name] = df[col_name].map(_map_bool)` rewrites the frame the caller owns. Today that is safe by accident: `_update_defect_in_locked_file` passes `df.copy()`, `_delete_defect_in_locked_file` passes the result of `df.drop(...)`, and `_create_defect_in_locked_file` passes a `pd.concat` result — all fresh objects. But `_read_dataframe_from_disk` → `_get_dataframe` **re-buffers the frame it returns**, so the object handed to the write path is one `.copy()` away from being the shared buffer entry. If any future call site drops that copy, the in-memory buffer silently acquires the file's on-disk labels (`"1-yes"`) where the internal form (`"true"`) is expected, and every subsequent read of that buffered frame is wrong until the mtime changes.

  The write path also performs this mutation *before* the write can fail, so on a `PermissionError` the caller's frame is left half-converted.
- **Category:** Code Quality / Bug (latent)
- **Recommendation:** Make it a pure function returning a new `Series` (`def boolean_udf_write_values(config, df, col_name) -> pd.Series`), or take a copy at the top of both writers (`df_to_write = df_with_new_defect.copy()`) and document the ownership. At minimum add a "mutates `df` in place" line to the docstring.

**[F15] [SEVERITY: LOW]** — The `mode="w"` (new-file) branch of `write_defect_data_to_excel` is unreachable, and the test that covers it only passes because it mocks the call that would fail

- **Location:** `:259-266`; test `TestWriteDefectDataToExcel::test_new_file_uses_write_mode`
- **Confidence:** 🟠 High
- **Issue:** `is_existing_xlsx = defect_path.exists() and ...` implies a non-existing-file path, but two lines earlier `resolve_visible_sheet_name(defect_path, config)` calls `get_visible_sheets` → `openpyxl.load_workbook(file_path)`, which raises `FileNotFoundError` for a file that does not exist. In production the point is moot — `_get_file_path` only returns paths of files it found on disk — so the `mode="w"` branch can never be taken. The test passes only because it patches `resolve_visible_sheet_name`, i.e. it asserts on a code path the production caller cannot reach.
- **Category:** Code Quality / Dead Code
- **Recommendation:** Delete the `is_existing_xlsx` conditional and always use `mode="a", if_sheet_exists="overlay"`, or move the `resolve_visible_sheet_name` call inside the existing-file branch and give the new-file branch a real (unmocked) test.

---

### `src/testbench_defect_service/clients/excel/utils.py`

**[F16] [SEVERITY: MEDIUM]** — The same logical field name can still be registered at two different column indices, producing a DataFrame with duplicate columns and silently garbled values *(prior F10, still open)*

- **Location:** `_register_column` (`:129-139`), `get_column_mapping_for_config` (`:45-88`)
- **Confidence:** 🟡 Medium — requires a misconfiguration (a UDF or control field sharing a name with a base field or another UDF), but nothing guards against it and the failure is silent.
- **Issue:** `_register_column` dedupes only *within* one `column_idx` (`if field_name not in column_mapping[column_idx]`). Nothing checks whether `field_name` was already registered at a different index. A UDF named `status` at column 10 alongside a `status` control field at column 7 yields `{6: ["status"], 9: ["status"]}`; `_apply_column_mapping` (`file_utils.py:157`) then sets `mapped_df.columns = pd.Index(["status", ..., "status"])`. From that point:

  - `row_value(row, "status")` returns a 2-element `pd.Series`; `str(value).strip()` yields pandas' repr text, which lands in the defect's status field and is sent to TestBench.
  - In `write_defect_data_to_excel`, `df_with_new_defect[[col_name]]` returns a *two-column* frame, so `to_excel(startcol=col_idx, ...)` writes two adjacent columns and overwrites the neighbouring one in the user's file.
  - The `_cell_for_optional_field` guard added for the prior F7/F8 fix (`if udf.name not in defect_info_data_frame.columns`) also becomes ambiguous, which the prior review already noted as the one behaviour wrinkle in that fix.

  `_validate_column_mapping` warns about the inverse case (several names at one index) but never about one name at several indices.
- **Category:** Bug / Data Modeling
- **Recommendation:** Track names globally in `get_column_mapping_for_config` and reject the collision at config-load time (or at least raise a `ValueError` the read path already maps to `READ_ACCESS_ERROR`):

  ```python
  seen: dict[str, int] = {}
  def _register_column(mapping, column_number, field_name):
      ...
      if seen.setdefault(field_name, column_idx) != column_idx:
          raise ValueError(
              f"Field '{field_name}' is mapped to both column {seen[field_name] + 1} "
              f"and column {column_idx + 1}."
          )
  ```

  Add a test asserting a UDF named `status` alongside a `status` control field is refused.

**[F17] [SEVERITY: MEDIUM]** — A control field with an empty `values` list rejects every create and update, which a legacy `.properties` file can produce

- **Location:** `validate_control_fields` (`:636`)
- **Confidence:** 🟠 High — follows directly from the code and the legacy parser; not covered by any test.
- **Issue:** `values` is optional (`ControlFields.values: list[str] = Field(default_factory=list)`), and the model's own `check_transitions_against_values` explicitly skips validation when it is empty (`config.py`, `if not self.values: return self`), which is a clear statement that "no declared values" is a supported configuration. But `validate_control_fields` does:

  ```python
  if value not in control_field.values:
      protocol.add_error(..., f"Value '{value}' is not a valid option for control field "
                              f"'{control_field.name}'. Allowed values: {control_field.values}.")
      return False
  ```

  With `values == []` this is unconditionally true, so **every** create and update is rejected with `Allowed values: [].` — an error message that names no remedy.

  This is reachable from a plain legacy config: `_parse_legacy_control_fields` (`config.py:39-52`) requires only `<field>.columnNo`, and sets `values` from `_split_csv(data.get(f"{raw_name}.value"))`, which returns `[]` when the `.value` key is absent. So a DMProxy `.properties` file that declares `controlFields=status` and `status.columnNo=7` but no `status.value` — which the loader accepts and the docs do not forbid — imports fine and then refuses every write.
- **Category:** Bug
- **Recommendation:** Treat an empty `values` as "unconstrained", matching the transition validator:

  ```python
  if control_field.values and value not in control_field.values:
      ...
  validated.add(control_field.name)
  ```

  and add a test for a control field with no declared values.

**[F18] [SEVERITY: LOW]** — Two broken implicit-concatenation error messages: one drops the exception, both lose a space

- **Location:** `_load_xlsx_header_values` (`:193-196`), `get_visible_sheets` (`:332-335`)
- **Confidence:** 🔴 Certain
- **Issue:**

  ```python
  raise ValueError(
      f"File '{file_path}' does not appear to be a valid xlsx file (it may be corrupted or in"
      "a different format): {e}"                     # <- not an f-string
  ) from e
  ```

  The second fragment is a plain string, so the message ends with the literal characters `{e}` instead of the exception, and the concatenation produces `"...or ina different format"`. The near-identical message in `get_visible_sheets` *is* an f-string but has the space on the wrong side: `"...may be corrupted" f"or in a different format..."` → `"corruptedor in"`. Both are user-facing: they surface through `_load_dataframe`'s `except Exception` wrapper into the sync protocol.
- **Category:** Bug (cosmetic) / Code Duplication
- **Recommendation:** Fix both, and since the two messages are meant to be the same, extract one helper:

  ```python
  def _invalid_xlsx_error(file_path: Path, exc: Exception) -> ValueError:
      return ValueError(
          f"File '{file_path}' does not appear to be a valid xlsx file "
          f"(it may be corrupted or in a different format): {exc}"
      )
  ```

**[F19] [SEVERITY: LOW]** — The encoding-fallback loop is duplicated, hardcodes its own encoding tuple, and ends in dead code

- **Location:** `_load_delimited_header_values` (`:241-263`)
- **Confidence:** 🔴 Certain
- **Issue:** Three things in one function:

  1. The `for encoding in ("utf-8-sig", "windows-1252")` loop repeats `file_utils._read_delimited_dataframe`'s logic (`file_utils.py:210-224`) and, unlike it, spells the encodings inline instead of reading `_DELIMITED_ENCODINGS`. Adding a third encoding requires remembering both places, and the two would silently diverge.
  2. `if last_error is not None: raise last_error` followed by `_raise_missing_header_row(...)` and `return []  # type: ignore[unreachable]` — the trailing two statements are unreachable, because `_read_delimited_header_values` already raises `ValueError` itself when the header row is absent. The `# type: ignore[unreachable]` comment confirms the author knew and worked around the type checker rather than deleting.
  3. Same `return []  # type: ignore[unreachable]` pattern repeated at `:279`.
- **Category:** Code Duplication / Dead Code
- **Recommendation:** Promote `_DELIMITED_ENCODINGS` into `utils.py` (or a small shared constants module — note `utils.py` cannot import `file_utils.py`, which imports it) and extract a single `def _with_encoding_fallback(read: Callable[[str], T]) -> T` used by both call sites. Delete the unreachable tail.

**[F20] [SEVERITY: LOW]** — `create_defect_data_frame` takes a `protocol` it never uses and has no return annotation; `add_defect_to_dataframe` exists only to thread it through

- **Location:** `create_defect_data_frame` (`:438-463`), `add_defect_to_dataframe` (`:405-423`)
- **Confidence:** 🔴 Certain
- **Issue:** `protocol: Protocol` is a required positional parameter of `create_defect_data_frame` and is never referenced in the body. `add_defect_to_dataframe` accepts it solely to pass it on. Both call sites (`client.py:384`, `client.py:488`) construct or forward a `Protocol` for nothing. The function also lacks a `-> pd.DataFrame` return annotation, unlike every other public function in the module, and has a stray blank line after `def` (`:441`).

  A required unused parameter is worse than a merely redundant one: it makes the function harder to test in isolation and implies to a reader that this function might report problems, which it cannot.
- **Category:** Code Quality
- **Recommendation:** Drop `protocol` from both signatures and add `-> pd.DataFrame`. If the intent was that the frame builder should eventually report unmappable values, add that reporting now or leave a `# TODO(...)` naming the intent — not a silent placeholder.

**[F21] [SEVERITY: LOW]** — `map_and_rename_columns` is production dead code: only the test module imports it

- **Location:** `:142-156`
- **Confidence:** 🔴 Certain — repo-wide grep shows hits only at the definition and in `tests/unit/clients/excel/test_utils.py` (three tests).
- **Issue:** A 15-line public function with three dedicated tests and no production caller. The write path builds its own header mapping via `header.get(col_idx + 1, col_name)` instead. Tests that exercise unreachable code give a misleading impression of coverage.
- **Category:** Code Quality / Dead Code
- **Recommendation:** Remove the function and its three tests, or wire it into whichever write path was meant to use it.

**[F22] [SEVERITY: LOW]** — `split_references` falls back to `";"` while the config default and the docs say `","`

- **Location:** `:577-581`
- **Confidence:** 🔴 Certain
- **Issue:** `separator = config.references_separator or ";"`. `ExcelDefectClientConfig.references_separator` is `str = Field(default=",")` and `docs/clients/excel-client.md` documents the default as `","`. The `or ";"` branch is only reachable when the value is the empty string — in which case the client silently splits on a semicolon, contradicting both the model default and the documentation. The write side (`create_defect_data_frame:453`) uses `config.references_separator.join(...)` with no fallback, so an empty separator would join with `""` and split with `";"` — an asymmetric round trip.
- **Category:** Bug (minor) / Code Quality
- **Recommendation:** Drop the `or ";"` (the field is non-optional with a default), or reject an empty `references_separator` in a field validator so read and write cannot disagree.

**[F23] [SEVERITY: LOW]** — `to_python_datetime_format` is an order-dependent chain of `str.replace` that silently mangles unsupported patterns

- **Location:** `:478-494`
- **Confidence:** 🟠 High
- **Issue:** Seven sequential `str.replace` calls whose correctness depends on their order (`yyyy` before `yy`, `MM` before the `mm` branch), with the `mm` disambiguation keyed off a substring test on the *original* string. It works for the six patterns the docs list, but anything else degrades silently rather than erroring:

  - `"dd.MMM.yyyy"` (month name) → `"%d.%mM.%Y"`, which `strftime` renders as e.g. `05.08M.2026` and `pd.to_datetime` then fails to parse, sending every defect down the "invalid lastEdited, using current UTC timestamp" path — with a per-defect warning, but no indication that the *format* is the problem.
  - Single-letter `SimpleDateFormat` fields (`"d.M.yyyy"`) are not handled at all.
  - Literal text in the pattern containing `dd`, `MM`, `hh`, `ss` is silently rewritten.
  - `hh` maps to `%I` with no `%p`, so a 12-hour pattern parses AM and PM identically.

  Because `simple_date_format` is also used to *write* the last-edited cell (`_format_last_edited`), a mangled pattern corrupts the file, not just the read.
- **Category:** Code Quality / Bug (latent)
- **Recommendation:** Replace the replace-chain with a single token-scanning pass over a `dict[str, str]` of supported patterns (longest-token-first), and raise a `ValueError` naming the unsupported token so it surfaces as a configuration error at startup rather than as per-defect warnings at sync time. Keep the existing tests as the regression net.

**[F24] [SEVERITY: INFO]** — `describe_duplicated_id_rows` recomputes `duplicated_ids(df)` that its only caller has already computed

- **Location:** `:542`, called from `client._report_ambiguous_ids` (`client.py:779-783`)
- **Confidence:** 🔴 Certain
- **Issue:** `_report_ambiguous_ids` calls `duplicated_ids(df)`, then immediately calls `describe_duplicated_id_rows(df, config)`, which calls `duplicated_ids(df)` again — a full `astype(str).str.strip()` + `duplicated()` pass over the whole frame. `describe_ambiguous_id` (`:562`) makes it a third pass on the update/delete paths. Harmless on small files; wasteful and slightly confusing on large ones.
- **Category:** Code Quality
- **Recommendation:** Pass the already-computed set in: `describe_duplicated_id_rows(df, config, ambiguous_ids)`.

---

### `src/testbench_defect_service/clients/excel/client.py`

**[F25] [SEVERITY: LOW]** — `get_defects_batch` duplicates the JSONL client's ID-normalization block verbatim *(prior F2, still open)*

- **Location:** `:319-332`
- **Confidence:** 🔴 Certain
- **Issue:** The `requested_ids = {str(getattr(defect_id, "root", defect_id)) for ... if getattr(defect_id, "root", defect_id)}` comprehension and the subsequent "report missing IDs" loop are line-for-line identical to `JsonlDefectClient.get_defects_batch`. `jsonl/utils.py` already has an `add_missing_defect_warnings` helper for the second half. This is the class of small duplication that drifts when one copy gets a bugfix.
- **Category:** Code Duplication
- **Recommendation:** Extract `normalize_requested_defect_ids(defect_ids) -> set[str]` into `clients/utils.py` and reuse `add_missing_defect_warnings` in both clients.

**[F26] [SEVERITY: LOW]** — A third `_build_defect_with_attributes` implementation, and the "shared" helper it should compare against has no callers

- **Location:** `:635-649`
- **Confidence:** 🟠 High
- **Issue:** There are now three implementations of "build the extended-attributes dict": `jira/utils.extract_static_attributes` (4-arg, live), `jsonl/client._build_defect_with_attributes` (inline, live), `excel/client._build_defect_with_attributes` (DataFrame-based, live) — plus the unreferenced `clients/utils.extract_static_attributes` (**F3**). The Excel variant reading from the mapped DataFrame row rather than from `Defect` attributes is a defensible design choice, but nothing in the code says so, so a reader who finds the "shared" helper with zero callers has no way to know whether Excel's divergence is intentional.
- **Category:** Code Duplication
- **Recommendation:** Add a one-line comment in `excel/client._build_defect_with_attributes` explaining why the DataFrame row is the source of truth here, and resolve **F3** in the same pass.

**[F27] [SEVERITY: LOW]** — `_get_effective_config` does a full `model_dump()` + `model_validate()` on every request, and drops an explicit empty-list project override

- **Location:** `:756-765`
- **Confidence:** 🟠 High
- **Issue:** Two things:

  1. Every `get_defects`, `create_defect`, `update_defect`, `delete_defect` and `get_defect_extended` call re-dumps and re-validates the entire config, including all `control_fields`, `udfs` and the whole `projects` dict — and the `model_validator(mode="before")` legacy normaliser runs again each time. For a config with many projects this is measurable per request, and it is pure recomputation of a value that only changes when the config file does.
  2. `merged_config.update(self.config.projects[project].model_dump(exclude_none=True))` means a project that sets `control_fields = []` (or `udfs = []`) to *deliberately clear* the global list has no effect — `exclude_none` keeps the empty list, so that case actually works, but `attributes = None` and `control_fields = None` are indistinguishable from "not set", which is the documented behaviour. Worth confirming that "clear the global list for this project" is intended to be impossible.
- **Category:** Code Quality
- **Recommendation:** Cache the merged config per project name in a dict built once in `__init__` (the config is immutable for the client's lifetime), and document the "cannot clear a list, only replace it" semantics in `docs/clients/excel-client.md#per-project-overrides`.

**[F28] [SEVERITY: LOW]** — The buffer cleanup thread cannot be stopped, and one is started per client instance

- **Location:** `_start_buffer_cleanup_thread` / `_cleanup_loop` (`:713-754`), started from `__init__` (`:84`)
- **Confidence:** 🔴 Certain
- **Issue:** `_cleanup_loop` is `while True: time.sleep(...)` with no stop event, and the thread is started as a side effect of construction. It is a daemon, so it does not block interpreter exit, but:

  - There is no way to shut a client down cleanly; a Sanic reload or a test that constructs many clients leaves one live thread each. The Excel test suite constructs `ExcelDefectClient(...)` dozens of times, so a full run accumulates threads (each holding a reference to `self` and therefore to the buffer catalog — the frames are never released).
  - `except Exception as exc: logger.warning(...)` swallows everything including a `MemoryError` and keeps looping.
  - Doing I/O-scheduling work in `__init__` makes the class hard to construct in a test without side effects, which is why `TestBufferCleanupThreadSizing` has to patch `threading.Thread`, `time.sleep` *and* `_purge_expired_entries` to observe anything.
- **Category:** Code Quality / Resource Leak
- **Recommendation:** Add a `threading.Event` stop flag, loop on `while not self._stop.wait(interval_seconds):`, and expose a `close()` (or `__enter__`/`__exit__`) that sets it. Move the thread start out of `__init__` into an explicit `start()` the app lifecycle calls, so tests can construct a client without it.

**[F29] [SEVERITY: LOW]** — `supports_changes_timestamps` reads only the global `lastedit_column_no`, ignoring per-project overrides the rest of the client honours

- **Location:** `:682-683`
- **Confidence:** 🟠 High — the abstract method takes no project argument, so this may be an interface limitation rather than an oversight.
- **Issue:** `return self.config.lastedit_column_no > 0` bypasses `_get_config_value`, which every other config read in this class uses. `ProjectConfig.lastedit_column_no` exists and is documented as overridable, and `docs/clients/excel-client.md` says *"Setting `lastedit_column_no = 0` disables change timestamps for the whole client"* — so the doc is at least consistent with the code, but a project that overrides `lastedit_column_no = 0` still has TestBench told that timestamps are supported, and every defect from that project then gets `datetime.now(timezone.utc)` as its `lastEdited` (`_parse_last_edited:944`), i.e. every defect looks changed on every sync.
- **Category:** Bug (minor) / Code Quality
- **Recommendation:** Return `True` only if *every* effective config has a positive `lastedit_column_no` (matching the conservative direction chosen for the cleanup thread), or add a warning at startup when a project override disagrees with the global value.

**[F30] [SEVERITY: LOW]** — `get_defect_extended` reports an ambiguous ID as "not found" instead of the clear duplicate-row message the update/delete paths give

- **Location:** `:623-631`
- **Confidence:** 🔴 Certain
- **Issue:** `single_defect_df = df.loc[df["id"] == defect_id]` selects *both* rows when an ID is duplicated. `_build_defects_from_dataframe` then runs `_report_ambiguous_ids` on that two-row frame, finds the duplicate, and skips both — with `protocol=None`, so nothing is recorded. `defects` is empty and the user gets `NotFound: Defect 'D-0002' was not found in project 'demo'.`

  `update_defect` and `delete_defect` handle the same input with a specific, actionable message (`describe_ambiguous_id`), so the extended view is the odd one out: it tells the user the defect does not exist when the file plainly contains it twice.
- **Category:** Bug (minor) / Code Quality
- **Recommendation:** Check `len(single_defect_df) > 1` before building and raise `ServerError(f"Cannot show defect '{defect_id}': {describe_ambiguous_id(df, effective_config, defect_id)}")`, matching the wording the write paths already use.

**[F31] [SEVERITY: INFO]** — `attributes.update({col: value})` where `attributes[col] = value` reads better

- **Location:** `_build_defect_with_attributes` (`:646`)
- **Confidence:** 🔴 Certain
- **Issue:** `attributes.update({col: df[col].iloc[0]})` constructs a throwaway one-item dict per column. The loop could also be a comprehension since it has no branching beyond the filter:

  ```python
  attributes = {col: df[col].iloc[0] for col in df.columns if col in attribute_fields}
  ```
- **Category:** Pythonic Idiom
- **Recommendation:** Use the comprehension above.

---

### `pyproject.toml`

**[F32] [SEVERITY: MEDIUM]** — mypy's `ignore_missing_imports` is enabled globally, and the accompanying per-module override for the project's own package is both redundant and harmful

- **Location:** `:807` (global `ignore_missing_imports = true`) and `:812-814` (`[[tool.mypy.overrides]] module = ["testbench_defect_service", "testbench_defect_service.*"]`)
- **Confidence:** 🔴 Certain
- **Issue:** The branch adds pandas/openpyxl/xlrd, then silences their (and everything else's) missing stubs by turning the flag on at the top level of a config that is otherwise deliberately strict (`strict_optional`, `warn_return_any`, `warn_no_return`, `warn_unreachable`). The effect is repo-wide: any third-party import that lacks stubs — present or future, in Jira/Sanic/pydantic code that has nothing to do with Excel — now silently becomes `Any`, which propagates through the call graph and defeats `warn_return_any`.

  Worse, the override block applies `ignore_missing_imports` to `testbench_defect_service.*` itself. That tells mypy to shrug at a *first-party* module it cannot resolve, so a genuine typo in an intra-package import (`from testbench_defect_service.clients.excel.file_util import ...`) type-checks clean. Given the branch already ships `pandas-stubs`, `types-openpyxl` and `types-xlrd` in the `dev` extra, the global flag should not have been needed for the three new dependencies at all.
- **Category:** Code Quality / Tooling
- **Recommendation:** Remove both the global flag and the first-party override, and add a narrowly scoped one for whichever third-party module actually lacks stubs:

  ```toml
  [[tool.mypy.overrides]]
  module = ["xlrd.*"]          # or whichever genuinely has no stubs
  ignore_missing_imports = true
  ```

  Then re-run `mypy src` and fix whatever surfaces, rather than suppressing it wholesale.

**[F33] [SEVERITY: LOW]** — The `excel` extra's three pins are copy-pasted into `dev`

- **Location:** `:786` (`excel = [...]`) and `:794-796` (same three lines inside `dev = [...]`)
- **Confidence:** 🔴 Certain
- **Issue:** `openpyxl>=3.1.5,<4.0.0`, `pandas>=2.2.3,<3.0.0` and `xlrd>=2.0.1,<3.0.0` are now declared in two places. Bumping the Excel extra's floor without touching `dev` leaves the development environment on an older version than the shipped extra allows — exactly the drift `CLAUDE.md` already documents for the ruff hook.
- **Category:** Code Duplication
- **Recommendation:** Self-reference the extra: `dev = ["testbench-defect-service[excel,jira]", "ruff>=0.9.6", ...]`. PEP 621 supports self-referential extras and flit handles them.

---

### `src/testbench_defect_service/utils/wizard.py`

**[F34] [SEVERITY: LOW]** — Two `# noqa` directives were widened from explicit codes to bare `# noqa`, disabling all lint rules on those lines

- **Location:** `should_skip_field` (`:229`, was `# noqa: PLR0913`), `prompt_single_field` (`:1012` in the diff, was `# noqa: C901, PLR0912, PLR0913`)
- **Confidence:** 🔴 Certain
- **Issue:** `CLAUDE.md` documents the bare-`# noqa` workaround for the ruff version drift between `.venv` and the pre-commit hook, and explicitly scopes it to `_check_transitions_for_field` in `clients/excel/utils.py`. This branch applies the same workaround to two more functions that previously carried precise code lists. A bare `# noqa` suppresses *every* rule on the line, so future violations on those two `def` lines — including ones unrelated to argument counts — go unreported. `_check_transitions_for_field` in the new `excel/utils.py:668` is a third instance.

  Per `CLAUDE.md` the underlying drift is not to be worked around further but reported, so flagging the widening rather than the drift itself.
- **Category:** Code Quality
- **Recommendation:** Pin the hook (`additional_dependencies: [ruff==0.15.21]` in `.pre-commit-config.yaml`) to match `.venv`, then restore the explicit code lists on all three functions. Until then, note in `CLAUDE.md` that the bare-`noqa` list has grown to three sites so they are all reverted together.

**[F35] [SEVERITY: LOW]** — `get_carried_over_value` re-implements two of `should_skip_field`'s guards, so the two must be kept in sync by hand

- **Location:** `:255-277`, used at `:1126-1133` in the diff
- **Confidence:** 🔴 Certain
- **Issue:** `get_carried_over_value` repeats `should_skip_field`'s `allowed_fields` and `skip_fields` checks verbatim, because it is called only in the branch where `should_skip_field` already returned `True` and needs to distinguish "skipped because hidden by `skip_if_wizard`" from "skipped for any other reason". If a new skip reason is added to `should_skip_field`, this function keeps carrying values over for it — silently writing a field the wizard decided not to ask about.

  The docstring is excellent and the fix it implements (hiding a field must not reset it) is a genuinely good catch; only the structure is fragile.
- **Category:** Code Duplication
- **Recommendation:** Have `should_skip_field` return the *reason* rather than a bool (`SkipReason.HIDDEN | SkipReason.NOT_ALLOWED | SkipReason.DEPENDENCY | None`), and carry over only on `HIDDEN`. That makes the coupling explicit and removes the duplicated guards.

---

### `docs/`

**[F36] [SEVERITY: MEDIUM]** — The sync-hook documentation was edited to claim it applies to all built-in clients, on the same branch that made it stop applying to Jira

- **Location:** `docs/configuration.md:275` (changed line: *"Both clients support..."* → *"The built-in clients support running shell commands ... configured under a `commands` subsection"*); `docs/clients/excel-client.md` "Sync hooks" section
- **Confidence:** 🔴 Certain — this is the documentation half of **F1**.
- **Issue:** The edited sentence now asserts that all three built-in clients read hooks from a `commands` subsection. After this branch, Jira reads `sync_commands` (which no model defines), so the statement is false for Jira and the shared reference page that `excel-client.md` links to (`../configuration.md#prepost-sync-commands`) is misleading for one of the three clients it now claims to cover. No doc, and no CHANGELOG entry, mentions a key rename.
- **Category:** Documentation / Bug
- **Recommendation:** Resolve **F1** first. If `commands` stays, the doc is already correct and needs no further change. If `sync_commands` is adopted, update `docs/configuration.md`, `docs/clients/excel-client.md#sync-hooks` and `docs/clients/jira-client.md`, and document the accepted legacy alias.

---

### `CHANGELOG.md`

**[F37] [SEVERITY: LOW]** — No `### Added` for the new client, and no entry for two behaviour/API changes this branch makes *(prior F12, still open)*

- **Location:** `## [Unreleased]` (`:9-17`)
- **Confidence:** 🔴 Certain
- **Issue:** The section contains only two `### Fixed` bullets about empty rows and blank boolean cells. Three things are missing:

  1. **The client itself.** ~2,900 lines of new client code, a new `[excel]` extra, new docs, wizard integration — a reader of the changelog would conclude Excel support already existed and was merely patched.
  2. **The Jira `commands` → `sync_commands` change (F1).** Whether it is a bug or an intentional rename, it changes the config contract for existing deployments and belongs under `### Changed` with migration instructions.
  3. **`ProtocolledString.value` widened from `str` to `str | None`.** This is a response-schema change on a public REST endpoint. The reasoning captured in the new field description is excellent and belongs in the changelog too.
- **Category:** Documentation
- **Recommendation:** Add `### Added` ("Excel/CSV defect client supporting `.xlsx`, `.xls`, `.csv`, `.tsv` and `.txt`, with legacy DMProxy `.properties` compatibility") and `### Changed` entries for items 2 and 3.

---

### `.gitignore` and `examples/`

**[F38] [SEVERITY: LOW]** — `examples/` is added to `.gitignore` by the same branch that commits three files under `examples/excel/project_1/`

- **Location:** `.gitignore:156` (`examples/` added under "Temporary directories and files"); `examples/excel/project_1/*.xls*`
- **Confidence:** 🔴 Certain
- **Issue:** Git keeps already-tracked files tracked, so the three committed workbooks survive — but every *new* file under `examples/` is now invisible to `git status`/`git add`. The working tree already shows the consequence: `examples/excel/project_1/car_config_2.csv`, `config.tsv`, `car_config_2.txt`, `20260610_Earlybird_AIDevOps.pptx` and `car_config_2.xlsx.lock` are all untracked and would be silently skipped by `git add -A`. The result is a directory that is half version-controlled and half not, with no rule a contributor can infer. (The stray `.pptx` and `.lock` also suggest `examples/` is being used as a scratch directory.)
- **Category:** Code Quality
- **Recommendation:** Decide one way: either the example workbooks are fixtures that belong in git (then remove `examples/` from `.gitignore` and add narrow ignores for `*.lock` and scratch files), or they do not (then `git rm --cached` the three committed ones and keep the directory ignored). Do not ship both.

**[F39] [SEVERITY: LOW]** — A committed binary fixture named `car_config - Kopie.xls` ("copy")

- **Location:** `examples/excel/project_1/car_config - Kopie.xls`
- **Confidence:** 🟠 High — I cannot read the binary, so I am judging by the filename.
- **Issue:** The name is the German Windows Explorer default for a duplicated file, which strongly suggests an accidental commit rather than a deliberate second fixture. It also contains spaces and a non-ASCII-friendly naming convention, and — relevant to the client's own behaviour — `_get_file_path` picks the **alphabetically first** matching file in the project directory, so `car_config - Kopie.xls` sorts *before* `car_config.xls` and would be the file the client actually opens for `project_1` with `file_type = ".xls"`. Any manual testing against that directory is exercising the copy, not the intended workbook.
- **Category:** Code Quality
- **Recommendation:** Delete it, or rename it to say what it is for (e.g. `car_config_hidden_sheet.xls`) and note it in a short `examples/excel/README.md`.

---

### `tests/`

**[F40] [SEVERITY: HIGH]** — 16 tests still exercise the deleted `_execute_sync_hook` methods and fail; the extracted helper has no test module of its own

- **Location:** `tests/unit/clients/jira/test_client.py` (`TestExecuteSyncHook`, 7 tests, `:1114-1260`); `tests/unit/clients/jsonl/test_jsonl_client.py` (9 tests, `:557`, `:566`, `:703-779`)
- **Confidence:** 🔴 Certain — verified by grep; the caller confirms 25 failures at the tip against 9 pre-existing.
- **Issue:** `2b45d86` deleted `JiraDefectClient._execute_sync_hook` and `JsonlDefectClient._execute_sync_hook` but updated only the Excel tests. The Jira and JSONL tests still call the removed methods (`client._execute_sync_hook("proj", sync_type, "presync")`) and patch removed module attributes (`clients.jsonl.client.subprocess`). All 16 fail.

  The consequence goes beyond a red suite. Those 16 tests were the *only* coverage of the hook logic — extension validation, missing-file handling, `CalledProcessError`, `OSError`, the "no command configured" acknowledgement. After the migration, the shared `execute_sync_hook` is covered only indirectly by `TestSyncHookCommands` in `tests/unit/clients/excel/test_client.py` (4 tests), which covers the happy path and the no-command path but not the four error branches. And crucially, none of the surviving tests exercise **Jira's** `before_sync`/`after_sync`, which is exactly why **F1** shipped unnoticed.
- **Category:** Missing Test / Bug
- **Recommendation:** Create `tests/unit/clients/test_utils.py` with a `TestExecuteSyncHook` class ported from the Jira/JSONL versions, driving `execute_sync_hook` directly with a `PhaseCommands` instance and covering all six branches. Then rewrite the 16 stale tests to go through `client.before_sync(...)`/`client.after_sync(...)` for each client, which is the level at which **F1** is detectable. Delete nothing until the replacement passes.

**[F41] [SEVERITY: MEDIUM]** — Nothing pins the UDF-clearing / boolean-precedence guard, so the prior review's HIGH-severity fix is unprotected

- **Location:** absent from `tests/unit/clients/excel/test_client.py` and `test_utils.py`
- **Confidence:** 🔴 Certain — grep for `value=None` across `tests/unit/clients/excel/` matches only two unrelated `return_value=None` mock arguments; `TestUdfClearingOnUpdate` does not exist.
- **Issue:** The guard at `excel/utils.py:460-461`

  ```python
  if udf.value is not None or udf.name not in defect_info_data_frame.columns:
      defect_info_data_frame[udf.name] = _cell_for_optional_field(udf.value)
  ```

  is the combined fix for the prior review's F7 (a cleared STRING UDF silently keeping its old value) and F8 (the null half of a boolean UDF's duplicate-entry pair blanking a real transition). The prior review documented five end-to-end `update_defect` tests added for it, and explicitly explained why they must go through `update_defect` against a real file rather than through `create_defect_data_frame` — because the value is dropped by `DataFrame.update` in the *write* path, so a frame-builder unit test would assert `None` and call it correct.

  Those tests are not in the tree at the branch tip. The condition is subtle enough that a well-meaning simplification to `defect_info_data_frame[udf.name] = _cell_for_optional_field(udf.value)` would look like a cleanup and would silently reintroduce a HIGH-severity data-loss bug with a green suite.
- **Category:** Missing Test
- **Where they actually are** *(established by the caller after the review; the reviewing agent's guess that the rebase dropped them is incorrect)*: `git log --all -S"TestUdfClearingOnUpdate"` matches **no commit on any branch**. The class was never committed. It exists only in **`stash@{0}`** — `WIP on excel: 0bbadb5` — at `tests/unit/clients/excel/test_client.py:1241`, containing **4** tests (the prior review's "five" was an overcount):

  - `test_a_string_udf_the_user_cleared_blanks_its_cell`
  - `test_a_string_udf_with_a_value_still_writes_it`
  - `test_a_boolean_udf_transition_survives_either_entry_order`
  - `test_a_udf_absent_from_the_payload_keeps_its_cell`

  Inspect with `git show 'stash@{0}:tests/unit/clients/excel/test_client.py'`. Note that `stash@{0}` also carries a `CHANGELOG.md` hunk that is already committed on the branch (`4cb966c`) and a `.gitignore` change, so apply it selectively rather than with a bare `git stash pop`.
- **Recommendation:** Recover the four cases from `stash@{0}` and commit them (extending to the fifth case the prior review described — boolean duplicate entries with the null entry **first** *and* **last** are two distinct orderings). Confirm the suite fails when the guard is reverted.

**[F42] [SEVERITY: LOW]** — No test covers `before_sync`/`after_sync` for the Jira or JSONL clients after the migration

- **Location:** `tests/unit/clients/jira/`, `tests/unit/clients/jsonl/`
- **Confidence:** 🔴 Certain
- **Issue:** Directly related to **F1** and **F40**. `TestSyncHookCommands` exists for Excel and would have caught the wrong config key had an equivalent existed for Jira — its docstring even states the invariant that was broken: *"The wizard writes sync hooks to 'commands'; the client must read that same key."*
- **Category:** Missing Test
- **Recommendation:** Copy `TestSyncHookCommands` into the Jira and JSONL test modules, parametrised over the client, and assert `subprocess.run` is called with the configured script.

**[F43] [SEVERITY: LOW]** — `tests/unit/utils/test_wizard_excel.py` classes carry no `@pytest.mark.unit`

- **Location:** `TestTransitionsAreControlFieldOnly`, `TestCommandsPrompt`, `TestUserDefinedAttributePrompt`
- **Confidence:** 🔴 Certain
- **Issue:** Every other test module added by this branch marks its tests `@pytest.mark.unit`, and `pyproject.toml:145` declares the marker. There is no `addopts = "-m unit"` today, so the tests do run under the documented `pytest tests/unit -q` — but any future marker-based selection (or a CI job that filters on it) would silently skip 11 tests.
- **Category:** Missing Test / Code Quality
- **Recommendation:** Add `@pytest.mark.unit` to the three classes.

**[F44] [SEVERITY: LOW]** — Several config fixtures pass a *file* path as `excel_file_path`, which is documented as a root *directory*

- **Location:** `tests/unit/clients/excel/test_utils.py` — `_make_csv_config(csv_file)` / `_make_xlsx_config(csv_file)` called with `tmp_path / "defects.csv"` at `:7338`, `:7368`, `:7393`, `:7418`, `:7444`, `:7587`, `:7595`, `:7603`
- **Confidence:** 🔴 Certain
- **Issue:** `excel_file_path` is documented and used as "root directory containing one subdirectory per project", but these fixtures pass a path to a CSV file. It does not matter for the functions under test (`create_defect_data_frame`, `split_references`) because they never touch `excel_file_path` — which is precisely the problem: the tests encode a config shape that could never occur in production, so they mislead a reader about the invariant and would not fail if a future change started resolving paths from it.
- **Category:** Code Quality (tests)
- **Recommendation:** Pass `tmp_path` (the directory) in all eight call sites.

---

## Part 1 Summary Table

| ID | Severity | File | Short title |
| --- | --- | --- | --- |
| F1 | HIGH | clients/jira/client.py | Jira sync hooks silently dead: `sync_commands` key exists on no model |
| F2 | MEDIUM | clients/utils.py | `execute_sync_hook(commands: str)` type hint wrong; `getattr` hides it |
| F3 | MEDIUM | clients/utils.py | `extract_static_attributes` is dead code and collides with the Jira one |
| F4 | LOW | clients/utils.py | `hook_type`/`sync_type` stringly-typed, resolved by reflection |
| F5 | LOW | clients/utils.py | f-string logging inconsistent with both calling clients |
| F6 | MEDIUM | models/config.py | Third duplicate `SyncCommandConfig`/`PhaseCommands`, now load-bearing |
| F7 | MEDIUM | app.py | FQ-path dependency check breaks documented short-form `client_class` |
| F8 | LOW | clients/\_\_init\_\_.py | `__all__` lists a conditionally-imported name; two optional-import idioms |
| F9 | MEDIUM | clients/excel/file_utils.py | Boolean UDF `trueValue`/`falseValue` defaults not applied on read/write |
| F10 | MEDIUM | clients/excel/file_utils.py | Parse-time import warnings lost on every buffered read |
| F11 | LOW | clients/excel/file_utils.py | `try/except KeyError` around an assignment; f-string log |
| F12 | LOW | clients/excel/file_utils.py | Empty column mapping → silent no-op write reported as success |
| F13 | LOW | clients/excel/file_utils.py | Trailing blank rows deleted, contradicting the documented promise |
| F14 | LOW | clients/excel/file_utils.py | `_apply_boolean_udf_write_mapping` mutates the caller's frame |
| F15 | LOW | clients/excel/file_utils.py | Unreachable `mode="w"` branch; its test mocks the failing call |
| F16 | MEDIUM | clients/excel/utils.py | Same field name at two column indices → duplicate DataFrame columns |
| F17 | MEDIUM | clients/excel/utils.py | Control field with empty `values` rejects every create/update |
| F18 | LOW | clients/excel/utils.py | Broken f-string concatenations in two xlsx error messages |
| F19 | LOW | clients/excel/utils.py | Duplicated encoding-fallback loop + unreachable tail |
| F20 | LOW | clients/excel/utils.py | Unused `protocol` parameter; missing return annotation |
| F21 | LOW | clients/excel/utils.py | `map_and_rename_columns` is production dead code |
| F22 | LOW | clients/excel/utils.py | `split_references` falls back to `";"` vs documented `","` |
| F23 | LOW | clients/excel/utils.py | `to_python_datetime_format` replace-chain silently mangles patterns |
| F24 | INFO | clients/excel/utils.py | `duplicated_ids` recomputed two/three times per operation |
| F25 | LOW | clients/excel/client.py | `get_defects_batch` duplicates JSONL's ID-normalization block |
| F26 | LOW | clients/excel/client.py | Third `_build_defect_with_attributes` variant, undocumented |
| F27 | LOW | clients/excel/client.py | `_get_effective_config` re-validates the whole config per request |
| F28 | LOW | clients/excel/client.py | Cleanup thread is unstoppable and started in `__init__` |
| F29 | LOW | clients/excel/client.py | `supports_changes_timestamps` ignores per-project overrides |
| F30 | LOW | clients/excel/client.py | Ambiguous ID reported as "not found" in the extended view |
| F31 | INFO | clients/excel/client.py | `attributes.update({...})` where a comprehension reads better |
| F32 | MEDIUM | pyproject.toml | mypy `ignore_missing_imports` globally + first-party override |
| F33 | LOW | pyproject.toml | Excel extra's pins copy-pasted into `dev` |
| F34 | LOW | utils/wizard.py | Two `# noqa` directives widened from explicit codes to bare |
| F35 | LOW | utils/wizard.py | `get_carried_over_value` duplicates `should_skip_field` guards |
| F36 | MEDIUM | docs/configuration.md | Doc claims all clients read `commands`; Jira no longer does |
| F37 | LOW | CHANGELOG.md | No `### Added`; no entry for the key rename or the API change |
| F38 | LOW | .gitignore | `examples/` ignored while example files are committed |
| F39 | LOW | examples/excel/project_1/ | `car_config - Kopie.xls` looks accidental and sorts first |
| F40 | HIGH | tests/unit/clients/{jira,jsonl}/ | 16 tests call the deleted `_execute_sync_hook`; helper untested |
| F41 | MEDIUM | tests/unit/clients/excel/ | Nothing pins the UDF-clearing/boolean-precedence guard |
| F42 | LOW | tests/unit/clients/{jira,jsonl}/ | No test covers `before_sync`/`after_sync` post-migration |
| F43 | LOW | tests/unit/utils/test_wizard_excel.py | Test classes lack `@pytest.mark.unit` |
| F44 | LOW | tests/unit/clients/excel/test_utils.py | Fixtures pass a file path as `excel_file_path` |

| Severity | Count |
| --- | --- |
| Critical | 0 |
| High | 2 |
| Medium | 10 |
| Low | 29 |
| Info | 3 |
| **Total** | **44** |

---

## Positive Observations

- **The prior review's substantive findings were genuinely fixed, not papered over.** The path-traversal guard (`_resolve_project_path`), the UDF-clearing precedence guard, the length-based ID slice, the buffer-thread sizing across project overrides, and the deletion of the dead legacy scalar mapping are all present and correct in the code — and in most cases the accompanying tests were written to fail against the pre-fix version, which is the right way to prove a fix.
- **`locking.py` remains the strongest module in the branch.** Correct per-platform OS byte-range locks, a thread-local lock layered in front to stop one process's threads fighting over the same handle, a documented rationale for never deleting the sidecar, graceful degradation with a logged warning on a read-only directory, and — notably — `test_lock_excludes_another_process_while_it_is_held`, which spawns a real subprocess rather than mocking the exclusion away.
- **The concurrency tests are real.** `test_concurrent_creates_assign_a_distinct_id_to_every_defect` and `test_concurrent_creates_keep_every_written_defect_in_the_file` run four threads against a real client and a real file with a `threading.Barrier` to force the race. These are the tests that would actually catch a broken lock.
- **The "unusable row" design is well reasoned and well documented.** Empty rows, rows without an ID and rows with duplicate IDs are each reported and skipped rather than failing the whole file, and — crucially — left in place so the frame stays positionally aligned with the file and the user can repair them. The docstrings on `_report_ambiguous_ids`, `_require_mapped_columns` and `_read_dataframe_from_disk` explain *why*, not just *what*, which is rare and genuinely useful.
- **`_cell_for_optional_field`'s docstring** is a model of the form: it names the pandas semantics (`DataFrame.update` skips NA), the protocol contract (TestBench sends the whole defect), and the resulting rule (an empty field is one the user emptied), in four lines.
- **The `ProtocolledString.value` fix** (`str` → `str | None`, never `""`) is correct and the field description explains the downstream TestBench assertion that motivated it — exactly the kind of context that stops someone "simplifying" it back.
- **`TestLegacyScalarKeys`** was written and run *before* the dead legacy mapping was deleted, so it pins pre-existing behaviour rather than describing the new code. That is the right order of operations for a deletion.
- **`get_carried_over_value`** catches a real and easy-to-miss wizard bug (hiding a field silently resetting a configured value) and documents the reasoning; only its structure (**F35**) is worth revisiting.

---

## Recommended Actions Before Merge

1. **Fix F1** — restore `"commands"` in `jira/client.py` (or land the rename properly with aliases, docs and a changelog entry). This is a silent regression for existing Jira deployments and the highest-impact item in the branch.
2. **Fix F2** and **F6** together — type `execute_sync_hook`'s `commands` parameter honestly against a single shared `PhaseCommands`, so F1's failure mode becomes impossible rather than merely absent.
3. **Fix F40 and F42** — get the 16 failing tests green by porting them onto `execute_sync_hook` and adding `before_sync`/`after_sync` coverage for Jira and JSONL. Do not merge with a knowingly red suite; that is what let F1 through.
4. **Restore F41** — the UDF-clearing / boolean-precedence tests. The fix they protect was rated HIGH by the prior review and is currently unpinned.
5. **Fix F9** — apply the documented `"true"`/`"false"` defaults and consistent case handling on the boolean read/write path.
6. **Fix F7** — restore the friendly missing-extra error for the documented short-form `client_class`; `check_client_dependencies` already exists for this.
7. **Fix F17** — treat an empty control-field `values` list as unconstrained; a legacy `.properties` file can otherwise reach a state where every write is refused.
8. **Address F16** — reject duplicate field-name→column mappings at config load. It is the root cause of the one remaining wrinkle in the F7/F8 fix and produces silent data corruption.
9. **Address F10** — replay buffered import warnings, or the client goes quiet about a misconfiguration for up to 24 hours.
10. **Revert F32** — the global mypy `ignore_missing_imports` (and especially the first-party override) weakens checking for the whole repository; narrow it to the module that actually needs it.
11. **Fix F36 and F37** — align the docs with whatever F1 resolves to, and add the missing `### Added` / `### Changed` changelog entries.
12. **Decide F38/F39** — make `examples/` either tracked or ignored, not both, and drop the `- Kopie` workbook.
13. Lower-priority cleanups: F3, F4, F5, F8, F11–F15, F18–F31, F33–F35, F43, F44.

---

## Part 2: Pre-existing Issues Found While Reviewing

> These findings are for code **not introduced by this branch**. The author is not obligated to fix them; they are recorded so they are not lost.

### `src/testbench_defect_service/utils/config.py` and `utils/config_wizard.py`

**[F45] [SEVERITY: MEDIUM]** — The wizard offers `excel_config.properties` as the default separate config file, but `save_properties_config` cannot serialize the Excel client's nested structures

- **Location:** `utils/config_wizard.py:265-266` (`if client_type == "excel": default_path = "excel_config.properties"`) → `utils/config.py:308-313` → `save_properties_config` (`utils/config.py:270-289`)
- **Confidence:** 🟠 High — the code paths are unambiguous; I did not run the wizard to confirm, and it depends on the user accepting the separate-file prompt.
- **Issue:** `save_properties_config` flattens the config with `str_config[key] = str(value)`. `.properties` is a flat key/value format with no nesting, but `ExcelDefectClientConfig` has `control_fields: list[ControlFields]`, `udfs: list[UserDefiendAttributes]`, `commands: PhaseCommands` and `projects: dict[str, ProjectConfig]`. Those come out as Python `repr` strings — `control_fields=[{'name': 'status', 'column_number': 7, ...}]` — which the loader cannot read back: `load_properties_config_from_path` returns them as plain strings and `model_validate` then fails with a validation error on `control_fields`, so the service refuses to start on the config its own wizard just wrote.

  The reverse direction (reading a hand-written legacy `.properties` with `controlFields=status,priority` / `status.columnNo=7`) is well supported by `_normalize_legacy_excel_config`; only the *writing* side is unimplemented. Both the `if client_type == "excel"` branch and `save_properties_config` predate this branch, so this is Part 2 — but note that this branch is what makes `"excel"` selectable in the wizard, so it turns a dormant path into a reachable one.
- **Category:** Bug
- **Recommendation:** Either implement the inverse of `_normalize_legacy_excel_config` (emit `controlFields=`, `<field>.columnNo`, `udf.attr<n>.*` etc.) so the round trip closes, or change the Excel default to `excel_config.toml` and mention in `docs/clients/excel-client.md` that `.properties` is read-only, migration-only input.

### `src/testbench_defect_service/clients/jsonl/client.py`

**[F46] [SEVERITY: LOW]** — `_build_defect_with_attributes` duplicates the logic of the (now caller-less) shared `extract_static_attributes` *(prior F15, still open)*

- **Location:** `:378-397`
- **Confidence:** 🔴 Certain
- **Issue:** The "check the direct attribute, else scan `userDefinedFields`" loop is functionally identical to `clients/utils.extract_static_attributes`. Because the shared helper has no callers at all (**F3**), migrating this one method would both remove the duplication and give the shared function a reason to exist.
- **Category:** Code Duplication

**[F47] [SEVERITY: INFO]** — Redundant `bool(...)` around an already-boolean expression *(prior F16, still open)*

- **Location:** `check_login` (`:53-58`)
- **Confidence:** 🔴 Certain
- **Issue:** `exists = project_path.exists()` … `return bool(exists)`. `Path.exists()` already returns `bool`; both wrappings are no-ops.
- **Category:** Code Quality

### `src/testbench_defect_service/clients/jira/config.py` and `clients/jsonl/config.py`

**[F48] [SEVERITY: LOW]** — Two pre-existing identical `SyncCommandConfig` / `PhaseCommands` pairs

- **Location:** `clients/jira/config.py:26-34`, `clients/jsonl/config.py:6-14`
- **Confidence:** 🔴 Certain
- **Issue:** These two copies predate the branch and are the reason `models/config.py` ended up as a third (**F6**). Consolidating all three onto `models/config.py` is the clean resolution and would let `execute_sync_hook` take a real type.
- **Category:** Code Duplication

---

**Files reviewed with no findings to report:** `src/testbench_defect_service/clients/excel/locking.py` (read in full; the module is sound — the sidecar-retention rationale, the thread-lock-in-front-of-OS-lock layering, and the fail-open-with-warning behaviour are all correct and well justified), `src/testbench_defect_service/clients/excel/config.py` (read in full; the legacy `.properties` folding is careful, the `AliasChoices` coverage matches the documented key table, and `ControlFields.check_transitions_against_values` is correct — the one nit, `separator` declaring `AliasChoices("separator", "separator")` with the same name twice, is harmless), `src/testbench_defect_service/clients/excel/__init__.py` (empty), `src/testbench_defect_service/models/defects.py` (the `SyncContext.iTBProject` and `ProtocolledString.value` changes are both correct), `src/testbench_defect_service/utils/dependencies.py` (`EXCEL_PACKAGES` now populated correctly), `README.md`, `docs/intro.md`, `docs/clients/index.md`, `docs/clients/excel-client.md`, `docs/getting-started/installation.md`, `docs/clients/{custom,jira}-client.md` (sidebar renumbering is consistent; `:::note`/`:::warning` admonitions all balance; cross-links resolve — the only content issue is F36 in `docs/configuration.md`), and the three binary workbook fixtures (contents not reviewable; see F38/F39).

Per the repo's `CLAUDE.md`, the ruff version drift between `.venv` and the pre-commit hook is a known, documented issue and is **not** reported as a defect; F34 concerns only the *widening* of the workaround to two additional functions that previously carried explicit codes.
agentId: a220a9d8184d22b0e (use SendMessage with to: 'a220a9d8184d22b0e', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 330986
tool_uses: 44
duration_ms: 835793</usage>