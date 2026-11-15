# Neo4j mirror of the TIA graph

Written for whoever runs TIA next to Knowledge Fabric 2.5, and for KF developers who query TIA's graph with Cypher.

## What it is

TIA's graph is built, stored and walked in **PostgreSQL**, which stays the system of record (see [GRAPH-STORE.md](GRAPH-STORE.md) for
why). The **Neo4j mirror** copies the current graph version of each tenant into a Neo4j database, so that:
- KF agents can walk from a change to the entry points and written test cases it reaches, in Cypher;
- TIA nodes can be linked to the KF ontology (domain, product line, function, sub-function, requirement, process, rule).

It is what Pawan asked for as "step 0" (see [MEETING-PAWAN.md](MEETING-PAWAN.md)). The code is [tia/neo4jgraph.py](../tia/neo4jgraph.py).

## Setting it up

1. Install the driver: `pip install 'tia[neo4j]'`. The container image already includes it.
2. Point TIA at the database:

   | Variable | Meaning |
   |---|---|
   | `NEO4J_URI` | for example `bolt://kf-neo4j.internal:7687` |
   | `NEO4J_USER` | default `neo4j` |
   | `NEO4J_PASSWORD` | required: there is no default password |
   | `NEO4J_DATABASE` | optional; the server's default database otherwise |
   | `TIA_NEO4J_AUTO_SYNC` | `true` to mirror automatically every time the landscape graph advances to a new version |

   Air-gapped installations must list the Neo4j host in `TIA_AIRGAP_ALLOWED_HOSTS`.
3. Mirror the graph, in one of three ways:
   - **Automatic:** set `TIA_NEO4J_AUTO_SYNC=true`. A failed sync is written to the audit log (`neo4j_sync_failed`) and never fails the request that advanced the graph.
   - **API:** `POST /api/v1/graph/neo4j-sync`. It needs `repo_write`, and a caller who may read every repository of the tenant. Its result gives the node, relationship and test-case counts.
   - **Command line:** `tia neo4j-sync --repo NAME=PATH ... [--tenant-id ID]`.

For a local Neo4j on a developer machine:

```
docker run -d --name tia-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/<choose-a-password> neo4j:5.26.4-community
```

## What is written

| In Neo4j | From TIA |
|---|---|
| `(:TiaNode:Tia<Type>)` | Every graph node, with its TIA type as a label: `TiaService`, `TiaEndpoint`, `TiaFunction`, `TiaCallsite`, `TiaSchema`, `TiaTest`, `TiaTable`, `TiaTopic`, and so on. Properties: `key` (`<tenant>\|<id>`, unique), `id`, `tenant`, `graph_version`, `type`, `name`, `repo`, `service`, `file`, `line`; endpoints also have `method`, `route` and `path`. |
| `-[:CALLS]->`, `-[:HANDLES]->`, `-[:CONSUMES_API]->`, `-[:TESTS]->`, `-[:READS]->`, ... | Every TIA edge, with TIA's own name and direction (consumer to provider). Properties: `status` (the evidence status, never upgraded), `strategy`, `rule`, `file`, `line`, `tia: true`. |
| `-[:IMPACTS {via}]->` | The same edges in the direction a change travels, which is what TIA's impact walk follows. "What does a change to X reach" becomes one pattern. |
| `(:TiaNode:TiaTestCase)-[:COVERS]->(:TiaEndpoint)` | The written test cases (`testcases/*.csv\|yaml\|json`) and the endpoints they test: named in the case, or called by the screen it names (`via_page`). `status` is `source_confirmed` when the case's *Entry point* column names it, `inferred` when it is matched from the text. |
| `(:TiaGraphVersion)` | One per tenant: the graph version mirrored, when, and the counts. |

The `Tia` prefix keeps these nodes apart from the KF ontology's own labels. KF has a business *Function*, which is not a code function.

Each sync updates the nodes and relationships it writes, then deletes that tenant's TIA nodes and relationships from other graph versions.
Neo4j therefore always holds the **current** landscape, while PostgreSQL keeps every version. Nothing outside the `Tia*` labels and
`tia: true` relationships is touched.

## Use case 1 in Cypher: which test cases a change reaches

```cypher
MATCH (c:TiaNode {tenant: $tenant}) WHERE c.id IN $changed          // e.g. ['payments-app:app.py::balance_of']
MATCH p = (c)-[:IMPACTS*0..8]->(e:TiaEndpoint)
WHERE all(n IN nodes(p) WHERE NOT n:TiaTest)
WITH DISTINCT e, min(length(p)) AS hops
MATCH (tc:TiaTestCase {tenant: $tenant})-[cov:COVERS]->(e)
RETURN tc.case_id, tc.title, e.method + ' ' + coalesce(e.route, e.path) AS entry_point, hops, cov.status, cov.via_page
```

