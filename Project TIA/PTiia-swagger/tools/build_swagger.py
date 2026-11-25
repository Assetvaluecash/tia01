"""Builds the complete OpenAPI (Swagger) document of the TIA API into PTiia-swagger/.

    python build_swagger.py --recorded recorded.json        # after running the test suite with record_plugin.py

Sources, all from the code (nothing typed by hand except the overview text):
  * the FastAPI application's own route table and schema (tia.api.create_app), including the 11 routes the app hides from its
    built-in schema (sign-in flow, web pages, health, metrics);
  * the permission of each route and the roles that hold it (tia.rbac.ROUTES / PERMISSIONS);
  * the response format of every exercised route, inferred from the real responses the test suite received (record_plugin.py),
    with one real example per status (secrets and local paths removed, long lists cut to 3 items).

Writes openapi.json, openapi.yaml, spec.js (for the offline Swagger UI page) and COVERAGE.md.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
PROJECT = OUT.parent
DEV = PROJECT / "development"
sys.path.insert(0, str(DEV))

from tools.gen_docs import build_app  # noqa: E402
from tia import __version__ as TIA_VERSION, rbac  # noqa: E402

# ---------------------------------------------------------------------------------------------------------------------- grouping
TAGS = [
    ("Impact analyses", "Run, list, reproduce and read impact analyses; the report and its tester views."),
    ("Tester views", "Test scope, coverage, automation inventory, flows and scripts for testers."),
    ("Code graph", "The dependency graph: views, direct questions, versions, Neo4j sync and ontology."),
    ("Repositories", "Register, sync, discover, upload and remove repositories."),
    ("Uploads", "Code upload sessions (zip archive or folder) that become repositories."),
    ("Evidence", "CI results, coverage, runtime observations, deployments, builds and their snapshots."),
    ("Releases and incidents", "Releases, environments, temporal comparisons, incidents and investigations."),
    ("Knowledge Fabric", "The TIA <-> Knowledge Fabric 2.5 bridge, review of links, products and the KF retriever door (/query/tia)."),
    ("Jobs", "The asynchronous job queue."),
    ("Webhooks", "Pull-request events from GitHub, Azure DevOps, GitLab, Bitbucket and Knowledge Fabric's review screen."),
    ("Tenant and configuration", "The tenant, its versioned configuration, usage, registry and settings."),
    ("Administration", "Identity providers, users, service tokens, sessions, repository access, keys and tenant lifecycle."),
    ("Audit", "The tamper-evident audit log."),
    ("Sign-in and session", "Browser sign-in (OIDC, SAML), the session and who am I."),
    ("Agents (MCP)", "The Model Context Protocol endpoint for coding assistants."),
    ("Health and metrics", "Liveness, readiness, health and Prometheus metrics."),
    ("Web interface", "The HTML pages: the single-page UI and the shareable report page."),
    ("Other", "Routes that fit no other group."),
]


def tag_of(path: str) -> str:
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return "Web interface"
    if parts[0] == "auth":
        return "Sign-in and session"
    if parts[0] in ("healthz", "readyz", "metrics"):
        return "Health and metrics"
    if parts[0] == "analyses":
        return "Web interface"
    if parts[0] == "query":
        return "Knowledge Fabric"
    if parts[0] == "mcp":
        return "Agents (MCP)"
    if parts[:2] == ["api", "v1"] and len(parts) > 2:
        seg = parts[2]
        if seg == "webhooks":
            return "Webhooks"
        if seg == "admin":
            return "Administration"
        if seg == "graph" and len(parts) > 3 and parts[3] in ("neo4j-sync", "ontology"):
            return "Code graph"
        return {"impact-analyses": "Impact analyses", "repositories": "Repositories", "uploads": "Uploads", "graph": "Code graph",
                "tenant": "Tenant and configuration", "jobs": "Jobs", "audit": "Audit", "evidence-snapshots": "Evidence",
                "me": "Sign-in and session", "health": "Health and metrics", "config": "Tenant and configuration", "evidence": "Evidence",
                "environments": "Releases and incidents", "releases": "Releases and incidents", "incidents": "Releases and incidents",
                "usage": "Tenant and configuration", "registry": "Tenant and configuration", "automation": "Tester views",
                "coverage": "Tester views", "flows": "Tester views", "scripts": "Tester views", "kf": "Knowledge Fabric",
                "tester-pack": "Tester views", "test-scope": "Tester views", "calibration": "Impact analyses",
                "trends": "Impact analyses"}.get(seg, "Other")
    return "Other"


# one-line summaries for handlers whose docstring is missing or does not start with what the route does (read from each handler's code)
SUMMARY = {
    "GET /": "The web interface (single-page HTML application)",
    "GET /api/v1/admin/github/installations": "List the GitHub App installations linked to this organisation",
    "DELETE /api/v1/admin/github/installations/{iid}": "Unlink a GitHub App installation",
    "GET /api/v1/admin/idps": "List the identity providers (OIDC, SAML)",
    "POST /api/v1/admin/idps": "Add an identity provider",
    "PUT /api/v1/admin/idps/{iid}": "Change an identity provider",
    "DELETE /api/v1/admin/idps/{iid}": "Remove an identity provider",
    "PUT /api/v1/admin/repo-access/{name}": "Set how one repository's access is governed and who is granted",
    "GET /api/v1/admin/sessions": "List browser sessions",
    "DELETE /api/v1/admin/sessions/{sid}": "Revoke a browser session",
    "GET /api/v1/admin/tokens": "List service-account tokens",
    "POST /api/v1/admin/tokens": "Create a service-account token (the secret is shown once)",
    "DELETE /api/v1/admin/tokens/{tid}": "Revoke a service-account token",
    "GET /api/v1/admin/users": "List users",
    "PUT /api/v1/admin/users/{uid}": "Change a user's roles or status",
    "GET /api/v1/audit": "Read the audit log",
    "GET /api/v1/audit/verify": "Verify the audit hash chain",
    "GET /api/v1/automation/ui": "UI automation inventory: every page, its elements and locators",
    "GET /api/v1/automation/api": "API automation inventory: every endpoint with its inputs and a test matrix",
    "GET /api/v1/config": "Server settings the web interface needs (auth mode, local paths, allowed git hosts)",
    "GET /api/v1/evidence": "List ingested evidence of one kind",
    "GET /api/v1/evidence-snapshots/{sid}": "An evidence snapshot: exactly what an analysis was computed from",
    "POST /api/v1/evidence/builds": "Ingest build records and their artifacts",
    "DELETE /api/v1/evidence/{rid}": "Delete one evidence record",
    "GET /api/v1/graph": "Code / dependency graph view for the UI (service, endpoint or function level)",
    "GET /api/v1/graph/stats": "Per repository: what was extracted and how it resolved",
    "GET /api/v1/graph/versions": "List stored graph versions",
    "GET /api/v1/graph/versions/{gid}": "One stored graph version",
    "GET /api/v1/health": "Simple health check: status and the number of registered repositories",
    "POST /api/v1/impact-analyses": "Run an impact analysis (synchronous, or queued with ?async=true)",
    "GET /api/v1/impact-analyses/{aid}": "The Change Impact Report of one analysis",
    "GET /api/v1/impact-analyses/{aid}/comment": "The pull-request comment of an analysis (Markdown)",
    "GET /api/v1/impact-analyses/{aid}/graph": "The analysis drawn on the code graph (impact overlay)",
    "GET /api/v1/impact-analyses/{aid}/paths": "The impact path of every finding",
    "POST /api/v1/impact-analyses/{aid}/publish": "Post or update the advisory comment and check run on a GitHub pull request",
    "GET /api/v1/impact-analyses/{aid}/unknowns": "What the analysis could not see (unknowns)",
    "GET /api/v1/jobs/{job_id}": "Status and result of a queued job",
    "DELETE /api/v1/jobs/{job_id}": "Cancel a queued or running job",
    "GET /api/v1/kf/reviews/{item_id}/history": "Every decision made on one review item",
    "GET /api/v1/me": "Who am I: the principal, its tenant, roles and permissions",
    "GET /api/v1/releases": "List releases",
    "GET /api/v1/repositories": "List registered repositories",
    "POST /api/v1/repositories": "Register a repository (git URL, or a local path in development mode)",
    "POST /api/v1/repositories/discover": "Discover (and optionally register) the repositories of an organisation or project",
    "DELETE /api/v1/repositories/{name}": "Remove a repository",
    "GET /api/v1/repositories/{name}/revisions": "Recent revisions of a repository",
    "POST /api/v1/repositories/{name}/sync": "Fetch the latest commits of a repository",
    "PUT /api/v1/repositories/{name}/upload": "Upload a zip as a repository in one call",
    "GET /api/v1/tenant/config/versions": "List configuration versions",
    "GET /api/v1/tenant/config/versions/{n}": "One configuration version",
    "POST /api/v1/uploads": "Start an upload session",
    "DELETE /api/v1/uploads/{uid}": "Cancel an upload session",
    "PUT /api/v1/uploads/{uid}/archive": "Send a zip archive to an upload session",
    "POST /api/v1/uploads/{uid}/commit": "Finish an upload: the files become a new revision of the repository",
    "POST /api/v1/uploads/{uid}/files": "Send a batch of folder files to an upload session",
    "GET /auth/callback": "OpenID Connect sign-in callback",
    "GET /auth/login": "Start browser sign-in (redirects to the identity provider)",
    "POST /auth/logout": "Sign out (revoke the session)",
    "POST /auth/saml/acs": "SAML assertion consumer service (the identity provider's POST)",
    "GET /auth/saml/metadata": "SAML service-provider metadata (XML)",
    "POST /mcp": "Model Context Protocol endpoint for coding assistants (read-only tools)",
    "GET /metrics": "Prometheus metrics",
}

# ---------------------------------------------------------------------------------------------------------------------- sanitising
SECRET_KEY = re.compile(r"(token|secret|password|passwd|private_key|client_secret|api_key|apikey|csrf|cookie|authorization|signature)", re.I)
SECRET_OK = re.compile(r"^(tokens?|token_id|token_count|tokens_total|has_secret|secret_set|secret_configured|csrf_required|.*_tokens|.*_count)$", re.I)
LOCAL_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/]+(?:[^\\/\s\"']+[\\/]+)*?(?:AppData|Temp|tmp|pytest-of-[^\\/\s\"']*)[\\/]+[^\s\"']*", re.I)
USERS_PATH = re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s\"']+(?:\\+[^\s\"']*)?", re.I)
TIA_TOKEN = re.compile(r"\btia_[0-9a-f-]{8,}_[A-Za-z0-9]+_[A-Za-z0-9_\-]{8,}\b")
JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*")


def clean_str(s: str) -> str:
    s = TIA_TOKEN.sub("tia_<tenant>_<id>_<secret>", s)
    s = JWT.sub("<jwt>", s)
    s = USERS_PATH.sub("/var/lib/tia/repos/<repo>", s)
    s = LOCAL_PATH.sub("/var/lib/tia/repos/<repo>", s)
    return s


def example_of(v, depth: int = 0, key: str = ""):
    """A real value made safe and short for an example: secrets and local paths replaced, lists cut to 3, strings to 400 chars."""
    if key and SECRET_KEY.search(key) and not SECRET_OK.match(key) and isinstance(v, str) and v:
        return "<redacted>"
    if depth > 14:
        return "..."
    if isinstance(v, dict):
        items = list(v.items())
        out = {str(k): example_of(x, depth + 1, str(k)) for k, x in items[:40]}
        if len(items) > 40:
            out["..."] = f"{len(items) - 40} more key(s)"
        return out
    if isinstance(v, list):
        return [example_of(x, depth + 1, key) for x in v[:3]]
    if isinstance(v, str):
        s = clean_str(v)
        return s if len(s) <= 400 else s[:400] + "..."
    return v


# ---------------------------------------------------------------------------------------------------------------------- schema inference
ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
ISO_D = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
# keys that are identifiers, not field names: TIA's own field names are snake_case, so kebab-case (service / repository names), paths,
# node ids, issue keys, hashes and numbers mean the object is a map
MAP_KEY = re.compile(r"[:/@{}\s.]|^\d|^[0-9a-f]{12,}$|^snap-|^g-|^tia-|^F\d+$|^[a-z0-9]+(?:-[a-z0-9]+)+$|^[A-Z][A-Z0-9]+-\d+$")
MAX_DEPTH = 16


def _tname(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _looks_like_map(objs: list) -> bool:
    keys = set()
    for o in objs:
        keys |= set(o)
    if not keys:
        return False
    odd = sum(1 for k in keys if MAP_KEY.search(k))
    if odd and odd >= len(keys) / 2:
        return True
    if len(keys) > 30:
        return True
    return False


def infer(values: list, depth: int = 0) -> dict:
    """A JSON Schema (OpenAPI 3.1) that every value in `values` satisfies."""
    if depth > MAX_DEPTH:
        return {"description": "nested deeper than this document details"}
    if not values:
        return {}
    by: dict = {}
    for v in values:
        by.setdefault(_tname(v), []).append(v)
    if "integer" in by and "number" in by:
        by["number"] += by.pop("integer")
    variants = []
    for t in ("object", "array", "string", "integer", "number", "boolean"):
        if t not in by:
            continue
        vs = by[t]
        if t == "object":
            if _looks_like_map(vs):
                inner = infer([x for o in vs for x in list(o.values())[:60]], depth + 1)
                sch = {"type": "object", "additionalProperties": inner or True,
                       "description": "map: keys are identifiers (node ids, repository or service names...)"}
            else:
                keys: dict = {}
                for o in vs:
                    for k, x in o.items():
                        keys.setdefault(k, []).append(x)
                props = {k: infer(xs, depth + 1) for k, xs in sorted(keys.items())}
                req = sorted(k for k in keys if all(k in o for o in vs))
                sch = {"type": "object", "properties": props}
                if req:
                    sch["required"] = req
        elif t == "array":
            items = [x for a in vs for x in a[:80]]
            sch = {"type": "array", "items": infer(items, depth + 1) if items else {}}
        elif t == "string":
            if all(ISO_DT.match(s) for s in vs):
                sch = {"type": "string", "format": "date-time"}
            elif all(ISO_D.match(s) for s in vs):
                sch = {"type": "string", "format": "date"}
            elif all(UUID.match(s) for s in vs):
                sch = {"type": "string", "format": "uuid"}
            else:
                sch = {"type": "string"}
        else:
            sch = {"type": t}
        variants.append(sch)
    nullable = "null" in by
    if not variants:
        return {"type": "null"}
    if len(variants) == 1:
        s = variants[0]
        if nullable:
            s = dict(s)
            s["type"] = [s["type"], "null"] if isinstance(s.get("type"), str) else s.get("type")
        return s
    out = {"anyOf": variants + ([{"type": "null"}] if nullable else [])}
    return out


# ---------------------------------------------------------------------------------------------------------------------- de-duplication
class Components:
    """Moves large, repeated response schemas into components/schemas so the document stays readable."""

    def __init__(self, schemas: dict):
        self.schemas = schemas
        self.by_hash: dict = {}
        self.uses: dict = {}

    @staticmethod
    def digest(s: dict) -> str:
        return hashlib.sha1(json.dumps(s, sort_keys=True).encode()).hexdigest()

    def register(self, name: str, schema: dict) -> dict:
        h = self.digest(schema)
        if h in self.by_hash:
            self.uses[self.by_hash[h]] += 1
            return {"$ref": f"#/components/schemas/{self.by_hash[h]}"}
        n, i = name, 2
        while n in self.schemas:
            n, i = f"{name}{i}", i + 1
        self.schemas[n] = schema
        self.by_hash[h] = n
        self.uses[n] = 1
        return {"$ref": f"#/components/schemas/{n}"}


def pascal(s: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^A-Za-z0-9]+", s) if p)


STATUS_TEXT = {"200": "OK", "201": "Created", "202": "Accepted", "204": "No content", "302": "Redirect", "303": "Redirect", "400": "Bad request",
               "402": "Plan limit reached (code plan_limit): the action would exceed the organisation's plan",
               "401": "Not signed in or invalid credential", "403": "Not permitted", "404": "Unknown, or not readable by the caller",
               "405": "Method not allowed", "409": "Conflict (stale version or state)", "410": "Tenant offboarded", "413": "Too large",
               "415": "Unsupported media type", "422": "Invalid request", "424": "Dependency problem (e.g. GitHub App installation)",
               "429": "Too many requests", "500": "Server error", "502": "Upstream error", "503": "A required service is not configured or unavailable"}

ERROR = {"type": "object", "description": "TIA's error body. `detail` is a message (or, for configuration validation, an object with `problems`); "
                                          "`code` is a stable machine-readable reason when the refusal comes from authentication, permissions or "
                                          "the tenant gate.",
         "properties": {"detail": {"anyOf": [{"type": "string"}, {"type": "object"}, {"type": "array"}]},
                        "code": {"type": "string", "enum": ["authentication_required", "invalid_token", "no_session", "session_expired", "session_revoked",
                                                           "forbidden", "csrf", "user_disabled", "no_role", "tenant_suspended", "tenant_offboarded",
                                                           "storage_quota_exceeded", "rate_limited", "auth_unavailable", "plan_limit"]}},
         "required": ["detail"]}


def response_name(op_id: str, status: str) -> str:
    return pascal(op_id) + ("Response" if status.startswith("2") else f"Error{status}")


# ---------------------------------------------------------------------------------------------------------------------- build
def build(recorded: dict) -> tuple[dict, dict]:
    app = build_app()
    hidden = []
    for r in app.routes:
        if getattr(r, "methods", None) and getattr(r, "include_in_schema", True) is False:
            r.include_in_schema = True
            hidden.extend(f"{m} {r.path}" for m in r.methods - {"HEAD", "OPTIONS"})
    app.openapi_schema = None
    oa = app.openapi()
    endpoints = {}
    for r in app.routes:
        if getattr(r, "methods", None):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                endpoints[(m, r.path)] = r

    routes = (recorded or {}).get("routes", {})
    comps = Components(oa.setdefault("components", {}).setdefault("schemas", {}))
    comps.schemas["Error"] = ERROR
    stats = {"operations": 0, "observed": 0, "typed_by_code": 0, "inferred": 0, "statuses_observed": 0, "hidden_added": len(hidden),
             "rows": []}

    for path, ops in sorted(oa["paths"].items()):
        for method, op in ops.items():
            M = method.upper()
            stats["operations"] += 1
            perm = rbac.classify(M, path)
            tag = tag_of(path)
            op["tags"] = [tag]
            ep = endpoints.get((M, path))
            doc = " ".join(((getattr(ep, "endpoint", None) and ep.endpoint.__doc__) or "").split())
            first = re.split(r"(?<=\.)\s", doc, maxsplit=1)[0].rstrip(".:;") if doc else ""
            first = (first[:100].rsplit(" ", 1)[0] + "...") if len(first) > 100 else first
            op["summary"] = SUMMARY.get(f"{M} {path}") or first or op.get("summary", f"{M} {path}")
            if doc and not op.get("description"):
                op["description"] = doc
            roles = sorted(rbac.PERMISSIONS.get(perm, ()), key=rbac.ROLES.index) if perm in rbac.PERMISSIONS else []
            who = ("**Public**: no credential." if perm == rbac.PUBLIC else "**Any signed-in principal.**" if perm == rbac.AUTHENTICATED
                   else f"**Needs permission `{perm}`**, held by: {', '.join(f'`{x}`' for x in roles)}." if perm else "**Not classified: refused to everyone.**")
            op["description"] = who + ("\n\n" + op["description"] if op.get("description") else "")
            op["x-tia-permission"] = perm
            if roles:
                op["x-tia-roles"] = roles
            if perm == rbac.PUBLIC:
                op["security"] = []
            if f"{M} {path}" in hidden:
                op["x-tia-hidden-in-app-schema"] = True

            rec = routes.get(f"{M} {path}")
            resp = op.setdefault("responses", {})
            row = {"op": f"{M} {path}", "tag": tag, "perm": perm, "calls": rec["calls"] if rec else 0, "statuses": []}
            if rec:
                stats["observed"] += 1
                op["x-tia-observed-calls"] = rec["calls"]
                # request body seen in tests
                bodies = [s["request"] for st in rec["statuses"].values() for s in st if isinstance(s.get("request"), (dict, list))
                          and not (isinstance(s["request"], dict) and (s["request"].get("__non_json__") or s["request"].get("__multipart__")))]
                multipart = any(isinstance(s.get("request"), dict) and s["request"].get("__multipart__") for st in rec["statuses"].values() for s in st)
                if bodies:
                    good = [s["request"] for code, st in rec["statuses"].items() if code.startswith("2") for s in st
                            if isinstance(s.get("request"), (dict, list))] or bodies
                    rb = op.get("requestBody")
                    if rb is None:
                        op["requestBody"] = {"required": False, "description": "JSON body (shape inferred from the requests the test suite sends; "
                                                                                 "the handler reads it directly).",
                                             "content": {"application/json": {"schema": infer(bodies), "example": example_of(good[0])}}}
                    else:
                        c = rb.setdefault("content", {}).setdefault("application/json", {})
                        c.setdefault("example", example_of(good[0]))
                elif multipart and op.get("requestBody") is None:
                    op["requestBody"] = {"content": {"multipart/form-data": {"schema": {"type": "object", "additionalProperties": True}}}}
                # query parameters seen but not declared (handlers that read request.query_params)
                declared = {p["name"] for p in op.get("parameters", [])}
                seenq = {}
                for st in rec["statuses"].values():
                    for s in st:
                        for k, v in (s.get("query") or {}).items():
                            seenq.setdefault(k, v)
                for k, v in sorted(seenq.items()):
                    if k not in declared:
                        op.setdefault("parameters", []).append({"name": k, "in": "query", "required": False, "schema": {"type": "string"},
                                                                 "example": clean_str(v)[:120], "x-tia-observed": True,
                                                                 "description": "read by the handler from the query string (seen in the test suite)"})
                # responses
                for code in sorted(rec["statuses"]):
                    samples = rec["statuses"][code]
                    row["statuses"].append(code)
                    stats["statuses_observed"] += 1
                    r = resp.setdefault(code, {"description": STATUS_TEXT.get(code, "Response")})
                    if r.get("description") in (None, "", "Successful Response"):
                        r["description"] = STATUS_TEXT.get(code, "Response")
                    js = [s for s in samples if "response" in s]
                    if js:
                        existing = (r.get("content") or {}).get("application/json", {}).get("schema")
                        typed = bool(existing) and existing != {} and ("$ref" in existing or "properties" in existing)
                        if typed:
                            stats["typed_by_code"] += 1
                            sch = existing
                        elif not code.startswith("2") and all(isinstance(s["response"], dict) and set(s["response"]) <= {"detail", "code"}
                                                               for s in js):
                            sch = {"$ref": "#/components/schemas/Error"}
                        else:
                            stats["inferred"] += 1
                            raw = infer([s["response"] for s in js])
                            sch = comps.register(response_name(op.get("operationId", f"{M}{path}"), code), raw) if len(json.dumps(raw)) > 400 else raw
                        ex = {f"observed_{i + 1}": {"summary": f"Observed in the test suite ({clean_str(s['path'])})",
                                                    "value": example_of(s["response"])}
                              for i, s in enumerate(js[:2])}
                        r["content"] = {"application/json": {"schema": sch, "examples": ex}}
                        if not typed:
                            r["x-tia-schema-source"] = "inferred from responses observed in the test suite"
                    else:
                        s = samples[0]
                        ct = s.get("content_type") or "text/plain"
                        if ct and s.get("size"):
                            r["content"] = {ct: {"schema": {"type": "string"}, **({"example": clean_str(s["response_text"])[:600]}
                                                                                    if s.get("response_text") and ct != "application/zip" else {})}}
                if "200" in resp and "200" not in rec["statuses"] and any(c.startswith("2") for c in rec["statuses"]):
                    if not (resp["200"].get("content", {}).get("application/json", {}).get("schema") or {}).get("$ref"):
                        resp.pop("200")                  # FastAPI's default 200 when the route really answers 201/202/204
            else:
                op["x-tia-observed-calls"] = 0
            # common answers every protected route may give
            if perm != rbac.PUBLIC:
                for code in ("401", "403", "429"):
                    resp.setdefault(code, {"description": STATUS_TEXT[code],
                                           "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}})
            if "{" in path:
                resp.setdefault("404", {"description": STATUS_TEXT["404"], "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}})
            stats["rows"].append(row)

    mcp_doc(oa)
    tags_used = {op["tags"][0] for ops in oa["paths"].values() for op in ops.values()}
    oa["tags"] = [{"name": n, "description": d} for n, d in TAGS if n in tags_used]
    oa["info"] = {"title": "TIA - Technical Impact Analysis API", "version": TIA_VERSION, "description": overview(stats)}
    oa["servers"] = [{"url": "http://127.0.0.1:8080", "description": "Local development server (python tools/run_dev.py --demo)"},
                     {"url": "https://tia.example.com", "description": "Your deployment (replace with its address)"}]
    oa["components"]["securitySchemes"] = {
        "bearer": {"type": "http", "scheme": "bearer",
                   "description": "A service-account token `tia_<tenant>_<id>_<secret>` (created by an administrator, shown once), or an OpenID "
                                  "Connect access token (JWT) from the tenant's identity provider."},
        "session": {"type": "apiKey", "in": "cookie", "name": "tia_session",
                    "description": "Browser session set by /auth/login (OIDC or SAML). State-changing calls must also send X-TIA-CSRF."},
        "csrf": {"type": "apiKey", "in": "header", "name": "X-TIA-CSRF", "description": "The `csrf` value from GET /auth/me (browser sessions only)."}}
    oa["security"] = [{"bearer": []}, {"session": [], "csrf": []}]
    oa["x-generated"] = {"by": "PTiia-swagger/tools/build_swagger.py", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "from": ["tia.api.create_app route table and schema", "tia.rbac route permissions",
                                  "responses recorded from the project's test suite (record_plugin.py)"]}
    return oa, stats


def mcp_doc(oa: dict) -> None:
    """POST /mcp is one JSON-RPC 2.0 endpoint: its methods and tools come from tia.mcp, so they are listed here from the code."""
    from tia import mcp
    op = (oa["paths"].get("/mcp") or {}).get("post")
    if not op:
        return
    rows = "\n".join(f"| `{t['name']}` | {t.get('title', '')} | {', '.join(f'`{k}`' for k in t['inputSchema'].get('properties', {})) or '-'} |"
                     for t in mcp.TOOLS)
    op["description"] += (f"\n\nModel Context Protocol `{mcp.PROTOCOL}` over JSON-RPC 2.0 (streamable HTTP, single JSON responses). Methods: "
                          "`initialize`, `tools/list`, `tools/call`, `ping`. Every tool is **read-only**; there is no write tool.\n\n"
                          "| Tool | What it answers | Arguments |\n|---|---|---|\n" + rows +
                          f"\n\nServer instructions given to the assistant: _{mcp.INSTRUCTIONS}_")
    rpc = {"type": "object", "required": ["jsonrpc", "method"],
           "properties": {"jsonrpc": {"const": "2.0"}, "id": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                          "method": {"type": "string", "enum": ["initialize", "notifications/initialized", "tools/list", "tools/call", "ping"]},
                          "params": {"type": "object", "description": "for tools/call: {name: <tool>, arguments: {...}}",
                                     "properties": {"name": {"type": "string", "enum": [t["name"] for t in mcp.TOOLS]}, "arguments": {"type": "object"}}}}}
    body = op.setdefault("requestBody", {"required": True, "content": {"application/json": {}}})
    c = body.setdefault("content", {}).setdefault("application/json", {})
    c["schema"] = rpc
    c.pop("example", None)
    c["examples"] = {"tools_list": {"value": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}},
                     "get_test_scope": {"value": {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                  "params": {"name": "get_test_scope", "arguments": {"analysis_id": "tia-pr-42-9f3c2ab"}}}}}
    oa["components"]["schemas"]["McpTools"] = {"description": "The tools POST /mcp offers (tools/list answers these)",
                                               "type": "array", "items": {"type": "object"}, "example": mcp.TOOLS}


def overview(st: dict) -> str:
    perms = "\n".join(f"| `{p}` | {', '.join(f'`{r}`' for r in sorted(rs, key=rbac.ROLES.index))} |" for p, rs in rbac.PERMISSIONS.items())
    return f"""TIA (Technical Impact Analysis) tells testers and reviewers what a code change affects and which tests to run again.
