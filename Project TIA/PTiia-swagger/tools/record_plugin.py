"""pytest plugin: records every HTTP exchange the TIA test suite makes through Starlette's TestClient.

Loaded from outside the project (no project file is changed):

    PYTHONPATH=../PTiia-swagger/tools SWAGGER_RECORD_OUT=recorded.json python -m pytest -p record_plugin tests

For each route template + method + status it keeps a few real samples (request body, query, response body), which
build_swagger.py turns into response schemas and examples. Credentials are never recorded (no request headers are kept).
"""
from __future__ import annotations

import json
import os
import threading
from urllib.parse import parse_qsl, urlsplit

from starlette.routing import Match
from starlette.testclient import TestClient

MAX_PER_STATUS = 6            # samples kept per (route, method, status)
MAX_BODY_CHARS = 400_000      # a body larger than this is kept as its shape only (first 2 samples)

_lock = threading.Lock()
_data: dict = {}              # "METHOD template" -> {"method", "path", "statuses": {status: [sample, ...]}, "calls": n}
_unmatched: dict = {}
_orig = TestClient.request


def _template(app, method: str, path: str):
    """The route template the app would dispatch this request to (Starlette's own matcher)."""
    routes = getattr(getattr(app, "router", None), "routes", None) or getattr(app, "routes", None) or []
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "path_params": {}}
    partial = None
    for r in routes:
        try:
            m, _ = r.matches(scope)
        except Exception:                                   # noqa: BLE001 - a recorder must never break a test
            continue
        if m == Match.FULL:
            return getattr(r, "path", None) or getattr(r, "path_format", None)
        if m == Match.PARTIAL and partial is None:
            partial = getattr(r, "path", None)
    return partial


def _jsonish(text: str):
    try:
        return json.loads(text), True
    except Exception:                                       # noqa: BLE001
        return None, False


def _record(client, method, url, kwargs, resp):
    method = method.upper()
    parts = urlsplit(str(url))
    path = parts.path or "/"
    tmpl = _template(client.app, method, path)
    if tmpl is None:
        with _lock:
            _unmatched[f"{method} {path}"] = _unmatched.get(f"{method} {path}", 0) + 1
        return
    req_body = kwargs.get("json")
    if req_body is None and kwargs.get("content") is not None:
        c = kwargs["content"]
        req_body, ok = _jsonish(c.decode("utf-8", "replace") if isinstance(c, (bytes, bytearray)) else str(c))
        if not ok:
            req_body = {"__non_json__": True}
    if req_body is None and kwargs.get("files"):
        req_body = {"__multipart__": sorted(kwargs["files"].keys()) if isinstance(kwargs["files"], dict) else True}
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    if isinstance(kwargs.get("params"), dict):
        q.update({k: v for k, v in kwargs["params"].items()})
    ctype = resp.headers.get("content-type", "")
    text = None
    try:
        text = resp.text
    except Exception:                                       # noqa: BLE001
        text = None
    body, is_json = (_jsonish(text) if text is not None and "json" in ctype else (None, False))
    sample = {"path": path, "query": {k: str(v) for k, v in q.items()}, "request": req_body, "status": resp.status_code,
              "content_type": ctype.split(";")[0].strip()}
    if is_json:
        sample["response"] = body
        sample["size"] = len(text)
    else:
        sample["response_text"] = (text or "")[:600] if text is not None else None
        sample["size"] = len(text or "")
    key = f"{method} {tmpl}"
    with _lock:
        ent = _data.setdefault(key, {"method": method, "path": tmpl, "statuses": {}, "calls": 0})
        ent["calls"] += 1
        lst = ent["statuses"].setdefault(str(resp.status_code), [])
        big = sample["size"] > MAX_BODY_CHARS
        if len(lst) < (2 if big else MAX_PER_STATUS):
            lst.append(sample)


def _patched(self, method, url, *args, **kwargs):
    resp = _orig(self, method, url, *args, **kwargs)
    try:
        _record(self, method, url, kwargs, resp)
    except Exception:                                       # noqa: BLE001 - recording is best effort
        pass
    return resp


TestClient.request = _patched


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("SWAGGER_RECORD_OUT", "recorded.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"exit_status": int(exitstatus), "routes": _data, "unmatched": _unmatched}, f, default=str)
