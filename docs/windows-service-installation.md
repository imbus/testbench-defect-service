---
sidebar_position: 7
title: Windows Service Installation
---

The TestBench Defect Service can be deployed as a Windows service for automatic startup and process management.

For the full installation guide covering NSSM, FireDaemon, YAJSW, and Windows Task Scheduler, see the [**Windows Service Installation Guide**](../docs/windows-service-installation).

Use these values when following the central guide:

| Placeholder | Value |
|-------------|-------|
| `<serviceName>` | `TestBenchDefectService` |
| `<serviceDisplayName>` | `TestBench Defect Service` |
| `<serviceExecutable>` | `testbench-defect-service.exe` |
| `<servicePort>` | `8030` |
| `<serviceInstallDir>` | Your installation directory, e.g. `C:\TestBenchDefectService` |

:::note Executable path
- **Ready-to-use executable**: `C:\TestBenchDefectService\testbench-defect-service.exe`
- **Python venv**: `C:\TestBenchDefectService\.venv\Scripts\testbench-defect-service.exe`

See [Installation](getting-started/installation.md) for details.
:::
