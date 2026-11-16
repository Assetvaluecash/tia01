"""Support script (not production code): writes the client showcase pack (docs/SHOWCASE.md) and, optionally, loads it into a running TIA.

    python tools/showcase.py [--out showcase]                              # write the pack
    python tools/showcase.py --out showcase --load http://127.0.0.1:8080 [--token TOKEN]   # and load it through the API

The pack (one folder, also zipped as tia-showcase.zip next to it):
  repos/               five git repositories with the main branch and six scenario branches (register them by path, or use the CLI)
  zips/base/           one zip per repository: upload these first (section 1 "Upload zip")
  zips/scenarios/NN-*/ payments-api after one change: upload it, then "Analyse vs previous upload"
  evidence/            CI test results (JUnit), deployments, observed runtime calls (OTLP) and an incident, as the API takes them
  README.md            what to do in every section of the web UI and what you should see
  expected.json        the same expectations, machine-readable (tests/test_showcase.py checks them)

--load uploads the base zips with the same API the web page uses, then records a release, the CI results, the deployments, the runtime
calls and the incident, so every section of the web UI has data. Nothing else is changed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from fixtures.build_showcase_fixture import EXPECTED, REPOS, SCENARIOS, SUITE, UNMAPPED, build  # noqa: E402

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="3">
  <testcase classname="tests.test_api" name="test_create_payment" file="tests/test_api.py" time="0.11"/>
  <testcase classname="tests.test_api" name="test_balance" file="tests/test_api.py" time="0.04">
    <failure message="assert 'USD' == 'EUR'">the balance came back in the wrong currency</failure></testcase>
  <testcase classname="tests.test_api" name="test_unknown_payment" file="tests/test_api.py" time="0.03"/>
</testsuite></testsuites>"""
RUNTIME = [("statement-service", "payments-api", "/accounts/{account_id}/payments", "production"),
           ("mobile-bff", "payments-api", "/accounts/{account_id}/payments", "production"),
           ("partner-portal", "payments-api", "/accounts/{account_id}/payments", "production")]
INCIDENT = {"id": "INC-2001", "title": "Statement PDF shows a refunded payment twice", "service": "statement-service", "environment": "production",
            "started_at": "2026-11-12T09:00:00Z", "ended_at": "2026-11-12T10:30:00Z", "severity": "high"}


def slug(branch: str) -> str:
    return branch.replace("/", "-")


def _git(path: Path, *args) -> bytes:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=True).stdout


def build_pack(out: Path) -> dict:
    """Write the pack into `out` (emptied first). -> {"repos", "zips": {"base": [...], "scenarios": {branch: path}}, "readme"}"""
    if out.exists():
        shutil.rmtree(out)
    (out / "zips" / "base").mkdir(parents=True)
    fx = build(str(out / "repos"))
    base = {}
    for name in REPOS:
        z = out / "zips" / "base" / f"{name}.zip"
        z.write_bytes(_git(Path(fx["paths"][name]), "archive", "--format=zip", "main"))
        base[name] = str(z)
    scen = {}
    for i, (branch, _) in enumerate(SCENARIOS, 1):
        d = out / "zips" / "scenarios" / f"{i:02d}-{slug(branch)}"
        d.mkdir(parents=True)
        (d / "payments-api.zip").write_bytes(_git(Path(fx["paths"]["payments-api"]), "archive", "--format=zip", branch))
        scen[branch] = str(d / "payments-api.zip")
    ev = out / "evidence"
    ev.mkdir()
    (ev / "junit-payments-api.xml").write_text(JUNIT, encoding="utf-8")
    (ev / "runtime-calls.json").write_text(json.dumps([dict(zip(("from", "to", "path", "environment"), c)) for c in RUNTIME], indent=2), encoding="utf-8")
    (ev / "incident.json").write_text(json.dumps(INCIDENT, indent=2), encoding="utf-8")
    (ev / "deployments.md").write_text("Deployments name exact revisions, which TIA gives each upload when it is stored: `--load` reads them from "
                                       "TIA and records payments-api in staging and production, the consumers in production.\n", encoding="utf-8")
    (out / "expected.json").write_text(json.dumps({"scenarios": EXPECTED, "always_unmapped": UNMAPPED}, indent=2), encoding="utf-8")
    (out / "README.md").write_text(readme(), encoding="utf-8")
    archive = out.parent / "tia-showcase.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, Path("tia-showcase") / f.relative_to(out))
    return {"repos": fx["paths"], "shas": fx["shas"], "zips": {"base": base, "scenarios": scen}, "readme": str(out / "README.md"),
            "archive": str(archive)}


