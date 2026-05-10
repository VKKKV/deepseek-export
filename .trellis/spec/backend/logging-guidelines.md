# Logging Guidelines

> How logging is done in this project.

---

## Overview

This project uses simple stdout diagnostics rather than a logging framework. Messages should be user-facing, short, and useful for debugging pagination, token capture, and delete failures.

---

## Log Levels

* `info`: normal progress output such as opening the browser or exporting a session.
* `warn`: recoverable anomalies such as malformed API pages or skipped sessions.
* `error`: unrecoverable failures such as token acquisition failure.

---

## Structured Logging

No structured logger is configured. Keep ad hoc messages consistent and avoid dumping full payloads unless truncated for diagnostics.

---

## What to Log

* Pagination stops and why they stopped.
* Token capture progress.
* Delete failures with enough context to identify the affected session.

---

## What NOT to Log

* Bearer tokens.
* Full API payloads unless truncated for troubleshooting.
* Unnecessary localStorage contents beyond brief debugging previews.