This document describes **every route** of the TIA server ({st['operations']} operations), generated from the code.

## Authentication
With `TIA_AUTH_REQUIRED=true` every route except the **public** ones needs one of:

| Credential | How it is sent | For |
|---|---|---|
| Service-account token | `Authorization: Bearer tia_<tenant>_<id>_<secret>` | CI jobs, scripts, agents |
| OpenID Connect token | `Authorization: Bearer <JWT>` | programs acting for a signed-in person |
| Browser session | `tia_session` cookie from `/auth/login` + `X-TIA-CSRF` header on changes | the web UI |

The credential names the **tenant**: every request sees that tenant's data only. A repository the caller may not read answers `404`.
Without `TIA_AUTH_REQUIRED` (development) everyone is an administrator of one tenant, and the server also serves its own `/docs`.

## Roles and permissions
Each operation states the permission it needs (`x-tia-permission`) and the roles that hold it (`x-tia-roles`). Routes not in the table are refused.

| Permission | Roles |
|---|---|
{perms}

## Errors
Errors are JSON `{{"detail": ..., "code": ...}}` (schema `Error`): `401` no or invalid credential, `403` not permitted, `404` unknown or not readable,
`409` stale version, `410` tenant offboarded, `422` invalid body (FastAPI's `HTTPValidationError`, or `{{"detail": {{"message", "problems"}}}}` for
configuration), `424` GitHub App installation problem, `429` rate limited (with `Retry-After`), `503` a required service is not configured.
Every response carries `X-Request-ID` and `X-Trace-Id`.