`tia.neo4jgraph.regression_tests(driver, tenant, changed)` runs this query. On the regression demo it returns exactly the test cases TIA's
own engine selects, for all three feature branches (`tests/test_neo4jgraph.py`). For `balance_of` that is TC-01, TC-02, TC-03 (through the
Pay screen) and TC-07.

## Automation and API testing in Cypher

The screens, elements, locators, requests, responses, fields and business rules of [GRAPH-SCHEMA.md](GRAPH-SCHEMA.md) are mirrored too.

**Elements of a screen, with the locator to use and the API the screen calls:**

```cypher
MATCH (:TiaApplication {tenant: $tenant})-[:HAS_SCREEN]->(sc:TiaScreen {route: '/pay'})-[:HAS_ELEMENT]->(el:TiaElement)
MATCH (el)-[:LOCATED_BY]->(l:TiaLocator {best: true})
OPTIONAL MATCH (sc)-[:CALLS_API]->(ep:TiaEndpoint)
RETURN el.name, el.mandatory, el.options, l.css, l.xpath, l.playwright, ep.method + ' ' + ep.route AS calls
```

**What a request needs, and what the response can be:**

```cypher
MATCH (ep:TiaEndpoint {tenant: $tenant, method: 'POST', route: '/payments'})-[:ACCEPTS]->(:TiaRequest)-[:HAS_FIELD]->(f:TiaField)
RETURN f.name, f.in, f.field_type, f.required, f.allowed_values, f.min_length, f.max_length, f.minimum, f.maximum, f.pattern

MATCH (:TiaEndpoint {tenant: $tenant, method: 'POST', route: '/payments'})-[:RETURNS]->(r:TiaResponse)
RETURN r.success_status, r.error_statuses, r.schema
```

**Business rules and where they apply:**

```cypher
MATCH (f:TiaFunction {tenant: $tenant})-[:APPLIES_RULE]->(r:TiaRule) RETURN f.name, r.expr, r.fields, r.file, r.line
```

`tests/test_neo4jgraph.py` runs these queries against a real Neo4j.

## Linking to the Knowledge Fabric ontology

Links are created **only from an explicit mapping**; TIA does not guess KF's schema. The mapping is a CSV with two columns:
- `tia`: an endpoint as `METHOD /route`, a business rule by its expression (`not p['disputed']`), a screen by its name, or a TIA node id;
- `kf`: the key value of the KF node.

```
tia neo4j-sync --repo payments-app=. --kf-links links.csv --kf-label SystemExtract --kf-key extract_id
```

This writes `(:TiaEndpoint)-[:IMPLEMENTS {kf_link: true}]->(:SystemExtract {extract_id: ...})` for every pair whose two ends exist. Change
the relationship type with `--kf-rel`. Pairs that cannot be linked are returned with the reason, for example:
- "no TIA node matches";
- "more than one TIA node matches";
- "no :SystemExtract node with extract_id = ...".

Links survive re-syncs while both ends exist.

The KF label and key names (`SystemExtract`, `SubFunction`, `Rule`, `TestCase` and their properties) must come from the KF team; the
example above uses placeholders. Once KF links its own test cases to sub-functions, the query above can be extended:

endpoint → `IMPLEMENTS` → system extract → sub-function → KF test case.

## Security

- The mirror holds **every repository of the tenant**, and Neo4j does not apply TIA's per-repository visibility. Grant access to the Neo4j database only to principals and agents that may read the whole landscape. The API refuses a sync started by a caller who cannot read every repository.
- Every node and relationship carries `tenant`. When tenants share one Neo4j database, give each tenant's agents a database or role that filters on it, or use one database per tenant (`NEO4J_DATABASE`).
- Values already kept out of TIA's records (secrets in source, configuration values) are not in the graph, so they are not in the mirror.

## Tests

`tests/test_neo4jgraph.py` tests the projection without a server. With `TIA_TEST_NEO4J_URI` and `TIA_TEST_NEO4J_PASSWORD` set, it also tests
against a real Neo4j:
- the sync;
- the Cypher regression query against the engine;
- re-sync and stale removal;
- tenant isolation;
- ontology links;
- the API.

CI starts `neo4j:5.26.4-community`, pinned by digest, as a service for these tests.
