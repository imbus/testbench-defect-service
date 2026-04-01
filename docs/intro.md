---
sidebar_position: 1
title: Introduction
---

# Introduction

[**Testbench Defect Service**](https://github.com/imbus/testbench-defect-service) is a lightweight, asynchronous REST API service that acts as a bridge between [Imbus TestBench](https://www.testbench.com/de/) and external defect tracking systems.

## What It Does

TestBench works with defect data — creating, reading, updating, and deleting bug reports during test execution. The Defect Service provides a unified API layer that allows TestBench to communicate with any supported backend without being tied to a specific tool.

At its core the service:

- Exposes a stable HTTP API that TestBench calls to manage defects.
- Translates those API calls into backend-specific operations.
- Returns structured responses that TestBench can understand regardless of which backend is used.

## Key Features

- **Pluggable clients** — swap the backend without touching TestBench configuration.
- **Per-project configuration** — control fields, attributes, and sync commands can all be overridden per project.
- **Pre/post sync hooks** — run custom shell commands before or after TestBench syncs defects.
- **Authentication** — simple username/password auth with salted bcrypt hashing.
- **SSL/TLS support** — optional HTTPS with one-way TLS or mutual TLS (mTLS).
- **Interactive setup wizard** — `init` and `configure` commands guide you through configuration interactively.

## Architecture

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

The service is built on [Sanic](https://sanic.dev), a Python async web framework, and is designed to be fast and resource-efficient even when running alongside TestBench on the same machine.

## Supported Backends

| Backend | Class | Description |
|---|---|---|
| [**JSONL**](clients/jsonl-client.md) | `testbench_defect_service.clients.JsonlDefectClient` | Stores defects as newline-delimited JSON files on disk. No external dependencies. Ideal for local use and testing. |
| [**Jira**](clients/jira-client.md)| `testbench_defect_service.clients.JiraDefectClient` | Full integration with Jira Cloud or Jira Data Center / Server. Requires the optional `[jira]` extra. |

The backend is selected via the `client_class` configuration key and can be switched at any time by updating the config file and restarting the service.


