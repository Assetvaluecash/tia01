"""The fixed graph representation (tia/graphschema.py, docs/GRAPH-SCHEMA.md; docs/MEETING-PAWAN.md "fix the representation once").

Every demo landscape's graph conforms to the schema, every property the schema lists is real, the document is generated from the schema,
each use case can walk its path (automation: application > screen > element > locator; API: endpoint > request/response > field; rules),
and adding the use-case structure changed no analysis result."""
import importlib
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

import tia.graph as graph_mod
from tia.graph import _IMPACT_DST, _IMPACT_SRC, build_graph
from tia.graphschema import EDGE_TYPES, GRAPH_SCHEMA_VERSION, NODE_TYPES, violations
from tia.graphstore import graph_inputs
from tia.impact import AnalysisRequest, _extract, analyze

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ("build_fixture", "build_lanes_fixture", "build_java_fixture", "build_data_fixture", "build_events_fixture",
            "build_polyglot_fixture", "build_sql_fixture", "build_streams_fixture", "build_regression_fixture")


@pytest.fixture(scope="module")
def landscapes(tmp_path_factory):
    out = {}
    for mod in FIXTURES:
        fx = importlib.import_module(f"fixtures.{mod}").build(str(tmp_path_factory.mktemp(mod)))
        ex = {n: _extract(n, p, "HEAD", None, ()) for n, p in fx["paths"].items()}
        out[mod] = (fx, ex, build_graph(ex))
    return out


def test_every_demo_graph_conforms_to_the_schema(landscapes):
    for mod, (_, _, g) in landscapes.items():
        assert violations(g) == [], mod


def test_the_schema_lists_only_real_properties_and_every_type_is_built(landscapes):
    keys, seen_rels = defaultdict(set), set()
    for _, _, g in landscapes.values():
        for a in g.nodes.values():
            keys[a["type"]] |= set(a)
        seen_rels |= {e.rel for e in g.edges}
    assert set(NODE_TYPES) - set(keys) == {"runtime_ref"}          # added only to an analysis's own copy, from runtime evidence
    for t, spec in NODE_TYPES.items():
        if t in keys:
            assert not [p for p in spec["properties"] if p not in keys[t]], t
    assert set(EDGE_TYPES) - seen_rels <= {"INHERITS"}             # INHERITS: Java fixtures without class hierarchies; see test_java


def test_the_engine_walks_exactly_what_the_schema_says():
    assert set(_IMPACT_DST) == {r for r, e in EDGE_TYPES.items() if e["impact"] == "dst->src"}
    assert set(_IMPACT_SRC) == {"HANDLES", "PUBLISHES"}
    new = {"HAS_APPLICATION", "HAS_SCREEN", "HAS_ELEMENT", "LOCATED_BY", "CALLS_API", "ACCEPTS", "RETURNS", "HAS_FIELD", "APPLIES_RULE"}
    assert all(EDGE_TYPES[r]["impact"] is None for r in new)       # use-case structure never carries impact


def test_the_schema_version_is_part_of_every_graph_version():
    assert graph_inputs({})["schema"] == GRAPH_SCHEMA_VERSION


def test_the_document_is_generated_from_the_schema():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_graph_schema.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---- the use cases walk their paths ----------------------------------------------------------------------------------------------------
def out_of(g, nid, rel):
    return [e.dst for e in g.edges if e.src == nid and e.rel == rel]


def test_automation_application_screen_element_locator(landscapes):
    _, _, g = landscapes["build_regression_fixture"]
    [app] = out_of(g, "svc:payments-app", "HAS_APPLICATION")
    assert g.nodes[app]["type"] == "application" and g.nodes[app]["frameworks"] == ["react"]
    [screen] = out_of(g, app, "HAS_SCREEN")
    assert g.nodes[screen]["route"] == "/pay"
    assert out_of(g, screen, "CALLS_API") == ["payments-app:POST /payments"]
    els = {g.nodes[e]["name"]: e for e in out_of(g, screen, "HAS_ELEMENT")}
    amount = g.nodes[els["Amount"]]
    assert amount["mandatory"] and amount["minimum"] == 0.01 and amount["maximum"] == 10000 and amount["input_type"] == "number"
    assert g.nodes[els["Reference"]]["max_length"] == 18
    locs = sorted((g.nodes[x] for x in out_of(g, els["Amount"], "LOCATED_BY")), key=lambda l: l["rank"])
    assert locs[0]["strategy"] == "id" and locs[0]["css"] == "#amount" and locs[0]["xpath"] == "//*[@id='amount']" and locs[0]["best"]
    assert sum(1 for l in locs if l["best"]) == 1 and locs[-1]["strategy"] == "position (fragile)" and not locs[-1]["best"]
    pay = g.nodes[els["Pay"]]
    assert pay["tag"] == "button" and any(g.nodes[x]["playwright"] == "getByTestId('pay')" for x in out_of(g, els["Pay"], "LOCATED_BY"))


