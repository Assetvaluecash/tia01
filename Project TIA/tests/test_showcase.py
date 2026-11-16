"""The client showcase (docs/SHOWCASE.md, tools/showcase.py): every expected result its README states is checked here, through the git
repositories AND through the zip uploads of the web page, and every web-UI section it describes is checked through the API that section
calls. If TIA changes what it answers, this test fails before a client sees a README that no longer matches."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_app
from fixtures.build_showcase_fixture import EXPECTED, SCENARIOS, UNMAPPED
from tia.impact import AnalysisRequest, analyze
from tools.showcase import DOCS, build_pack, docs_text, load

ALL_CASES = {f"NW-{i:02d}" for i in range(1, 15)}


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    return build_pack(tmp_path_factory.mktemp("pack") / "showcase")


def check_scenario(branch: str, ts: dict, rep: dict):
    e, reg = EXPECTED[branch], ts["regression"]
    assert sorted(c["id"] for c in reg["selected"]) == e["selected"], branch
    assert [c["id"] for c in reg["unmapped"]] == UNMAPPED, branch
    assert {c["id"] for c in reg["selected"] + reg["not_selected"] + reg["unmapped"]} == ALL_CASES, branch
    assert "NW-13" in {c["id"] for c in reg["not_selected"]}, branch                    # the sign-in screen calls no API
    assert sorted(x["entry_point"] for x in ts["entry_points"]) == e["entry_points"], branch
    assert rep["status"] == e["status"] and rep["change"]["change_type"] == e["change_type"], branch
    assert reg["summary"]["headline"].startswith(f"Regression-test {len(e['selected'])} of your 14 test case(s)"), branch


def test_the_pack_holds_what_the_readme_says(pack):
    out = Path(pack["readme"]).parent
    assert sorted(p.name for p in (out / "zips" / "base").iterdir()) == sorted(
        f"{n}.zip" for n in ("payments-api", "statement-service", "mobile-bff", "web-portal", "qa-testcases"))
    assert len(pack["zips"]["scenarios"]) == len(SCENARIOS) == 6
    assert all(Path(p).stat().st_size > 1000 for p in pack["zips"]["scenarios"].values())
    assert json.loads((out / "expected.json").read_text(encoding="utf-8"))["scenarios"] == EXPECTED
    readme = Path(pack["readme"]).read_text(encoding="utf-8")
    for i, (branch, _) in enumerate(SCENARIOS, 1):
        assert f"zips/scenarios/{i:02d}-{branch.replace('/', '-')}/payments-api.zip" in readme and EXPECTED[branch]["see"] in readme
    assert {p.name for p in (out / "evidence").iterdir()} >= {"junit-payments-api.xml", "runtime-calls.json", "incident.json"}
    assert Path(pack["archive"]).stat().st_size > 10_000
    assert DOCS.read_text(encoding="utf-8") == docs_text(), "run  python tools/showcase.py --docs"


@pytest.mark.parametrize("branch", [b for b, _ in SCENARIOS])
def test_every_scenario_through_git(pack, branch):
    rep = analyze(AnalysisRequest(repos=pack["repos"], target="payments-api", base=pack["shas"]["base"], head=pack["shas"][branch]))
    ts = rep["test_scope"]
    check_scenario(branch, ts, rep)
    if branch == "feature/holds":
        [c] = ts["config_checks"]
        assert (c["key"], c["kind"], c["set_in"]) == ("HOLDS_ENABLED", "config_newly_read", [])
        assert [o["function"] for o in c["other_readers"]] == ["held_amount"]
    if branch == "feature/min-balance":
        assert [(c["key"], c["change"], c["readers"][0]["function"]) for c in ts["config_checks"]] == [("MIN_BALANCE", "value_changed", "can_pay")]
        assert "MIN_BALANCE=100" not in json.dumps(rep)
    if branch == "feature/remove-disputed":
        sev = {(f["component"], f["severity"]) for f in rep["findings"]}
        assert ("statement-service", "critical") in sev and ("mobile-bff", "high") in sev
        assert len(ts["rule_gaps"]) == 1 and len(ts["consistency_checks"]) == 1
        assert [m["service"] for m in ts["rule_gaps"][0]["missing_in"]] == ["mobile-bff"]
    if branch == "feature/drop-reference":
        assert any(u["area"] == "truncated_traversal" for u in rep["unknowns"])
        assert any(c["type"] == "db_column" and c["change"] == "column_dropped" for c in rep["change"]["changed_components"])
        deeper = analyze(AnalysisRequest(repos=pack["repos"], target="payments-api", base=pack["shas"]["base"], head=pack["shas"][branch],
                                         max_depth=12))
        assert deeper["status"] == "complete_with_gaps"                                   # section 6: a higher limit follows it through


def test_the_web_ui_route_upload_zips_analyse_and_every_section(pack, tmp_path):
    c = TestClient(make_app(tmp_path / "ws"))
    done = load(c, pack["zips"]["base"])                                                 # section 1 (upload) and the evidence for 5a
    assert sorted(done["uploaded"]) == sorted(pack["zips"]["base"])
    assert done["test_results"]["failed"] == 1 and "INC-2001" in json.dumps(done["incident"])
    base_zip = Path(pack["zips"]["base"]["payments-api"]).read_bytes()
    reports = {}
    for i, (branch, _) in enumerate(SCENARIOS):                                         # section 3: upload, "Analyse vs previous upload"
        if i:
            assert c.put("/api/v1/repositories/payments-api/upload", content=base_zip).status_code == 200
        assert c.put("/api/v1/repositories/payments-api/upload", content=Path(pack["zips"]["scenarios"][branch]).read_bytes()).status_code == 200
        r = c.post("/api/v1/impact-analyses", json={"target": "payments-api", "base": "main~1", "head": "main"})
        assert r.status_code == 200, r.text
        rep = r.json()["report"]
        check_scenario(branch, rep["test_scope"], rep)
        reports[branch] = rep
    # section 4: the tester pack of scenario 1
    pk = c.get(f"/api/v1/impact-analyses/{reports['feature/holds']['analysis_id']}/tester-pack").json()
    assert any(x["entry_point"] == "POST /payments" for x in pk["api"]["endpoints"]) and any(p["page"] == "/pay" for p in pk["ui"]["pages"])
    # section 2: the graph and "ask the graph"
    q = c.get("/api/v1/graph/query", params={"question": "consumers", "component": "GET /accounts/{account_id}/payments"}).json()
    assert q["status"] == "ok"
    assert {"statement-service", "mobile-bff", "web-portal"} <= {x["service"] for x in q["results"]["consumers"]}
    # section 5: tester views
    sc = c.get("/api/v1/graph/shared-components").json()
    assert any(g["shared_entry_point"] == "GET /accounts/{account_id}/payments" for g in sc["rule_gaps"])
    cov = c.get("/api/v1/coverage").json()
    assert cov["summary"]["written_tests"] == 14
    ui = c.get("/api/v1/automation/ui").json()
    assert sorted(p["page"] for p in ui["pages"]) == ["/accounts", "/done", "/login", "/pay"]
    api = c.get("/api/v1/automation/api").json()
    assert any(e["entry_point"] == "POST /payments" and e["cases"] for e in api["endpoints"])
    one = c.post("/api/v1/coverage/test-case", json={"title": "Payment refused below the minimum balance", "entry_point": "POST /payments",
                                                     "expected": "Refused: 409 insufficient balance"}).json()
    assert one["matched"] and any(m["entry_point"] == "POST /payments" for m in one["matched"])
    # execution flow and the automation script
    fl = c.get("/api/v1/graph/flows", params={"endpoint": "POST /payments"}).json()
    text = fl["text"][0]
    assert "api_create_payment [controller]" in text and "create_payment [service]" in text and "save_payment [data access]" in text
    assert "payments.created" in text and any(d["service"] == "payments-api" and d["entities"] for d in fl["design"])
    r = c.post("/api/v1/automation/script", json={"repo": "web-portal", "from": "/login", "to": "/done"})
    assert r.status_code == 200, r.text
    sc_ = r.json()
    assert sc_["screens"] == ["/login", "/accounts", "/pay", "/done"] and "expect(response.status()).toBe(201)" in sc_["script"]
    # the same through the Python SDK
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
    from tia_client import TiaClient

    def transport(method, url, headers, body, timeout):
        resp = c.request(method, url.replace("http://testserver", ""), headers=headers, content=body)
        return resp.status_code, resp.content
    sdk = TiaClient("http://testserver", transport=transport)
    assert sdk.execution_flow("POST /payments")["flows"][0]["entry_point"] == "POST /payments"
    assert sdk.automation_script("web-portal", "/login", "/done")["screens"][-1] == "/done"
    # section 5a: releases, what ran where, incidents
    assert any(r["name"] == "2026.11-showcase" for r in c.get("/api/v1/releases").json()["releases"])
    env = json.dumps(c.get("/api/v1/environments").json())
    assert "staging" in env and "production" in env
    inv = c.get("/api/v1/incidents/INC-2001/investigation")
    assert inv.status_code == 200
    # section 5b: trends of the analyses just run
    tr = c.get("/api/v1/trends").json()
    assert "payments-api" in json.dumps(tr)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed: the generated script's syntax is not checked")
def test_the_generated_script_is_valid_javascript(pack, tmp_path):
    from tia.graph import build_graph
    from tia.impact import _extract
    from tia.scripts import generate
    ex = {n: _extract(n, p, "main", None, ()) for n, p in pack["repos"].items()}
    out = generate(build_graph(ex), ex, "web-portal", "/login", "/done")
    f = tmp_path / out["file_name"]
    f.write_text(out["script"], encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert out["unknowns"] == [] and "page.getByTestId('pay').click()" in out["script"]
