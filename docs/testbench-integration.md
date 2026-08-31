---
sidebar_position: 6
title: TestBench Integration
---
# TestBench Integration

This page explains how to connect TestBench to the running TestBench Defect Service.

---

## Overview

TestBench communicates with the Defect Service through the **DMProxy** (Defect Management Proxy) component. The connection is configured via two `.properties` files in the TestBench installation directory.

---

## Requirements

- TestBench Defect Service is installed and running (see [Quick Start](getting-started/quickstart.md)).
- You know the host and port the service is listening on.
- You have set credentials with `testbench-defect-service set-credentials`.

---

## Configuration in TestBench

The DMProxy is a component of the TestBench installation, located at e.g.:

```
C:\imbus\TestBench\iTB_DMProxy\
```

It contains two relevant configuration files:

### 1. Wrapper configuration

Located in the `wrapper-config` subdirectory, e.g.:

```
C:\imbus\TestBench\iTB_DMProxy\wrapper-config\DefectService_wrapper.properties
```

This file registers the Defect Service as a repository and points to its settings. **You typically do not need to change anything here**, but verify it contains:

```properties
main-class = de.imbus.testbench.service.dm.DefectServiceWrapper
# Repository identifier as it appears in TestBench (must match the service name in config.toml)
name=DefectService
settings = ../defectServiceWrapper/DefectService_settings.properties
```

The `name` value is the repository identifier that appears in TestBench. The `settings` path points to the service settings file (relative to the wrapper config file).

### 2. Service settings

Located at (relative to the DMProxy directory):

```
C:\imbus\TestBench\iTB_DMProxy\defectServiceWrapper\DefectService_settings.properties
```

**This is the file you need to edit.** Set the URL to match the host and port the Defect Service is listening on:

```properties
# Server configuration
server.url=http://127.0.0.1:8030
```

If you configured HTTPS, use `https://` instead and ensure the TestBench host trusts the certificate.

---

## Verifying the connection

1. Start the Defect Service:
   ```bash
   testbench-defect-service start
   ```
2. Open `http://127.0.0.1:8030/check-login` in a browser (or use curl) — it should return `200 OK`.
3. Start the DMProxy.
4. Open TestBench, select the Defect Service as defect management system for your project, enter login data, select a project and trigger a defect synchronization. Check the service logs for incoming requests.

---

## Migrating to the New Service

Use this procedure to migrate from the legacy Defect Service setup to the new architecture without losing synchronization.

:::warning
 During setup and integration, the new service name must be exactly the same as the old service name. Any mismatch will break the integration.
:::

### Migration steps

1. **Set up the new Defect Service**
   Initialize and configure `testbench-defect-service` in your environment.

   :::tip[Convert the old configuration instead of retyping it]
   If the previous setup used a Jira `.conf` or an Excel `.properties` wrapper file, convert it
   directly:

   ```bash
   testbench-defect-service migrate --from jira.conf
   ```

   The [Migration guide](migration.md) covers what is carried over and what you are asked for.
   :::

   :::tip
   If you are migrating an existing setup, use the values from your current DMProxy `.properties` files as input for the service configuration. This is especially helpful when running the configuration wizard, because you can reuse the existing service-related values instead of entering them again manually. For the initial setup flow, see [Quickstart](getting-started/quickstart.md) and [Configuration](configuration.md).

   The current DMProxy configuration is usually the best reference for the values you need during migration:

   - Use the existing repository name from the [wrapper configuration](#1-wrapper-configuration).
   - Use the current connection details from the [service settings](#2-service-settings).
   :::

   Requirement: The configured service name must match the previous service name character-for-character.
2. **Integrate with DMProxy**
   Register the new service in DMProxy as described on this page.

   Requirement: The service name used in DMProxy must be identical to the previous service name.
3. **Start both services**
   After configuration is complete, start:

   - `testbench-defect-service`
   - `DMProxy`
4. **Update credentials in TestBench**
   Open TestBench and go to Defect Manager. Update the credentials for the migrated service connection.
5. **Reselect and synchronize the project**
   Complete the migration in your project workspace:

   - Reselect the project once in the UI (even if it is already selected).
   - Trigger a manual synchronization.

---

## Troubleshooting

| Symptom                | Likely cause                            | Fix                                                                      |
| ---------------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| `Connection refused` | Service is not running or port mismatch | Start the service; verify `host` and `port` in config. |
| `401 Unauthorized`   | Wrong credentials                       | Re-run `testbench-defect-service set-credentials`.     |
| `500 Server Error`   | Service or client misconfiguration      | Check service logs; run `configure --view` to inspect current settings. |

---

## Network considerations

- By default the service listens on `127.0.0.1` (loopback only). To accept connections from another machine (e.g. TestBench running on a different host), set `host = "0.0.0.0"` in `config.toml`.
- If a firewall is in place, open the configured port (default `8030`).
- For production deployments, consider enabling HTTPS — see [Configuration](configuration.md#https--tls).
