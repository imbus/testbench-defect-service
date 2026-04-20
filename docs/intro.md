---
sidebar_position: 1
title: Introduction
---

# Introduction

[**TestBench Defect Service**](https://github.com/imbus/testbench-defect-service) is a lightweight, asynchronous REST API service that acts as a bridge between [imbus TestBench](https://www.testbench.com) and external defect tracking systems.

## What it does

TestBench works with defect data — creating, reading, updating, and deleting bug reports during test execution. The Defect Service provides a unified API layer that allows TestBench to communicate with any supported backend without being tied to a specific tool.

At its core the service:

- Exposes a stable HTTP API that TestBench calls to manage defects.
- Translates those API calls into backend-specific operations.
- Returns structured responses that TestBench can understand regardless of which backend is used.

## Features

- **Pluggable clients** — swap the backend without touching TestBench configuration.
- **Per-project configuration** — control fields, attributes, and sync commands can all be overridden per project.
- **Pre/post sync hooks** — run custom shell commands before or after TestBench syncs defects.
- **Authentication** — simple username/password auth with salted bcrypt hashing.
- **SSL/TLS support** — optional HTTPS with one-way TLS or mutual TLS (mTLS).
- **Interactive setup wizard** — `init` and `configure` commands guide you through configuration interactively.

## Architecture

The service runs a [Sanic](https://sanic.dev)-based HTTP server and delegates all domain logic to a configured `DefectClient` implementation.

```
┌──────────────────────────────────────┐
│          TestBench DM Proxy          │
└───────────────────┬──────────────────┘
                    │  HTTP (Basic Auth)
┌───────────────────▼──────────────────┐
│      TestBench Defect Service        │
│                (Sanic)               │
├──────────────────────────────────────┤
│            DefectClient              │
├───────────────────┬──────────────────┤
│        JSONL      │       Jira       │
└──────────┬────────┴────────┬─────────┘
           │                 │
     .jsonl files      Jira REST API
```

## Supported Backends

| Backend | Class | Description |
|---------|-------|-------------|
| [**JSONL**](clients/jsonl-client.md) | `testbench_defect_service.clients.JsonlDefectClient` | Stores defects as newline-delimited JSON files on disk. No external dependencies. Ideal for local use and testing. |
| [**Jira**](clients/jira-client.md) | `testbench_defect_service.clients.JiraDefectClient` | Full integration with Jira Cloud or Jira Data Center / Server. Requires the optional `[jira]` extra. |

The backend is selected via the `client_class` configuration key and can be switched at any time by updating the config file and restarting the service.

## Where to go next

- **New here?** Start with the [Installation](getting-started/installation.md) and [Quickstart](getting-started/quickstart.md) guides.
- **Configuring the service?** See the [Configuration](configuration.md) page.
- **Choosing a client?** Check the [Clients overview](clients/index.md), then dive into [JSONL](clients/jsonl-client.md) or [Jira](clients/jira-client.md).
- **Running as a Windows service?** See the [Windows service guide](windows-service-installation.md).
- **CLI reference?** See the [CLI commands](cli.md) page.

