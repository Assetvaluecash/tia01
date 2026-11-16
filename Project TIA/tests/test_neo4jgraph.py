"""The Neo4j mirror of TIA's graph (docs/NEO4J.md, docs/MEETING-PAWAN.md step 0).

The projection is tested without a server. The sync, the Cypher regression query, tenant isolation, re-sync and ontology links run against a
real Neo4j when TIA_TEST_NEO4J_URI / TIA_TEST_NEO4J_USER / TIA_TEST_NEO4J_PASSWORD are set (CI starts neo4j:5.26.4-community as a service);
otherwise they are skipped and say so."""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import make_app
from fixtures.build_regression_fixture import build
from tia import neo4jgraph as ng
from tia.airgap import AirGapError
from tia.graph import build_graph
from tia.impact import AnalysisRequest, _extract, analyze

NEO = {"uri": os.environ.get("TIA_TEST_NEO4J_URI"), "user": os.environ.get("TIA_TEST_NEO4J_USER", "neo4j"),
       "password": os.environ.get("TIA_TEST_NEO4J_PASSWORD"), "database": None}
live = pytest.mark.skipif(not (NEO["uri"] and NEO["password"]), reason="no Neo4j: set TIA_TEST_NEO4J_URI and TIA_TEST_NEO4J_PASSWORD")


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return build(str(tmp_path_factory.mktemp("neo4j")))


def extracts_at(fx, rev):
    return {"payments-app": _extract("payments-app", fx["paths"]["payments-app"], rev, None, ())}


def fid(g, name):
    return next(n for n, a in g.nodes.items() if a.get("type") == "function" and a.get("name", "").split(".")[-1] == name)


# ---- projection (no server) --------------------------------------------------------------------------------------------------------------
def test_labels_keep_tia_types_apart_from_the_ontology():
    assert [ng.label_of(t) for t in ("function", "endpoint", "event_schema", "callsite", "", "weird type!")] == \
        ["TiaFunction", "TiaEndpoint", "TiaEventSchema", "TiaCallsite", "TiaUnknown", "TiaWeirdType"]


def test_projection_keeps_tia_names_directions_and_evidence(fx):
    ex = extracts_at(fx, "main")
    g = build_graph(ex)
    p = ng.project(g, "t1", "g-1", ex)
    assert sum(len(v) for v in p["nodes"].values()) == len(g.nodes)
    assert all(r["key"] == f"t1|{r['id']}" for rows in p["nodes"].values() for r in rows)
    assert {"CALLS", "HANDLES", "TESTS"} <= set(p["rels"])                                  # TIA's own relationship names
    call = next(e for e in g.edges if e.rel == "CALLS")
    assert {"src": f"t1|{call.src}", "dst": f"t1|{call.dst}"}.items() <= next(r for r in p["rels"]["CALLS"] if r["src"] == f"t1|{call.src}").items()
    imp = {(r["src"], r["dst"], r["props"]["via"]) for r in p["impacts"]}
    assert (f"t1|{call.dst}", f"t1|{call.src}", "CALLS") in imp                              # a change travels callee -> caller
    h = next(e for e in g.edges if e.rel == "HANDLES")
    assert (f"t1|{h.src}", f"t1|{h.dst}", "HANDLES") in imp                                  # handler -> endpoint
    assert all(r["props"]["status"] for rows in p["rels"].values() for r in rows)
    cases = {r["props"]["case_id"]: r for r in p["test_cases"]}
    assert len(cases) == 10 and cases["TC-03"]["props"]["entry_point"] == "/pay"
    cov = {(r["src"].split("|")[1], r["dst"].split("|")[1]): r["props"] for r in p["covers"]}
    assert not any(src.endswith(":TC-10") for src, _ in cov)                                 # a case naming nothing is not linked
    tc3 = {d: v for (s, d), v in cov.items() if s.endswith(":TC-03")}
    assert tc3 == {"payments-app:POST /payments": {"status": "source_confirmed", "strategy": "screen", "via_page": "/pay"},
                   "payments-app:screen:/pay": {"status": "source_confirmed", "strategy": "screen-named"}}   # the API behind it, and the screen


def test_configuration_comes_from_the_environment_without_a_default_password():
    assert ng.config_from_env({}) is None
    with pytest.raises(ng.Neo4jUnavailable, match="no default password"):
        ng.config_from_env({"NEO4J_URI": "bolt://x:7687"})
    assert ng.config_from_env({"NEO4J_URI": "bolt://x:7687", "NEO4J_PASSWORD": "p"}) == \
        {"uri": "bolt://x:7687", "user": "neo4j", "password": "p", "database": None}


def test_unreachable_and_air_gapped(monkeypatch):
    with pytest.raises(ng.Neo4jUnavailable, match="cannot reach Neo4j"):
        ng.connect({"uri": "bolt://127.0.0.1:1", "user": "neo4j", "password": "x"})
    monkeypatch.setenv("TIA_AIRGAPPED", "true")
    with pytest.raises(AirGapError):
        ng.connect({"uri": "bolt://neo4j.example.com:7687", "user": "neo4j", "password": "x"})


