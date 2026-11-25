# PTiia-swagger — the complete Swagger (OpenAPI) document of the TIA API

Everything a client needs to call TIA's HTTP API: every route, its parameters, request body, **response format with real examples**,
the permission it needs, the roles that hold it, and the errors it can answer.

| File | What it is |
|---|---|
| [`index.html`](index.html) | Swagger UI. Open it in a browser (double-click works: the document is embedded through `spec.js`). |
| [`openapi.json`](openapi.json) | The OpenAPI 3.1 document. Import it into Postman, Insomnia, Stoplight, a code generator, etc. |
| [`openapi.yaml`](openapi.yaml) | The same document in YAML. |
| [`spec.js`](spec.js) | The same document wrapped for `index.html`, so the page works from `file://` without a web server. |
| [`COVERAGE.md`](COVERAGE.md) | Every operation, its permission, how often the test suite called it and which statuses were seen. |
| [`tools/record_plugin.py`](tools/record_plugin.py) | pytest plugin that records the real HTTP exchanges of the test suite. |
| [`tools/build_swagger.py`](tools/build_swagger.py) | Builds the documents from the code and the recording. |

## At a glance

| | |
|---|---|
| Operations documented | **143**: every route of the server |
| Operations with observed responses | **138** (the 5 others are Knowledge Fabric routes no test calls; see `COVERAGE.md`) |
| Response statuses with a schema and real example | **327** |
| Standard | OpenAPI **3.1.0**, checked with `openapi-spec-validator` 0.7.1: valid |
| Recorded from | the full test suite: 1,454 passed, 29 skipped, on an embedded PostgreSQL (25 Nov 2026) |

## What is in the document

* **All routes of the server**, grouped by tags (Impact analyses, Tester views, Code graph, Repositories, Uploads, Evidence, Releases
  and incidents, Knowledge Fabric, Jobs, Webhooks, Tenant and configuration, Administration, Audit, Sign-in and session, Agents (MCP),
  Health and metrics, Web interface). This includes the routes the server hides from its own built-in `/docs` (sign-in flow, web pages,
  health, metrics), marked `x-tia-hidden-in-app-schema`.
* **Security:** the three ways to authenticate (`bearer` service token or OIDC JWT, `session` cookie + `csrf` header). Each operation
  carries `x-tia-permission` and `x-tia-roles` from `tia/rbac.py`, and public routes have `security: []`.
* **Request bodies:** the Pydantic models the code declares; for handlers that read the body themselves, a schema inferred from the
  bodies the tests send, with an example.
* **Responses:** for each status the tests observed, a JSON schema **inferred from the real responses** (`x-tia-schema-source`) and up to two
  real examples. Large shared shapes (the impact report and others) are in `components/schemas`. The common errors (`401`, `403`, `404`,
  `429`) use the `Error` schema `{detail, code}`.
* **MCP:** `POST /mcp` lists its JSON-RPC methods and every tool with its arguments, taken from `tia/mcp.py`.

## How it was made (and how far to trust it)

1. The FastAPI application is built exactly as the server builds it (`tia.api.create_app`), and its own OpenAPI schema is taken as the base:
   paths, path and query parameters, request models.
2. The project's whole test suite (`development/tests`, a real embedded PostgreSQL) was run with `record_plugin.py`, which records every
   request and response made through the test client. No project file is changed.
3. `build_swagger.py` merges the two. Examples have secrets, tokens and local file paths replaced, and long lists cut to three items.

Limits, stated plainly:
* A response schema lists **the fields the tests saw**. A field marked `required` was present in every observed answer of that status.
  A field that only appears in situations no test reaches is not listed.
* Operations that no test calls are documented from the code only (path, parameters, request model, permission), without a response body.
  `COVERAGE.md` lists them (calls = 0).
* Values in examples come from the test fixtures (demo services such as `payments-service`), not from a customer.

## Rebuild after the API changes

From `Project TIA/development`, with the project's virtual environment active:

```bash
PYTHONPATH=../PTiia-swagger/tools SWAGGER_RECORD_OUT=../PTiia-swagger/tools/recorded.json \
    python -m pytest -q -p record_plugin tests            # records the exchanges (the full suite takes a while)
python ../PTiia-swagger/tools/build_swagger.py --recorded ../PTiia-swagger/tools/recorded.json
```

Without `--recorded` the builder still writes every route from the code, only without the observed response formats.

## Use it

* **Read:** open `index.html`. Use the filter box to find a route by tag.
* **Try calls:** start TIA locally (`python tools/run_dev.py --demo` in `development/`, on `http://127.0.0.1:8080`). In development mode
  (`TIA_AUTH_REQUIRED` not set) the server also serves FastAPI's own `/docs`, `/redoc` and `/openapi.json`; with authentication required
  they are switched off. This document is the complete, annotated version of that built-in schema.
* **Generate a client:** for example `openapi-generator-cli generate -i openapi.json -g python -o tia-client`. The project also ships a
  hand-written Python SDK in `development/sdk/python`.
