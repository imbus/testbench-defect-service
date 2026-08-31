---
sidebar_position: 4
title: Migration
---
# Migrating a legacy configuration

Earlier TestBench defect wrappers were configured with a Jira `.conf` file or an Excel
`.properties` file. The `migrate` command reads one of those files and writes an equivalent
`config.toml` for this service, so you do not have to re-enter settings that the old file
already holds.

```bash
testbench-defect-service migrate --from PATH [--path PATH] [--type excel|jira]
```

:::note
Only the Jira and Excel clients have a legacy wrapper format. There is nothing to migrate for
the JSONL client — configure it with [`init`](cli.md#init).
:::

---

## Before you start

1. **Locate the legacy file.** It is the file the old wrapper was started with — a `.conf` for
   Jira, a `.properties` for Excel. In a DMProxy installation it usually sits next to the
   wrapper, e.g. `C:\imbus\TestBench\iTB_DMProxy\jiraRest\` or `C:\imbus\TestBench\iTB_DMProxy\excel\`.
2. **Install the matching extra.** The migration validates against the client model, and the
   Jira flow refuses to run without the Jira dependencies:

   ```bash
   pip install "testbench-defect-service[jira]"    # or [excel]
   ```

   See [Installation](getting-started/installation.md).
3. **Keep the old file.** `migrate` only reads it; it is never modified. Leave it in place until
   the new service has synchronized successfully.
4. **Note the service name.** The `name` / `systemName` from the legacy file must stay
   character-for-character identical, or TestBench will not recognize the migrated connection.
   See [Migrating to the New Service](testbench-integration.md#migrating-to-the-new-service).

---

## What the command does

1. Detects the legacy format from the file extension (`.conf` → Jira, `.properties` → Excel).
2. Parses the file with the parser for that format. A line it cannot read, or a key set twice
   to two different values, aborts the migration and names the file and line number.
3. Asks for the settings the legacy format never carried — the service credentials, and for
   Jira the authentication method.
4. Validates the result against the same client model the service loads at startup, filling in
   documented defaults for everything the legacy file does not mention.
5. Lists the legacy entries that have no equivalent in the new configuration, so a setting
   that mattered can be applied by hand.
6. Writes the TOML file.

The conversion runs to completion **before anything is written**. Cancelling a prompt, or a
value the service would reject, aborts the migration and leaves an existing configuration
exactly as it was.

---

## Migrating a Jira wrapper (`.conf`)

```bash
testbench-defect-service migrate --from jira.conf
```

A legacy `.conf` file is a list of `key: value` lines; `#` starts a comment and surrounding
double quotes are stripped:

```conf
# jira.conf
wrapper.name: "JiraService"
wrapper.readonly: false
wrapper.timeout_seconds: 30
jira.baseUri: "https://your-domain.atlassian.net"
jira.baseQuery: "project = BUG ORDER BY created DESC"
jira.username: "jira-user@example.com"
```

### What is carried over

| Legacy key                  | TOML option    | Notes                                             |
| --------------------------- | -------------- | ------------------------------------------------- |
| `wrapper.name`            | `name`       | The display name TestBench uses. Must not change. |
| `jira.baseUri`            | `server_url` | Also pre-fills the server URL prompt.             |
| `jira.baseQuery`          | `defect_jql` | The JQL that selects the defects to read.         |
| `wrapper.readonly`        | `readonly`   | See the warning below.                            |
| `wrapper.timeout_seconds` | `timeout`    |                                                   |

`jira.username` (also `jira.user` / `jira.login`) is used as the **default for the username
prompt**, not written directly — which credentials are needed depends on the authentication
method you choose.

Every other key in the `.conf` is ignored. The old wrapper's field mapping has no equivalent in
the new Jira client, which is configured through `field_mappings`, `status_mapping` and the
per-project options described on the [Jira client](clients/jira-client.md) page. Options the
`.conf` says nothing about are written with the client model's documented defaults, so the
generated file is complete and self-explanatory.

### What you are asked for

| Prompt                                                                       | Why                                                                                                                                                            |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Service credentials** (username, password)                           | They protect this service's own HTTP API and have no counterpart in the legacy wrapper. A fresh`password_hash` and `salt` are derived from what you enter. |
| **Jira authentication** (`auth_type` and the credentials it implies) | The legacy wrapper stored its Jira credentials outside the`.conf`.                                                                                           |

The authentication prompts are the same ones [`configure`](cli.md#configure) uses, including the
choice of `basic`, `token`, `oauth1`, `oauth2 2LO (service account)` and
`oauth2 3LO (user account)`.

For the OAuth2 flows:

- The **client secret** is written to `.env` as `JIRA_OAUTH2_CLIENT_SECRET`, never into the
  TOML file.
- For **3LO**, the browser-based OAuth wizard runs when no refresh token is available, and the
  resulting refresh token is stored in the token cache rather than in the configuration.

:::warning[readonly defaults to true]
A legacy file that says nothing about writing is converted into a **read-only** client. The old
wrappers were set up per system by an administrator, so silently granting write access would be
the more dangerous guess. If the migrated service must create and update defects, set
`readonly = false` in the generated file — or set `wrapper.readonly: false` (Jira) /
`readOnly=false` (Excel) in the legacy file before migrating.
:::

---

## Migrating an Excel wrapper (`.properties`)

```bash
testbench-defect-service migrate --from genericexcel.properties
```

A legacy `.properties` file is a list of `key=value` lines; `#` and `!` start a comment:

```properties
# genericexcel.properties
systemName=Excel
excelFilePath=C:\\defects\\excel
fileType=.xlsx
worksheetName=Defects
readOnly=false
defects.header.line=1
defects.data.startingLine=2
defect.id.columnNo=1
defect.title.columnNo=2

controlFields=status,priority
status.columnNo=7
status.value=open,in_progress,closed

status.transition.number=2
status.transition1=open-in_progress
status.transition2=in_progress-closed

udf.attr.number=1
udf.attr1.name=Customer
udf.attr1.column=10
udf.attr1.type=STRING
```

### What is carried over

The Excel client reads the legacy key names itself, so the whole file is converted:

- **Scalar keys** — `systemName`, `excelFilePath`, `defect.id.columnNo` and the rest — map onto
  their modern option through the aliases listed under
  [Key mapping](clients/excel-client.md#key-mapping).
- **Composite keys** are reassembled into their nested shape: `controlFields` plus the
  per-field `*.columnNo` / `*.value` keys become `control_fields`, `*.transition<n>` entries
  become `transitions` on the control field they belong to, and `udf.attr<n>.*` become `udfs`.
- **Unknown keys are ignored** — settings from the old wrapper that the client has no option for
  simply do not appear in the result.
- `excelFilePath` is resolved and written as an **absolute** path, relative to the directory
  `migrate` runs in. A relative path in the legacy file would otherwise be resolved against the
  service's working directory later, which is a different directory when it runs as a Windows
  service.

The only prompt is for the **service credentials**; everything else comes from the file.

:::tip[Per-project properties files]
A `<Project>.properties` file next to the project's data directory does not need migrating. The
Excel client reads it at runtime and accepts the legacy key spelling there too — see
[`<Project>.properties` beside the data](clients/excel-client.md#projectproperties-beside-the-data).
:::

---

## Choosing the output path and the source type

| Option                  | Description                                                   | Default                          |
| ----------------------- | ------------------------------------------------------------- | -------------------------------- |
| `--from PATH`         | Legacy`.conf` or `.properties` file to convert (required) | —                               |
| `--path PATH`         | Configuration file to write                                   | `config.toml`                  |
| `--type [excel\|jira]` | Legacy source type                                            | detected from the file extension |

Pass `--type` when the file has been renamed and its extension no longer identifies the format:

```bash
# Write somewhere other than the working directory
testbench-defect-service migrate --from jira.conf --path /etc/defect-service/config.toml

# The extension no longer says which wrapper this is
testbench-defect-service migrate --from wrapper.txt --type jira
```

If the target file already exists you are asked to confirm, and the existing file is renamed to
`config.toml.backup` — timestamped when a backup is already present — before the new one is
written.

---

## After migrating

1. **Review the generated file.** It contains every option, including the defaults that were
   filled in, so it is worth reading once against the [Configuration](configuration.md)
   reference. Check `readonly` in particular.

   ```bash
   testbench-defect-service configure --view
   ```
2. **Adjust anything the legacy format could not express** — logging, SSL, `host` / `port`,
   per-project overrides and sync commands all take their defaults from the service model:

   ```bash
   testbench-defect-service configure
   ```
3. **Start the service** and check the log for a successful client initialization:

   ```bash
   testbench-defect-service start
   ```
4. **Reconnect TestBench.** Register the service in DMProxy under the unchanged service name,
   update the credentials in Defect Manager, reselect the project and trigger a
   synchronization. The full procedure is in
   [Migrating to the New Service](testbench-integration.md#migrating-to-the-new-service).

---

## Troubleshooting

| Message                                                                                   | Cause                                                                                                     | Fix                                                                                     |
| ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `Cannot tell the legacy format of '<file>' from its extension.`                         | The file is neither`.conf` nor `.properties`.                                                         | Pass`--type jira` or `--type excel`.                                                |
| `<file> line <n>: expected 'key: value', got '<line>'`                                  | The line carries no separator. When it uses the other format's separator the message says so — usually a wrapper file migrated with the wrong `--type`. | Fix the line, comment it out with `#`, or pass the `--type` the message names. Nothing was written. |
| `<file> line <n>: '<key>' is set twice, to '<a>' and '<b>'.`                            | The legacy file gives one key two different values, so there is no telling which one to migrate. | Remove one of the two entries and run `migrate` again. |
| `Cannot convert the Jira .conf file: <field>: <message>`                                | A converted value is not valid for the client model.                                                      | Correct the named key in the legacy file and run`migrate` again. Nothing was written. |
| `Cannot convert the Excel .properties file: <field>: <message>`                         | The same, for the Excel model — usually a missing`excelFilePath` or an unsupported `fileType`.       | As above.                                                                               |
| `Jira authentication setup was cancelled` / `Service credentials setup was cancelled` | A prompt was aborted.                                                                                     | Re-run the command; the existing configuration was not touched.                         |
| The Jira extra is reported as missing                                                     | The Jira dependencies are not installed, so the authentication prompts cannot run.                        | `pip install "testbench-defect-service[jira]"`                                        |
| Defects are visible but cannot be changed                                                 | `readonly` defaulted to `true`.                                                                       | Set`readonly = false` in the generated configuration.                                 |

### Entries that were not carried over

A legacy file may configure things the new client has no equivalent for. Those entries are
listed once every prompt is answered, immediately before the file is written:

```text
════════════════════════════════════════════════════════════
⚠️  2 legacy setting(s) were NOT carried over
════════════════════════════════════════════════════════════
  • jira.password
  • wrapper.class

Nothing in the new configuration reads them. The legacy file is unchanged,
so anything that still matters can be applied to the new file by hand.
════════════════════════════════════════════════════════════
```

Apart from those keys the migration is complete — nothing else was dropped silently.

### Rolling back

The migration writes exactly one file. To go back, restore the `config.toml.backup*` file that
`migrate` created, or delete the generated configuration — the legacy `.conf` / `.properties`
file is untouched and can be migrated again at any time.

---

## See also

- [CLI reference for `migrate`](cli.md#migrate)
- [Legacy `.properties` configuration](clients/excel-client.md#legacy-properties-configuration) — running the Excel client directly off a `.properties` file, without converting it
- [TestBench Integration](testbench-integration.md) — wiring the migrated service into DMProxy