def load(c, base_zips: dict) -> dict:
    """c: an httpx.Client or FastAPI TestClient pointed at TIA. Uploads the base zips and records the evidence."""
    from demo_seed import check, otlp
    done = {"uploaded": []}
    for name, path in base_zips.items():
        r = check(c.put(f"/api/v1/repositories/{name}/upload", content=Path(path).read_bytes()), f"upload {name}")
        done["uploaded"].append(r.get("name", name))
    r = c.post("/api/v1/releases", content=json.dumps({"name": "2026.11-showcase", "revisions": {n: "main" for n in base_zips},
                                                          "description": "Northwind showcase"}))
    revs = (check(r, "release")["revisions"] if r.status_code != 409 else
            next(x["revisions"] for x in check(c.get("/api/v1/releases"), "releases")["releases"] if x["name"] == "2026.11-showcase"))
    done["release"] = "2026.11-showcase"
    done["test_results"] = check(c.post(f"/api/v1/evidence/test-results?repo=payments-api&revision={revs['payments-api']}&build_id=ci-77"
                                        "&environment=ci", content=JUNIT), "test results")["counts"]
    deps = [{"repo": "payments-api", "environment": "staging", "revision": revs["payments-api"], "deployed_at": "2026-11-10T09:00:00Z"},
            {"repo": "payments-api", "environment": "production", "revision": revs["payments-api"], "deployed_at": "2026-11-11T08:00:00Z"},
            {"repo": "statement-service", "environment": "production", "revision": revs["statement-service"], "deployed_at": "2026-11-09T08:00:00Z"},
            {"repo": "mobile-bff", "environment": "production", "revision": revs["mobile-bff"], "deployed_at": "2026-11-09T08:30:00Z"}]
    done["deployments"] = check(c.post("/api/v1/evidence/deployments?source=pipeline", content=json.dumps(deps)), "deployments")["deployments"]
    done["runtime_edges"] = check(c.post("/api/v1/evidence/runtime?format=otlp&source=otel-collector", content=otlp(RUNTIME)), "runtime")["edges"]
    done["incident"] = check(c.post("/api/v1/incidents?source=itsm", content=json.dumps(INCIDENT)), "incident")["incident"]
    return done


SECTIONS = """
## Walk through every section of the web UI

Start TIA (`python tools/run_dev.py --data demo-data/showcase`), open http://127.0.0.1:8080, and follow the sections in order. With
`python tools/showcase.py --out showcase --load http://127.0.0.1:8080`, steps 1 and 7 are already done for you (it uploads the base
zips and loads the evidence through the API, as a pipeline would).

| Section | What to do | What you should see |
|---|---|---|
| **1. Repositories → Upload zip** | Upload the five zips of `zips/base/`, one at a time; the repository name is the file name (payments-api, statement-service, mobile-bff, web-portal, qa-testcases). | Five repositories of kind *upload*. |
| **2. Code graph** | Level *service*. Then search `payments` at level *function*. | payments-api with statement-service, mobile-bff and web-portal calling it; the topic `payments.created` consumed by statement-service. |
| **2. Ask the graph** | *Consumers of* `GET /accounts/{account_id}/payments`. | statement-service, mobile-bff and web-portal. |
| **3. Analyse a change** | For each scenario below: upload its `payments-api.zip` (same name, payments-api), press **Analyse vs previous upload**, then **Run analysis**. Before the next scenario, upload `zips/base/payments-api.zip` again so the next change is compared with the original. | The result in the scenario table. |
| **4. Report → What to test** | Open any scenario's report. | First **Regression-test N of your 14 test case(s)** with the reason per test case, NW-14 under *review by hand*, then the entry points, rule gaps, consistency and configuration checks. |
| **4. Report → Tester pack** | Press *Tester pack* on scenario 1. | The coverage gate, the API test matrix of `POST /payments` and the locator pack of the Pay screen. |
| **5. Tester views → Common components & rule gaps** | Open the tab. | `GET /accounts/{account_id}/payments` is shared; rule gap: statement-service leaves out disputed payments, mobile-bff does not. |
| **5. Tester views → Technical coverage** | Open the tab. | Every API and screen with the aspects the tests and the 14 written cases cover, and the gaps. |
| **5. Tester views → Automation: APIs / pages & locators** | Open both tabs. | Every endpoint's inputs, rules and valid/invalid values; the four screens with their elements and locators. |
| **5. Tester views → Check one test case** | Paste NW-02's title, entry point (`POST /payments`) and expected result. | Which technical aspects it covers (the 409 refusal). |
| **5. Tester views → Execution flow** | Entry point `POST /payments`, then *Show execution flow* (API: `GET /api/v1/graph/flows`; CLI: `tia flows`). | `api_create_payment [controller]` → `create_payment [service]` → `load_account` / `save_payment [data access]` and `publish_created [events]` → topic `payments.created`; below it the design of each service: controllers, models, entities. |
| **5. Tester views → Automation script** | Repository `web-portal`, from `/login` to `/done`, then *Generate script* (API: `POST /api/v1/automation/script`; CLI: `tia script`). | A Playwright test through /login, /accounts, /pay and /done that fills every input with a valid value and waits for `POST /payments` (201); nothing left to review. |
| **5a. Releases, What ran where, Incidents** | Open the three tabs (needs `--load`). | Release *2026.11-showcase*; payments-api in staging and production; incident INC-2001 on statement-service. |
| **5b. Insights** | Open the section after a few analyses. | Trends of the scenarios you ran. |
| **6. Configuration** | Raise *max_depth* to 12, then rerun scenario 5. | Its status changes from *partial* to *complete_with_gaps*. |
| **Neo4j** (optional) | With `NEO4J_URI`/`NEO4J_PASSWORD` set, `POST /api/v1/graph/neo4j-sync`. | The landscape, the 14 test cases and the screens in Neo4j (docs/NEO4J.md has the Cypher). |
"""


