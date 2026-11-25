# API coverage of this Swagger document

Generated 2026-11-25 12:39 UTC by `tools/build_swagger.py`.

* Operations documented: **143** (every route of the server, 11 of them hidden from the app's own schema)
* Operations whose responses were observed in the test suite: **138**
* Response statuses with a documented body: **327** (128 schemas inferred from real responses, 17 typed by the code's own models)
* Test-suite exit status during recording: 0 (0 = every test passed)

Operations with **0** calls are documented from the code only (path, parameters, request model, permission); their response format is not shown because no test calls them.

| Group | Operation | Permission | Calls in tests | Statuses seen |
|---|---|---|---|---|
| Administration | `GET /api/v1/admin/github/installations` | `admin` | 4 | 200, 403 |
| Administration | `POST /api/v1/admin/github/installations` | `admin` | 10 | 200, 403, 409, 422, 424, 503 |
| Administration | `DELETE /api/v1/admin/github/installations/{iid}` | `admin` | 3 | 200, 404 |
| Administration | `GET /api/v1/admin/idps` | `admin` | 3 | 200, 403 |
| Administration | `POST /api/v1/admin/idps` | `admin` | 5 | 200, 400, 422 |
| Administration | `DELETE /api/v1/admin/idps/{iid}` | `admin` | 2 | 200, 404 |
| Administration | `PUT /api/v1/admin/idps/{iid}` | `admin` | 2 | 200, 404 |
| Administration | `GET /api/v1/admin/repo-access` | `admin` | 5 | 200, 403 |
| Administration | `POST /api/v1/admin/repo-access/sync` | `access_sync` | 34 | 200, 403, 503 |
| Administration | `PUT /api/v1/admin/repo-access/{name}` | `admin` | 12 | 200, 403, 404, 422 |
| Administration | `GET /api/v1/admin/sessions` | `admin` | 2 | 200, 403 |
| Administration | `DELETE /api/v1/admin/sessions/{sid}` | `admin` | 1 | 200 |
| Administration | `GET /api/v1/admin/tokens` | `admin` | 10 | 200, 401, 403 |
| Administration | `POST /api/v1/admin/tokens` | `admin` | 5 | 201, 403, 422 |
| Administration | `DELETE /api/v1/admin/tokens/{tid}` | `admin` | 2 | 200, 404 |
| Administration | `GET /api/v1/admin/users` | `admin` | 2 | 200, 403 |
| Administration | `PUT /api/v1/admin/users/{uid}` | `admin` | 4 | 200, 404, 422 |
| Agents (MCP) | `POST /mcp` | `read` | 26 | 200, 202, 400 |
| Audit | `GET /api/v1/audit` | `audit_read` | 44 | 200, 401, 403 |
| Audit | `GET /api/v1/audit/report` | `audit_read` | 1 | 200 |
| Audit | `GET /api/v1/audit/verify` | `audit_read` | 20 | 200, 403 |
| Code graph | `GET /api/v1/graph` | `read` | 27 | 200, 400, 401, 404 |
| Code graph | `GET /api/v1/graph/flows` | `read` | 2 | 200 |
| Code graph | `POST /api/v1/graph/kf-links` | `repo_write` | 2 | 422 |
| Code graph | `POST /api/v1/graph/neo4j-sync` | `repo_write` | 2 | 409, 503 |
| Code graph | `GET /api/v1/graph/ontology` | `read` | 3 | 200 |
| Code graph | `GET /api/v1/graph/query` | `read` | 24 | 200, 400 |
| Code graph | `POST /api/v1/graph/registry-match` | `read` | 3 | 200, 422 |
| Code graph | `GET /api/v1/graph/relationships` | `read` | 18 | 200, 400 |
| Code graph | `POST /api/v1/graph/rescan` | `repo_write` | 11 | 200, 403 |
| Code graph | `GET /api/v1/graph/shared-components` | `read` | 6 | 200 |
| Code graph | `GET /api/v1/graph/stats` | `read` | 2 | 200 |
| Code graph | `GET /api/v1/graph/versions` | `read` | 13 | 200 |
| Code graph | `GET /api/v1/graph/versions/{gid}` | `read` | 5 | 200, 404 |
| Evidence | `GET /api/v1/evidence` | `read` | 4 | 200, 400 |
| Evidence | `GET /api/v1/evidence-snapshots/{sid}` | `read` | 7 | 200, 404 |
| Evidence | `POST /api/v1/evidence/builds` | `evidence_write` | 1 | 200 |
| Evidence | `POST /api/v1/evidence/coverage` | `evidence_write` | 1 | 200 |
| Evidence | `POST /api/v1/evidence/deployments` | `evidence_write` | 9 | 200, 402, 404 |
| Evidence | `POST /api/v1/evidence/runtime` | `evidence_write` | 5 | 200 |
| Evidence | `POST /api/v1/evidence/test-results` | `evidence_write` | 9 | 200, 400, 404 |
| Evidence | `DELETE /api/v1/evidence/{rid}` | `evidence_write` | 2 | 200, 404 |
| Health and metrics | `GET /api/v1/health` | `public` | 23 | 200 |
| Health and metrics | `GET /healthz` | `public` | 25 | 200 |
| Health and metrics | `GET /metrics` | `public` | 15 | 200, 403 |
| Health and metrics | `GET /readyz` | `public` | 6 | 200 |
| Impact analyses | `GET /api/v1/calibration` | `read` | 2 | 200 |
| Impact analyses | `POST /api/v1/impact-analyses` | `analyze` | 202 | 200, 202, 400, 401, 402, 403, 404 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}` | `read` | 69 | 200, 404 |
| Impact analyses | `POST /api/v1/impact-analyses/{aid}/acknowledgements` | `evidence_write` | 4 | 200, 400 |
| Impact analyses | `POST /api/v1/impact-analyses/{aid}/approvals` | `analyze` | 4 | 200, 400 |
| Impact analyses | `POST /api/v1/impact-analyses/{aid}/change-record` | `analyze` | 2 | 200, 400 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/comment` | `read` | 10 | 200, 404 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/coordination` | `read` | 2 | 200 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/evidence` | `read` | 8 | 200, 404 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/findings` | `read` | 6 | 200, 400, 404 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/graph` | `read` | 7 | 200, 404 |
| Impact analyses | `POST /api/v1/impact-analyses/{aid}/notifications` | `evidence_write` | 6 | 200 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/paths` | `read` | 2 | 200, 404 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/policy` | `read` | 3 | 200 |
| Impact analyses | `POST /api/v1/impact-analyses/{aid}/publish` | `analyze` | 25 | 200, 400, 404, 422, 502, 503 |
| Impact analyses | `POST /api/v1/impact-analyses/{aid}/reproduce` | `analyze` | 16 | 200, 400, 404 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/tester-pack` | `read` | 8 | 200, 404 |
| Impact analyses | `GET /api/v1/impact-analyses/{aid}/unknowns` | `read` | 4 | 200, 404 |
| Impact analyses | `POST /api/v1/impact-analyses/{aid}/verdicts` | `evidence_write` | 6 | 200, 404, 422 |
| Impact analyses | `GET /api/v1/trends` | `read` | 4 | 200, 400 |
| Jobs | `DELETE /api/v1/jobs/{job_id}` | `analyze` | 3 | 404, 409 |
| Jobs | `GET /api/v1/jobs/{job_id}` | `read` | 30 | 200, 404 |
| Knowledge Fabric | `GET /api/v1/kf/catalog` | `read` | 2 | 200, 404 |
| Knowledge Fabric | `GET /api/v1/kf/customers` | `config_write` | 0 | - |
| Knowledge Fabric | `GET /api/v1/kf/decisions` | `read` | 4 | 200, 400 |
| Knowledge Fabric | `GET /api/v1/kf/gaps` | `read` | 4 | 200, 403 |
| Knowledge Fabric | `DELETE /api/v1/kf/links` | `config_write` | 2 | 403, 503 |
| Knowledge Fabric | `GET /api/v1/kf/links` | `read` | 0 | - |
| Knowledge Fabric | `GET /api/v1/kf/node` | `read` | 4 | 200, 404 |
| Knowledge Fabric | `GET /api/v1/kf/overlay` | `read` | 4 | 200, 404 |
| Knowledge Fabric | `GET /api/v1/kf/products` | `read` | 1 | 200 |
| Knowledge Fabric | `PUT /api/v1/kf/products/{repository}` | `config_write` | 8 | 200, 403, 404, 409, 422 |
| Knowledge Fabric | `POST /api/v1/kf/relink` | `repo_write` | 0 | - |
| Knowledge Fabric | `GET /api/v1/kf/review-measures` | `read` | 3 | 200 |
| Knowledge Fabric | `GET /api/v1/kf/reviews` | `read` | 5 | 200, 400 |
| Knowledge Fabric | `POST /api/v1/kf/reviews/decisions` | `kf_review` | 1 | 200 |
| Knowledge Fabric | `GET /api/v1/kf/reviews/{item_id}` | `read` | 2 | 200, 404 |
| Knowledge Fabric | `POST /api/v1/kf/reviews/{item_id}/decision` | `kf_review` | 15 | 200, 400, 403, 409, 422 |
| Knowledge Fabric | `GET /api/v1/kf/reviews/{item_id}/history` | `read` | 1 | 200 |
| Knowledge Fabric | `GET /api/v1/kf/rule-proposals` | `read` | 0 | - |
| Knowledge Fabric | `POST /api/v1/kf/rule-proposals/{proposal_id}` | `repo_write` | 0 | - |
| Knowledge Fabric | `PATCH /api/v1/kf/settings` | `config_write` | 12 | 200, 403, 409, 422 |
| Knowledge Fabric | `GET /api/v1/kf/status` | `read` | 10 | 200 |
| Knowledge Fabric | `POST /query/tia` | `read` | 22 | 200, 401, 422 |
| Knowledge Fabric | `POST /query/tia/resolve` | `read` | 4 | 200, 422 |
| Releases and incidents | `GET /api/v1/environments` | `read` | 2 | 200 |
| Releases and incidents | `GET /api/v1/environments/at` | `read` | 5 | 200, 400 |
| Releases and incidents | `POST /api/v1/incidents` | `evidence_write` | 9 | 200, 400 |
| Releases and incidents | `GET /api/v1/incidents/{iid}/investigation` | `read` | 6 | 200 |
| Releases and incidents | `POST /api/v1/incidents/{iid}/links` | `evidence_write` | 3 | 200, 400, 404 |
| Releases and incidents | `GET /api/v1/releases` | `read` | 3 | 200 |
| Releases and incidents | `POST /api/v1/releases` | `evidence_write` | 15 | 200, 400, 404, 409 |
| Releases and incidents | `GET /api/v1/releases/compare` | `read` | 4 | 200 |
| Releases and incidents | `GET /api/v1/releases/{name}/consumers` | `read` | 6 | 200, 404 |
| Repositories | `GET /api/v1/repositories` | `read` | 751 | 200, 401, 403, 410, 421, 429 |
| Repositories | `POST /api/v1/repositories` | `repo_write` | 1072 | 200, 400, 402, 403, 421 |
| Repositories | `POST /api/v1/repositories/discover` | `repo_write` | 4 | 200, 424, 503 |
| Repositories | `DELETE /api/v1/repositories/{name}` | `repo_delete` | 20 | 200, 400, 401, 403, 404 |
| Repositories | `GET /api/v1/repositories/{name}/revisions` | `read` | 8 | 200, 404 |
| Repositories | `POST /api/v1/repositories/{name}/sync` | `repo_write` | 18 | 200, 400, 403, 404, 424 |
| Repositories | `PUT /api/v1/repositories/{name}/upload` | `repo_write` | 28 | 200, 400, 403, 404 |
| Sign-in and session | `GET /api/v1/me` | `authenticated` | 31 | 200, 401, 403, 502 |
| Sign-in and session | `GET /auth/callback` | `public` | 31 | 302, 400, 401, 403 |
| Sign-in and session | `GET /auth/login` | `public` | 73 | 302, 404, 502, 503 |
| Sign-in and session | `POST /auth/logout` | `authenticated` | 1 | 200 |
| Sign-in and session | `GET /auth/me` | `public` | 20 | 200 |
| Sign-in and session | `GET /auth/options` | `public` | 4 | 200 |
| Sign-in and session | `POST /auth/saml/acs` | `public` | 44 | 302, 400, 401, 403, 413 |
| Sign-in and session | `GET /auth/saml/metadata` | `public` | 1 | 200 |
| Tenant and configuration | `GET /api/v1/config` | `public` | 1 | 200 |
| Tenant and configuration | `POST /api/v1/registry/import` | `config_write` | 3 | 200, 400 |
| Tenant and configuration | `GET /api/v1/tenant` | `read` | 13 | 200, 403 |
| Tenant and configuration | `GET /api/v1/tenant/config` | `read` | 15 | 200, 403 |
| Tenant and configuration | `PUT /api/v1/tenant/config` | `config_write` | 50 | 200, 401, 403, 422 |
| Tenant and configuration | `GET /api/v1/tenant/config/diff` | `read` | 3 | 200, 404 |
| Tenant and configuration | `POST /api/v1/tenant/config/validate` | `read` | 3 | 200 |
| Tenant and configuration | `GET /api/v1/tenant/config/versions` | `read` | 1 | 200 |
| Tenant and configuration | `GET /api/v1/tenant/config/versions/{n}` | `read` | 5 | 200, 404 |
| Tenant and configuration | `POST /api/v1/tenant/config/versions/{n}/restore` | `config_write` | 3 | 200, 404 |
| Tenant and configuration | `GET /api/v1/usage` | `admin` | 2 | 200, 400 |
| Tester views | `GET /api/v1/automation/api` | `read` | 4 | 200 |
| Tester views | `POST /api/v1/automation/script` | `read` | 2 | 200 |
| Tester views | `GET /api/v1/automation/ui` | `read` | 5 | 200 |
| Tester views | `GET /api/v1/coverage` | `read` | 8 | 200, 404 |
| Tester views | `POST /api/v1/coverage/test-case` | `read` | 8 | 200, 422 |
| Uploads | `POST /api/v1/uploads` | `repo_write` | 47 | 200, 400, 403, 404 |
| Uploads | `DELETE /api/v1/uploads/{uid}` | `repo_write` | 2 | 200, 404 |
| Uploads | `PUT /api/v1/uploads/{uid}/archive` | `repo_write` | 39 | 200, 400, 403, 404, 413 |
| Uploads | `POST /api/v1/uploads/{uid}/commit` | `repo_write` | 34 | 200, 400, 404 |
| Uploads | `POST /api/v1/uploads/{uid}/files` | `repo_write` | 7 | 200, 413 |
| Web interface | `GET /` | `public` | 6 | 200 |
| Web interface | `GET /analyses/{aid}` | `read` | 20 | 200, 302, 401, 403, 404, 410 |
| Webhooks | `POST /api/v1/webhooks/ado` | `public` | 16 | 202, 400, 401, 503 |
| Webhooks | `POST /api/v1/webhooks/bitbucket` | `public` | 4 | 202, 401 |
| Webhooks | `POST /api/v1/webhooks/github` | `public` | 44 | 200, 202, 400, 401, 403, 413, 503 |
| Webhooks | `POST /api/v1/webhooks/gitlab` | `public` | 5 | 202, 401 |
| Webhooks | `POST /api/v1/webhooks/kf-review` | `public` | 7 | 200, 400, 401, 404, 409, 503 |
