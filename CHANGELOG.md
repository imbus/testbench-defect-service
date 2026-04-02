# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-04-01

### Added

- Initial release of TestBench Defect Service.
- REST API for managing defects backed by Jira or JSONL (file-based) clients.
- Interactive configuration wizard (`testbench-defect-service init`).
- HTTP Basic Authentication for API access.
- OpenAPI / Swagger UI documentation served at `/docs`.
- Pre/post sync command hooks.
- Support for multiple projects from a single service instance.
- CLI entry point (`testbench-defect-service`) with `init`, `start`, and `set-credentials` commands.
- `jira` optional dependency group for Jira backend support.

[0.1.0]: https://github.com/imbus/testbench-defect-service/releases/tag/v0.1.0