def readme() -> str:
    rows = []
    for i, (branch, what) in enumerate(SCENARIOS, 1):
        e = EXPECTED[branch]
        rows.append(f"| {i} | `zips/scenarios/{i:02d}-{slug(branch)}/payments-api.zip` (branch `{branch}`) | {what} | "
                    f"{e['see']} Test cases to rerun: {', '.join(e['selected']) or 'none'}. |")
    cases = "\n".join(f"| {line.split(',')[0]} | {line.split(',')[1]} |" for line in SUITE.strip().splitlines()[1:])
    return f"""# TIA showcase: Northwind Pay

Written for testers and client reviewers who want to try every TIA feature on a small, complete landscape, without access to real code.
Every expected result below is checked on each TIA test run (tests/test_showcase.py), so what you see should match exactly.

## What is inside

| Repository | What it is | What it shows off |
|---|---|---|
| payments-api | FastAPI service in layers: controllers, services, repositories (SQLAlchemy), models, schemas, Kafka producer; config/app.env; an Alembic migration; an OpenAPI file with response examples; tests that assert responses | impact, contracts, data, events, configuration, API structure and examples, execution flow |
| statement-service | consumer of `GET /accounts/{{account_id}}/payments`; leaves out disputed payments (a business rule); listens to `payments.created` | cross-service impact, rule, events |
| mobile-bff | consumer of the same endpoint, shows every payment (the rule gap); reads the payments table directly | rule gap, consistency check, data impact |
| web-portal | React screens /login → /accounts → /pay → /done calling the API | automation: screens, elements, locators, navigation, script generation |
| qa-testcases | the testers' 14 written test cases (`testcases/regression-suite.csv`) | regression selection |

Two ways in: **upload the zips** through the web page (`zips/`), or **register the git repositories** of `repos/` by path (or use the
command line: `tia analyze --repo payments-api=repos/payments-api ... --target payments-api --base main --head feature/holds`).

## The six scenarios

| # | Upload (then *Analyse vs previous upload*) | The change | What TIA should tell you |
|---|---|---|---|
{chr(10).join(rows)}

NW-14 (*Archive export reaches the archive*) names nothing TIA can match, so every scenario lists it under *review by hand*.
NW-13 (*Sign in*) tests the /login screen, which calls no API, so API changes never select it.
{SECTIONS}
## The written test cases

| ID | Title |
|---|---|
{cases}
"""


DOCS = ROOT / "docs" / "SHOWCASE.md"
DOCS_HEAD = """<!-- Generated by tools/showcase.py --docs from the same source as the pack's README; do not edit by hand (a test fails when it is out of
date). -->

> **Make the pack:** `python tools/showcase.py --out showcase` writes the folder below and `tia-showcase.zip` next to it (repositories,
> upload zips, evidence, this README). `--load http://127.0.0.1:8080` also uploads the base zips and the evidence into a running TIA.

"""


def docs_text() -> str:
    return DOCS_HEAD + readme()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "showcase"))
    ap.add_argument("--load", metavar="URL", help="also upload the base zips and the evidence to this running TIA")
    ap.add_argument("--token", help="API token for --load when TIA requires sign-in")
    ap.add_argument("--docs", action="store_true", help="only rewrite docs/SHOWCASE.md")
    a = ap.parse_args()
    if a.docs:
        DOCS.write_text(docs_text(), encoding="utf-8", newline="\n")
        print(f"wrote {DOCS}")
        return
    pack = build_pack(Path(a.out))
    print(f"wrote {a.out} and {pack['archive']}")
    if a.load:
        import httpx
        headers = {"Authorization": f"Bearer {a.token}"} if a.token else {}
        with httpx.Client(base_url=a.load, headers=headers, timeout=300) as c:
            print(json.dumps(load(c, pack["zips"]["base"]), indent=2))


if __name__ == "__main__":
    main()