def test_dropdown_values_are_kept_and_dynamic_ones_are_said(landscapes):
    _, _, g = landscapes["build_lanes_fixture"]
    sel = [a for a in g.nodes.values() if a["type"] == "element" and a["tag"] == "select"]
    by = {a["name"]: a for a in sel}
    assert by["Month"]["options"] == ["2026-09", "2026-10", "2026-11"]
    assert any(a.get("options_source", "").startswith(("static", "literal", "dynamic")) for a in sel)


def test_api_request_response_and_field_definitions(landscapes):
    _, _, g = landscapes["build_regression_fixture"]
    ep = "payments-app:POST /payments"
    [req] = out_of(g, ep, "ACCEPTS")
    [resp] = out_of(g, ep, "RETURNS")
    fields = {g.nodes[f]["name"]: g.nodes[f] for f in out_of(g, req, "HAS_FIELD")}
    assert set(fields) == {"account_id", "amount", "currency", "reference"} and g.nodes[req]["body_schema"] == "PaymentRequest"
    assert fields["account_id"].items() >= {"in": "body", "field_type": "str", "required": True, "min_length": 6, "max_length": 12}.items()
    assert fields["amount"]["exclusive_minimum"] == 0 and fields["amount"]["maximum"] == 10000
    r = g.nodes[resp]
    assert (r["schema"], r["success_status"], r["shape"], r["error_statuses"]) == ("Payment", 201, "object", [404, 409])
    assert {g.nodes[f]["name"] for f in out_of(g, resp, "HAS_FIELD")} == {"payment_id", "account_id", "amount", "currency", "status"}
    [preq] = out_of(g, "payments-app:GET /payments/{}", "ACCEPTS")
    path = [g.nodes[f] for f in out_of(g, preq, "HAS_FIELD")]
    assert [(f["name"], f["in"]) for f in path] == [("payment_id", "path")]


def test_business_rules_found_in_code(landscapes):
    _, _, g = landscapes["build_lanes_fixture"]
    rules = [(a["function"], a["expr"], a["fields"]) for a in g.nodes.values() if a["type"] == "rule"]
    assert any("disputed" in expr and fields == ["disputed"] for _, expr, fields in rules)
    rid = next(n for n, a in g.nodes.items() if a["type"] == "rule" and "disputed" in a["expr"])
    assert [e.src for e in g.edges if e.dst == rid and e.rel == "APPLIES_RULE"] and g.nodes[rid]["line"]


# ---- the representation grew; no analysis changed ---------------------------------------------------------------------------------
def essence(rep):
    ts = rep["test_scope"]
    return {"findings": sorted((f["component"], f["severity"], f["evidence_status"], tuple(p["node"] for p in f["path"])) for f in rep["findings"]),
            "entry_points": sorted((e["node"], e["change_effect"], e["evidence_status"]) for e in ts["entry_points"]),
            "top": sorted(e["node"] for e in ts["code_without_entry_point"]), "gaps": len(ts["rule_gaps"]),
            "regression": sorted(c["id"] for c in ts["regression"]["selected"]), "status": rep["status"],
            "unknowns": sorted(u["area"] for u in rep["unknowns"])}


@pytest.mark.parametrize("mod,target,branches", [("build_fixture", "payments-service", ("breaking", "impl")),
                                                  ("build_lanes_fixture", "payments-service", ("behaviour", "contract")),
                                                  ("build_regression_fixture", "payments-app", ("feature/holds",))])
def test_adding_the_structure_changes_no_analysis(landscapes, monkeypatch, mod, target, branches):
    fx = landscapes[mod][0]
    run = lambda b: analyze(AnalysisRequest(repos=fx["paths"], target=target, base=fx["shas"]["base"], head=fx["shas"][b]))  # noqa: E731
    with_structure = {b: essence(run(b)) for b in branches}
    monkeypatch.setattr(graph_mod, "add_structure", lambda g, ex: None)
    without = {b: essence(run(b)) for b in branches}
    assert with_structure == without
