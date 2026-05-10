# Error Handling

> How errors are handled in this project.

---

## Overview

External API responses are parsed defensively. HTTP success alone is not enough; business-level failure can still be encoded in JSON payloads.

---

## Error Types

This project does not define a custom error hierarchy for the exporter script. It uses simple boolean returns and logged messages for recoverable API failures.

---

## Error Handling Patterns

### Pattern: Best-effort cleanup

Cleanup must not hide successful work. Browser shutdown errors are swallowed after logging.

```python
try:
    page.close()
except Exception:
    pass

try:
    context.close()
except Exception as e:
    print(f"  浏览器关闭时忽略错误: {e}")
```

### Pattern: Defensive JSON parsing

Always guard `.json()` and nested payload access when calling DeepSeek APIs.

```python
def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return None
```

### Pattern: Alternate list payloads

DeepSeek endpoints can move list payloads between `data.biz_data`, `biz_data`, `data`, and the root object. When parsing message history, check each candidate location and accept list-valued candidates directly.

Do not return early on an empty list if another candidate key may contain real data.

---

## API Error Responses

Treat these payload signals as failure when present:

* `code` not in `(0, "0", None, "")`
* `success is False`
* `ok is False`

If the response body is not JSON, fall back to HTTP success only when the endpoint is known to return plain success without payload metadata.

---

## Common Mistakes

### Common Mistake: Trusting HTTP status alone

The delete endpoint may return HTTP 200 but still carry a business failure in JSON. Always inspect the payload first.

### Common Mistake: Letting cleanup raise

Context shutdown on Wayland/Hyprland can raise even after successful token capture. Cleanup should be best-effort.

### Common Mistake: Treating one empty list as authoritative

Some payloads include an empty `messages` key while the real records live under another key such as `items` or `chat_messages`. Search all known candidate keys before deciding a conversation is empty.
