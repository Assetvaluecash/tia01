"""Expected-response examples, screen navigation, the execution-flow view and the automation-script generator (docs/MEETING-PAWAN.md items
2, 3 and 4; docs/GRAPH-SCHEMA.md). The end-to-end route through the web API is in tests/test_showcase.py."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.build_lanes_fixture import build as build_lanes
from fixtures.build_showcase_fixture import build as build_showcase
from tia.extract_openapi import extract_openapi
from tia.extract_python import extract_file
from tia.extract_ui import navigations
from tia.flows import design, flows, render
from tia.graph import build_graph
from tia.impact import _extract
from tia.scripts import generate, route_between

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def showcase(tmp_path_factory):
    fx = build_showcase(str(tmp_path_factory.mktemp("showcase")))
    ex = {n: _extract(n, p, "main", None, ()) for n, p in fx["paths"].items()}
    return fx, ex, build_graph(ex)


# ---- expected-response examples ----------------------------------------------------------------------------------------------------
def test_examples_from_test_assertions():
    src = '''from fastapi.testclient import TestClient
client = TestClient(app)

def test_create():
    r = client.post("/payments", json={"amount": 10})
    assert r.status_code == 201
    assert r.json()["status"] == "PENDING"
    body = r.json()
    assert body["amount"] == 10

def test_whole_body():
    r = client.get("/fx/rates")
    assert r.json() == {"EUR": 1.0}

def test_only_status():
    r = client.get("/x")
    assert r.status_code == 200
'''
    ex = {(x["method"], x["norm_path"]): x for x in extract_file("r", "s", "tests/test_x.py", src).api_examples}
    assert ex[("POST", "/payments")] | {} == {"method": "POST", "norm_path": "/payments", "status": 201, "body": {"status": "PENDING", "amount": 10},
                                             "partial": True, "source": "test", "test": "test_create", "file": "tests/test_x.py", "line": 5}
    assert ex[("GET", "/fx/rates")]["body"] == {"EUR": 1.0} and ex[("GET", "/fx/rates")]["partial"] is False
    assert ("GET", "/x") not in ex                                            # a status alone is not an example body


def test_examples_from_openapi_success_and_error():
    spec = ("openapi: 3.0.0\ninfo: {title: t, version: '1'}\npaths:\n  /p/{id}:\n    get:\n      responses:\n"
            "        '200': {description: ok, content: {application/json: {example: {id: P1}}}}\n"
            "        '404': {description: no, content: {application/json: {examples: {gone: {value: {detail: unknown}}}}}}\n")
    got = sorted((x["status"], json.dumps(x["body"])) for x in extract_openapi("r", "s", "openapi.yaml", spec).api_examples)
    assert got == [(200, '{"id": "P1"}'), (404, '{"detail": "unknown"}')]


def test_examples_hang_under_the_response(showcase):
    _, _, g = showcase
    [resp] = [e.dst for e in g.edges if e.rel == "RETURNS" and e.src == "payments-api:GET /payments/{}"]
    exs = sorted((g.nodes[e.dst]["status"], g.nodes[e.dst]["source"]) for e in g.edges if e.rel == "HAS_EXAMPLE" and e.src == resp)
    assert exs == [(200, "openapi"), (404, "openapi")]       # the spec's examples survive the code's own endpoint; a status-only test adds none
    [post] = [e.dst for e in g.edges if e.rel == "RETURNS" and e.src == "payments-api:POST /payments"]
    [x] = [g.nodes[e.dst] for e in g.edges if e.rel == "HAS_EXAMPLE" and e.src == post]
    assert json.loads(x["body_json"]) == {"status": "PENDING"} and x["partial"] and x["test"] == "test_create_payment"


# ---- navigation between screens ------------------------------------------------------------------------------------------------------
def test_navigation_from_links_and_code():
    assert [n["to"] for n in navigations('<Link to="/a">x</Link><a href="/b?q=1">b</a><a href="https://x.io/c">c</a>'
                                         '<li routerLink="/d"></li><a [routerLink]="[\'/e\']">e</a>', True, False)] == ["/a", "/b", "/d", "/e"]
    assert [n["to"] for n in navigations("navigate(`/u/${id}`); this.router.navigate(['/v']); history.push('/w'); list.push('/no')",
                                         False, True)] == ["/u/{}", "/v", "/w"]


def test_screens_are_connected_in_the_graph(showcase):
    _, _, g = showcase
    nav = sorted((g.nodes[e.src]["route"], g.nodes[e.dst]["route"]) for e in g.edges if e.rel == "NAVIGATES_TO")
    assert nav == [("/accounts", "/pay"), ("/done", "/accounts"), ("/login", "/accounts"), ("/pay", "/done")]
    assert [g.nodes[s]["route"] for s in route_between(g, "web-portal", "/login", "/done")] == ["/login", "/accounts", "/pay", "/done"]
    assert route_between(g, "web-portal", "/done", "/login") is None


# ---- execution flow and design ----------------------------------------------------------------------------------------------------------
def test_execution_flow_follows_layers_services_data_events_and_rules(showcase, tmp_path):
    _, _, g = showcase
    [f] = flows(g, "POST /payments")
    text = render(f)
    for line in ("api_create_payment [controller]", "create_payment [service]", "load_account [data access]", "save_payment [data access]",
                 "publish_created [events]", "payments.created [publishes]", "AccountRecord [reads]"):
        assert line in text, line
    lanes = build_lanes(str(tmp_path / "lanes"))
    exl = {n: _extract(n, p, "HEAD", None, ()) for n, p in lanes["paths"].items()}
    [pdf] = flows(build_graph(exl), "GET /statements/{account_id}/pdf")
    t = render(pdf)
    assert "not p['disputed'] [rule]" in t and "fetch_payments [client]" in t and "GET /accounts/{account_id}/payments on payments-service" in t


def test_design_lists_controllers_models_and_entities(showcase):
    _, _, g = showcase
    [d] = design(g, "payments-api")
    assert {c["function"] for c in d["controllers"]} >= {"api_create_payment", "api_list_payments", "api_refund"}
    assert {m["name"] for m in d["models"]} >= {"Payment", "PaymentRequest", "PaymentRow", "Balance"}
    ent = {e["name"]: e for e in d["entities"]}
    assert "POST /payments (reads)" in ent["AccountRecord"]["used_by"]
    assert d["roles"]["controller"] == 6 and d["roles"]["data access"] >= 4


def test_declared_only_endpoints_say_so():
    from tia.models import RepoExtract, Endpoint
    ex = RepoExtract(repo="r", service="s", commit="c", extractor_version="x",
                     endpoints=[Endpoint("s:GET /x", "s", "r", "GET", "/x", "/x", "openapi:x", "r:openapi.yaml::x", "openapi.yaml", 1, source="openapi")])
    [f] = flows(build_graph({"r": ex}))
    assert f["declared_only"] and f["steps"] == [] and "declared in a specification only" in render(f)


# ---- automation script ----------------------------------------------------------------------------------------------------------------
def test_script_states_what_it_cannot_know(showcase):
    _, ex, g = showcase
    out = generate(g, ex, "web-portal", "/done", "/login")
    assert "no navigation from /done to /login" in out["error"] and out["screens_known"] == ["/accounts", "/done", "/login", "/pay"]
    ok = generate(g, ex, "web-portal", "/login", "/done")
    steps = {s["screen"]: s for s in ok["steps"]}
    assert steps["/pay"]["calls"] == ["POST /payments"] and {f["element"] for f in steps["/pay"]["filled"]} == {"Amount", "Currency", "Reference"}
    assert "page.locator('#password').fill(" in ok["script"] and ok["file_name"] == "flow-login-to-done.spec.js"


def test_the_cli_prints_flows_and_writes_a_script(showcase, tmp_path):
    fx, _, _ = showcase
    repos = [f"--repo={n}={p}" for n, p in fx["paths"].items()]
    r = subprocess.run([sys.executable, "-m", "tia.cli", "flows", *repos, "--endpoint", "GET /accounts/{account_id}/balance"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "api_balance [controller]" in r.stdout and "account_balance [service]" in r.stdout
    out = tmp_path / "flow.spec.js"
    r = subprocess.run([sys.executable, "-m", "tia.cli", "script", *repos, "--app", "web-portal", "--from", "/login", "--to", "/done",
                        "--out", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "page.goto(BASE_URL + \"/login\")" in out.read_text(encoding="utf-8")