## How this document was made
* Routes, parameters and the request models come from the application itself (`tia.api.create_app`), including the
  {st['hidden_added']} routes the server hides from its own schema (`x-tia-hidden-in-app-schema`).
* Response formats come from **real responses**: the project's test suite was run with a recorder, and each route's response schema was
  inferred from what it actually answered (`x-tia-schema-source`), with real examples (secrets and local paths removed, lists cut to 3).
  {st['observed']} of {st['operations']} operations were exercised (`x-tia-observed-calls`); see COVERAGE.md for the rest.
* An inferred schema lists the fields seen in tests: a field marked required appeared in every observed answer. Fields that appear only in
  situations the tests did not reach are not listed.
"""


def coverage_md(st: dict, recorded: dict) -> str:
    rows = sorted(st["rows"], key=lambda r: (r["tag"], r["op"].split(" ", 1)[1], r["op"]))
    lines = [f"# API coverage of this Swagger document\n",
             f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `tools/build_swagger.py`.\n",
             f"* Operations documented: **{st['operations']}** (every route of the server, {st['hidden_added']} of them hidden from the app's own schema)",
             f"* Operations whose responses were observed in the test suite: **{st['observed']}**",
             f"* Response statuses with a documented body: **{st['statuses_observed']}** ({st['inferred']} schemas inferred from real responses, "
             f"{st['typed_by_code']} typed by the code's own models)",
             f"* Test-suite exit status during recording: {recorded.get('exit_status')} (0 = every test passed)\n",
             "Operations with **0** calls are documented from the code only (path, parameters, request model, permission); their response "
             "format is not shown because no test calls them.\n",
             "| Group | Operation | Permission | Calls in tests | Statuses seen |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['tag']} | `{r['op']}` | `{r['perm']}` | {r['calls']} | {', '.join(r['statuses']) or '-'} |")
    return "\n".join(lines) + "\n"


def to_yaml(oa: dict) -> str:
    import yaml

    class D(yaml.SafeDumper):
        pass
    D.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))
    return yaml.dump(oa, Dumper=D, sort_keys=False, allow_unicode=True, width=140)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recorded", help="recorded.json from record_plugin.py (without it, only the code-derived parts are built)")
    a = ap.parse_args(argv)
    recorded = json.loads(Path(a.recorded).read_text(encoding="utf-8")) if a.recorded else {}
    oa, st = build(recorded)
    text = json.dumps(oa, indent=1, ensure_ascii=False)
    (OUT / "openapi.json").write_text(text + "\n", encoding="utf-8", newline="\n")
    (OUT / "openapi.yaml").write_text(to_yaml(oa), encoding="utf-8", newline="\n")
    (OUT / "spec.js").write_text("/* generated by tools/build_swagger.py: the OpenAPI document for index.html (works from file://) */\n"
                                 "window.TIA_OPENAPI = " + text + ";\n", encoding="utf-8", newline="\n")
    (OUT / "COVERAGE.md").write_text(coverage_md(st, recorded), encoding="utf-8", newline="\n")
    print(f"operations {st['operations']}, observed {st['observed']}, statuses {st['statuses_observed']}, inferred {st['inferred']}, "
          f"components {len(oa['components']['schemas'])}, size {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
