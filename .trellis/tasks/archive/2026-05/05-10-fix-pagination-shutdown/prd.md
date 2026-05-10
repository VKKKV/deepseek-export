# Fix DeepSeek Pagination And Browser Shutdown

## Goal

Make the exporter reliably fetch all DeepSeek Web Chat sessions without hitting the API count limit, avoid browser shutdown crashes on Wayland/Hyprland, and keep delete/export API handling defensive enough for real-world responses.

Validate the fix against an end-to-end export run, not just isolated pagination calls.

## What I Already Know

* The current `fetch_all_sessions` sends `count=500`, which can trigger DeepSeek `ILLEGAL_COUNT` because the observed safe page size is around 50 and the upper limit is about 200.
* DeepSeek supports cursor pagination through `before_seq_id`; the next cursor should be derived from the previous page, preferably `biz_data.next_seq_id` when present or the minimum numeric `seq_id` in the page.
* Token acquisition via Playwright response interception is the working path; `localStorage.userToken` is not reliable because it can contain a JSON wrapper with `value: null`.
* Wayland/Hyprland Chromium shutdown can crash during `context.close()`, so browser cleanup should be best-effort and not turn a successfully captured token into a failure.
* `fetch_messages` already uses defensive parsing for `data.biz_data.messages`.
* `delete_session` currently treats HTTP 200 as success but DeepSeek may signal business success through a JSON `code: 0` shape.

## Requirements

* Fetch sessions using page size 50 by default, not a single large request.
* Iterate pages with `before_seq_id` until the API reports no more pages or no usable cursor can be advanced.
* Preserve the existing `--count` CLI meaning as the maximum number of sessions to export.
* Avoid duplicate sessions if pagination returns overlapping rows.
* Keep diagnostic output when no sessions are returned or an API page response is unexpected.
* Close Playwright resources defensively so shutdown errors do not mask successful token capture.
* Treat delete success defensively by accepting HTTP success plus either `code == 0`, absent JSON success metadata, or another clearly successful response shape if observed in code.

## Acceptance Criteria

* [ ] Running with the default `--count 500` does not call `fetch_page` with `count=500`.
* [ ] `fetch_all_sessions` requests multiple pages using `before_seq_id` and stops at `has_more == false` or the requested maximum.
* [ ] A session list larger than one page can be exported without `ILLEGAL_COUNT`.
* [ ] Token capture still succeeds if `context.close()` raises during cleanup.
* [ ] Delete failures are not silently counted as success when the API returns an explicit non-zero business code.
* [ ] A full export dry run or live run demonstrates the pagination path works with multiple pages.
* [ ] Existing README usage remains valid.

## Definition Of Done

* Relevant parsing/pagination logic is covered by tests or a lightweight verification path suitable for this script.
* Lint/type/syntax checks pass for the Python script.
* README is updated only if CLI behavior or usage text changes.

## Technical Approach

Implement cursor pagination in `fetch_all_sessions` with a fixed API page size capped at 50 and a separate `limit`/maximum value from CLI `--count`. Track seen session IDs to avoid duplicates. Use `biz_data.has_more` and `biz_data.next_seq_id` when available, falling back to the minimum numeric `seq_id` from the current page. Add guarded Playwright cleanup around `page.close()` and `context.close()`. Update delete response handling to parse JSON when possible and reject explicit business errors.

## Decision (ADR-lite)

**Context**: DeepSeek's internal API rejects overly large `count` values and exposes cursor pagination. The exporter needs to remain a single-file script with minimal dependencies.

**Decision**: Keep the CLI unchanged, but internally page with `count=50` and `before_seq_id` until enough sessions are collected.

**Consequences**: Exporting many sessions now makes more API calls, but avoids known API limits and supports complete export.

## Out Of Scope

* Adding a new API client abstraction or large refactor.
* Supporting the alternate pinned/updated_at cursor format unless `before_seq_id` is unavailable in practice.
* Changing the Markdown output format.

## Technical Notes

* Main script: `export.py`.
* CLI/docs: `README.md`.
* Project dependencies: `requests`, `playwright`; no test framework is currently configured.
* Backend spec index exists at `.trellis/spec/backend/index.md`, but project-specific guideline files are currently placeholders.
