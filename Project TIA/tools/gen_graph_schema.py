"""Support script (not production code): writes docs/GRAPH-SCHEMA.md from tia/graphschema.py, so the document cannot drift from the schema
the code builds and the tests enforce.

    python tools/gen_graph_schema.py           # rewrite docs/GRAPH-SCHEMA.md
    python tools/gen_graph_schema.py --check   # exit 1 if it is out of date (tests/test_graphschema.py does this)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tia.graphschema import EDGE_TYPES, GRAPH_SCHEMA_VERSION, NODE_TYPES  # noqa: E402
from tia.neo4jgraph import label_of  # noqa: E402

OUT = ROOT / "docs" / "GRAPH-SCHEMA.md"
GROUPS = [("code", "Code and services"), ("data", "Data"), ("events", "Events"), ("automation", "Automation: Application > Screen > Element > Locator"),
          ("api", "API testing: Endpoint > Request / Response > Field"), ("rules", "Business rules")]
IMPACT = {"src->dst": "source → target", "dst->src": "target → source", None: "not traversed"}

HEAD = f"""# TIA graph schema

*Generated from [tia/graphschema.py](../tia/graphschema.py) by `tools/gen_graph_schema.py`; do not edit by hand (a test fails when it is out of
date). Schema version `{GRAPH_SCHEMA_VERSION}`.*

Written for the people who decide how TIA's knowledge is represented, and for anyone who queries it (Knowledge Fabric agents, Cypher, the
API). This is the fixed representation every use case is answered from (see [MEETING-PAWAN.md](MEETING-PAWAN.md)). It changes only by a
deliberate, versioned decision: a change to [tia/graphschema.py](../tia/graphschema.py) bumps the schema version, which gives every graph a
new version id.

## Where it is stored

* **PostgreSQL** is the system of record: each graph version is immutable and content-addressed, and it is stored with the repository
  commits it was built from ([GRAPH-STORE.md](GRAPH-STORE.md)). The impact engine walks it in memory.
* **Neo4j** holds a mirror of each tenant's current version for Knowledge Fabric ([NEO4J.md](NEO4J.md)). A node type `x` becomes the
  label `TiaX`, and relationships keep the names below.
* **Enforcement:** `tests/test_graphschema.py` builds the graph of every demo landscape and fails on any node type or relationship this
  schema does not allow.

## The picture

```
Service ─EXPOSES→ Endpoint ←HANDLES─ Function ─CALLS→ Function ─READS/WRITES→ Entity / Table / Column
   │                 │  ↑                │   └─APPLIES_RULE→ Rule
   │                 │  └─CONSUMES_API── Callsite ←ISSUES─ Function (another service)
   │                 ├─ACCEPTS→ Request ─HAS_FIELD→ Field
   │                 ├─RETURNS→ Response ─HAS_FIELD→ Field
   │                 └─USES_SCHEMA→ Schema
   └─HAS_APPLICATION→ Application ─HAS_SCREEN→ Screen ─HAS_ELEMENT→ Element ─LOCATED_BY→ Locator
                                                 └─CALLS_API→ Endpoint
Test ─TESTS→ Endpoint / Function          (Neo4j adds) TestCase ─COVERS→ Endpoint,  Endpoint/Rule ─IMPLEMENTS→ Knowledge Fabric node
```

## How a change travels (impact)

Only relationships with an impact direction carry a change. A relationship marked *not traversed* is structure that use cases read
(screens, fields, rules). Adding such structure never changes an impact result.

"""

USE_CASES = """
## How each use case reads it

| Use case | Path through the graph |
|---|---|
| **Blast radius and regression tests** (use case 1) | changed Function, following impact relationships (Neo4j: `IMPACTS`), to an Endpoint; written TestCase `COVERS` Endpoint. See [NEO4J.md](NEO4J.md). |
| **Automation script for a flow** "screen A to screen B" | Application `HAS_SCREEN` Screen A and Screen B; each Screen `HAS_ELEMENT` Element (mandatory, rules, dropdown values); each Element `LOCATED_BY` Locator with `best = true` (rank 1 is tried first); Screen `CALLS_API` Endpoint for the requests the flow sends. |
| **API test cases / calling an API** | Endpoint `ACCEPTS` Request `HAS_FIELD` Field (where it goes, type, required, allowed values, limits); Endpoint `RETURNS` Response (success status, error statuses, shape) `HAS_FIELD` Field. |
| **Business rules** | Function `APPLIES_RULE` Rule (the condition and the fields it tests). Endpoint `HANDLES`/`CALLS` paths show which entry points a rule sits behind. |
| **Knowledge Fabric ontology** | an Endpoint, Rule or Screen `IMPLEMENTS` a KF node, from an explicit mapping only ([NEO4J.md](NEO4J.md)). The KF test case and sub-function are then reached from there. |

## What is not in it (yet)

* **Expected response examples:** OpenAPI `example(s)` and response bodies from tests are not captured; a Response has its schema, success status and error statuses.
* **The order of screens in a flow:** a flow "A to B" is given by the person or agent asking. Navigation between screens is not extracted.
* **Rules linked to the fields of a specific endpoint:** a Rule names the fields it tests; linking them to Field nodes needs the endpoint whose data it filters, which the rule-gap analysis works out per use (tia.testscope).
* **Values filled at run time:** dropdown values or element ids built by code are marked dynamic, never guessed.
"""


def render() -> str:
    L = [HEAD]
    L += ["## Node types", ""]
    for g, title in GROUPS:
        rows = [(t, n) for t, n in NODE_TYPES.items() if n["group"] == g]
        L += [f"### {title}", "", "| Type | Neo4j label | Meaning | Properties |", "|---|---|---|---|"]
        for t, n in rows:
            detail = " *(many per parent: left out of overview pictures)*" if n.get("detail") else ""
            opt = f"; when declared: {', '.join(f'`{p}`' for p in n['optional'])}" if n.get("optional") else ""
            L.append(f"| `{t}` | `{label_of(t)}` | {n['description']}{detail} | {', '.join(f'`{p}`' for p in n['properties'])}{opt} |")
        L.append("")
    L += ["## Relationships", "", "| Relationship | From | To | Impact travels | Meaning |", "|---|---|---|---|---|"]
    for r, e in EDGE_TYPES.items():
        L.append(f"| `{r}` | {', '.join(f'`{x}`' for x in sorted(e['from']))} | {', '.join(f'`{x}`' for x in sorted(e['to']))} | "
                 f"{IMPACT[e['impact']]} | {e['description']} |")
    L += ["", "Every relationship also records its evidence: `status` (`source_confirmed`, `contract_confirmed`, `runtime_observed`, `inferred`, "
          "...), the `strategy` that found it, the inference `rule` when it is inferred, and the repository, file, line and commit it came from."]
    return "\n".join(L) + "\n" + USE_CASES


def main(argv=None) -> int:
    text = render()
    if "--check" in (argv or sys.argv[1:]):
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print("docs/GRAPH-SCHEMA.md is out of date: run python tools/gen_graph_schema.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