def test_api_refuses_when_neo4j_is_not_configured(tmp_path, fx, monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    c = TestClient(make_app(tmp_path / "ws", allow_local=True))
    assert c.post("/api/v1/graph/neo4j-sync").status_code == 409                            # nothing registered yet
    assert c.post("/api/v1/repositories", json={"path": fx["paths"]["payments-app"], "name": "payments-app"}).status_code == 200
    r = c.post("/api/v1/graph/neo4j-sync")
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


# ---- against a real Neo4j ------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def neo():
    if not (NEO["uri"] and NEO["password"]):
        pytest.skip("no Neo4j: set TIA_TEST_NEO4J_URI and TIA_TEST_NEO4J_PASSWORD")
    drv = ng.connect(NEO)
    tenants = []
    yield drv, tenants
    with drv.session() as s:
        s.run("MATCH (n:TiaNode) WHERE n.tenant IN $t DETACH DELETE n", t=tenants).consume()
        s.run("MATCH (n:TiaGraphVersion) WHERE n.tenant IN $t DETACH DELETE n", t=tenants).consume()
        s.run("MATCH (n:KfTestSystemExtract) DETACH DELETE n").consume()
    drv.close()


def tenant(neo):
    t = f"test-{uuid.uuid4().hex[:10]}"
    neo[1].append(t)
    return t


def synced(neo, fx, rev="main", t=None):
    t = t or tenant(neo)
    ex = extracts_at(fx, rev)
    g = build_graph(ex)
    out = ng.sync(neo[0], ng.project(g, t, f"g-{rev}", ex), t, f"g-{rev}")
    return t, g, out


@live
def test_cypher_answers_use_case_1_exactly_as_the_engine_does(neo, fx):
    t, g, out = synced(neo, fx)
    assert out["test_cases"] == 10 and out["nodes"] == len(g.nodes) + 10
    for branch, changed in (("feature/holds", "balance_of"), ("feature/min-balance", "can_pay"), ("feature/fx-rounding", "convert")):
        rep = analyze(AnalysisRequest(repos=fx["paths"], target="payments-app", base=fx["shas"]["base"], head=fx["shas"][branch]))
        engine = {c["id"] for c in rep["test_scope"]["regression"]["selected"]}
        cypher = {r["test_case"] for r in ng.regression_tests(neo[0], t, [fid(g, changed)])}
        assert cypher == engine, branch
    rows = {r["test_case"]: r for r in ng.regression_tests(neo[0], t, [fid(g, "balance_of")])}
    assert set(rows) == {"TC-01", "TC-02", "TC-03", "TC-07"}
    assert rows["TC-03"]["reached"][0]["via_page"] == "/pay" and rows["TC-07"]["reached"][0]["entry_point"] == "GET /accounts/{account_id}/balance"


@live
def test_resync_replaces_the_version_and_tenants_stay_apart(neo, fx):
    t, _, first = synced(neo, fx)
    other, _, _ = synced(neo, fx)
    _, g2, second = synced(neo, fx, "feature/fx-rounding", t)                 # the landscape moved on: TC-11 was added
    assert second["test_cases"] == 11 and second["removed_stale"] == {"nodes": 0, "relationships": 0}   # same structure: re-stamped
    with neo[0].session() as s:
        versions = s.run("MATCH (n:TiaNode {tenant: $t}) RETURN collect(DISTINCT n.graph_version) AS v", t=t).single()["v"]
        assert versions == ["g-feature/fx-rounding"]
        assert s.run("MATCH (v:TiaGraphVersion {tenant: $t}) RETURN v.graph_version AS v", t=t).single()["v"] == "g-feature/fx-rounding"
        n_other = s.run("MATCH (n:TiaNode {tenant: $t}) RETURN count(n) AS n", t=other).single()["n"]
    assert n_other == first["nodes"]                                                          # the other tenant is untouched
    assert {"TC-08", "TC-09", "TC-11"} == {r["test_case"] for r in ng.regression_tests(neo[0], t, [fid(g2, "convert")])}


@live
def test_what_a_new_version_no_longer_has_is_removed(neo, fx):
    t, g, first = synced(neo, fx)
    ex = extracts_at(fx, "main")
    p = ng.project(g, t, "g-without-rates", ex)
    gone = f"{t}|" + next(n for n, a in g.nodes.items() if a.get("type") == "endpoint" and a.get("route") == "/fx/rates")
    p["nodes"] = {lab: [r for r in rows if r["key"] != gone] for lab, rows in p["nodes"].items()}
    drop = lambda rows: [r for r in rows if gone not in (r["src"], r["dst"])]             # noqa: E731
    p["rels"] = {rel: drop(rows) for rel, rows in p["rels"].items()}
    p["impacts"], p["covers"] = drop(p["impacts"]), drop(p["covers"])
    out = ng.sync(neo[0], p, t, "g-without-rates")
    assert out["removed_stale"]["nodes"] == 1 and out["removed_stale"]["relationships"] >= 1 and out["nodes"] == first["nodes"] - 1
    with neo[0].session() as s:
        assert s.run("MATCH (n:TiaNode {key: $k}) RETURN count(n) AS n", k=gone).single()["n"] == 0


@live
def test_ontology_links_are_explicit_and_survive_a_resync(neo, fx):
    t, _, _ = synced(neo, fx)
    with neo[0].session() as s:
        s.run("CREATE (:KfTestSystemExtract {extract_id: 'SE-PAY'})").consume()
    res = ng.link_ontology(neo[0], t, [{"tia": "POST /payments", "kf": "SE-PAY"}, {"tia": "GET /nope", "kf": "SE-PAY"},
                                       {"tia": "GET /fx/rates", "kf": "SE-MISSING"}], "KfTestSystemExtract", "extract_id")
    assert res["linked"] == 1
    assert [m["reason"] for m in res["not_linked"]] == ["no TIA node matches", "no :KfTestSystemExtract node with extract_id = 'SE-MISSING'"]
    with pytest.raises(ValueError):
        ng.link_ontology(neo[0], t, [], "Bad Label", "id")
    synced(neo, fx, "main", t)                                                                  # same version again: links stay
    with neo[0].session() as s:
        n = s.run("MATCH (e:TiaEndpoint {tenant: $t})-[x:IMPLEMENTS {kf_link: true}]->(:KfTestSystemExtract {extract_id: 'SE-PAY'}) "
                  "RETURN count(x) AS n", t=t).single()["n"]
    assert n == 1


@live
def test_automation_and_api_paths_are_walkable_in_cypher(neo, fx):
    t, _, _ = synced(neo, fx)
    with neo[0].session() as s:
        rows = s.run(
            "MATCH (:TiaApplication {tenant: $t})-[:HAS_SCREEN]->(sc:TiaScreen {route: '/pay'})-[:HAS_ELEMENT]->(el:TiaElement) "
            "MATCH (el)-[:LOCATED_BY]->(l:TiaLocator {best: true}) "
            "OPTIONAL MATCH (sc)-[:CALLS_API]->(ep:TiaEndpoint) "
            "RETURN el.name AS element, el.mandatory AS mandatory, l.strategy AS strategy, l.css AS css, l.playwright AS playwright, "
            "ep.method + ' ' + ep.route AS calls ORDER BY el.line", t=t).data()
        assert [(r["element"], r["strategy"], r["css"]) for r in rows] == [
            ("Amount", "id", "#amount"), ("Reference", "id", "#reference"), ("Pay", "test id", '[data-testid="pay"]')]
        assert all(r["calls"] == "POST /payments" for r in rows) and rows[0]["mandatory"] is True
        fields = s.run(
            "MATCH (ep:TiaEndpoint {tenant: $t, method: 'POST', route: '/payments'})-[:ACCEPTS]->(:TiaRequest)-[:HAS_FIELD]->(f:TiaField) "
            "RETURN f.name AS name, f.in AS place, f.required AS required, f.max_length AS max_length ORDER BY name", t=t).data()
        assert [(f["name"], f["place"], f["required"]) for f in fields] == [
            ("account_id", "body", True), ("amount", "body", True), ("currency", "body", True), ("reference", "body", True)]
        assert {f["name"]: f["max_length"] for f in fields}["reference"] == 18
        resp = s.run("MATCH (:TiaEndpoint {tenant: $t, method: 'POST', route: '/payments'})-[:RETURNS]->(r:TiaResponse) "
                     "RETURN r.success_status AS ok, r.error_statuses AS errors", t=t).single()
        assert (resp["ok"], resp["errors"]) == (201, [404, 409])
        s.run("CREATE (:KfTestSystemExtract {extract_id: 'RULE-OWN-ACCOUNT'})").consume()
    res = ng.link_ontology(neo[0], t, [{"tia": "p['account_id'] == account_id", "kf": "RULE-OWN-ACCOUNT"}], "KfTestSystemExtract", "extract_id")
    assert res == {"linked": 1, "not_linked": []}                                              # a code rule linked by its expression


@live
def test_the_api_mirrors_the_landscape(tmp_path, fx, neo, monkeypatch):
    monkeypatch.setenv("NEO4J_URI", NEO["uri"])
    monkeypatch.setenv("NEO4J_USER", NEO["user"])
    monkeypatch.setenv("NEO4J_PASSWORD", NEO["password"])
    c = TestClient(make_app(tmp_path / "ws", allow_local=True))
    assert c.post("/api/v1/repositories", json={"path": fx["paths"]["payments-app"], "name": "payments-app"}).status_code == 200
    r = c.post("/api/v1/graph/neo4j-sync")
    assert r.status_code == 200, r.text
    body = r.json()
    neo[1].append(body["tenant"])
    assert body["test_cases"] == 10 and body["nodes"] > 10 and body["graph_version"].startswith("g-")
