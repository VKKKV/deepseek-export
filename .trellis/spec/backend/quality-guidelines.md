# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Keep exporter changes small and script-local. Prefer a single, readable implementation with explicit defensive checks over a larger abstraction.

---

## Forbidden Patterns

* Do not fetch DeepSeek sessions with an oversized `count` just to avoid pagination.
* Do not treat `resp.ok` as the only success signal for business endpoints.
* Do not let browser cleanup errors fail an otherwise successful token capture.

---

## Required Patterns

* Page cursor-based session lists with a fixed safe page size.
* Deduplicate sessions by `id` while paginating.
* Preserve diagnostic output when the API returns malformed payloads.

---

## Testing Requirements

At minimum, run `python -m py_compile export.py` and a lightweight local verification of pagination or response parsing when editing the exporter.

---

## Code Review Checklist

* Pagination uses `before_seq_id` and stops correctly.
* Delete handling rejects explicit business errors.
* Cleanup remains best-effort.
* Diagnostics still help when the API payload is malformed.
