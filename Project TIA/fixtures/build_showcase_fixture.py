"""The client showcase: one small company landscape ("Northwind Pay") that exercises every TIA feature, built as real git repositories with a
main branch and one feature branch per scenario (docs/SHOWCASE.md; tools/showcase.py also packs it as upload zips).

payments-api        FastAPI service in layers: app/api (controllers), app/services, app/repositories (SQLAlchemy), app/models, app/schemas,
                    app/events (Kafka producer). Configuration in config/app.env; an Alembic migration; an OpenAPI file with response examples;
                    automated tests that assert response fields. The shared endpoint GET /accounts/{account_id}/payments returns
                    List[PaymentRow] (with `disputed`).
statement-service   consumer: fetches the shared endpoint, LEAVES OUT disputed payments (the rule), serves GET /statements/{account_id}/pdf,
                    and listens to the payments.created topic.
mobile-bff          consumer: fetches the shared endpoint and shows EVERY payment (no rule: the rule gap); maps the payments table read-only.
web-portal          React front end: /login -> /accounts -> /pay -> /done, calling the payments API.
qa-testcases        the testers' written regression suite: testcases/regression-suite.csv (14 cases, one that names nothing TIA can match).

Scenario branches (all on payments-api, each from main): see SCENARIOS.
"""
from __future__ import annotations

from pathlib import Path

from fixtures.build_fixture import _commit, _run, _write

# ---- payments-api ------------------------------------------------------------------------------------------------------------------
P_SCHEMAS = '''from enum import Enum

from pydantic import BaseModel, Field


class Currency(str, Enum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"


class PaymentRequest(BaseModel):
    account_id: str = Field(min_length=6, max_length=12)
    amount: float = Field(gt=0, le=10000)
    currency: Currency
    reference: str = Field(max_length=18)


class Payment(BaseModel):
    payment_id: str
    account_id: str
    amount: float
    currency: str
    status: str


class PaymentRow(BaseModel):
    payment_id: str
    amount: float
    status: str
    disputed: bool


class Balance(BaseModel):
    account_id: str
    balance: float
    currency: str
'''

P_MODELS = '''from sqlalchemy import Boolean, Column, Numeric, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class AccountRecord(Base):
    __tablename__ = "accounts"
    id = Column(String(12), primary_key=True)
    balance = Column(Numeric(14, 2), nullable=False)
    held = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False)


class PaymentRecord(Base):
    __tablename__ = "payments"
    id = Column(String(20), primary_key=True)
    account_id = Column(String(12), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    status = Column(String(12), nullable=False)
    reference = Column(String(18), nullable=True)
    disputed = Column(Boolean, nullable=False)
'''

P_DB = '''from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SessionLocal = sessionmaker(bind=create_engine("postgresql://payments-db/payments"))
'''

P_REPOSITORY = '''from app.models import AccountRecord, PaymentRecord


def load_account(session, account_id):
    return session.query(AccountRecord).filter(AccountRecord.id == account_id).one_or_none()


def load_payments(session, account_id):
    return session.query(PaymentRecord).filter(PaymentRecord.account_id == account_id).all()


def load_payment(session, payment_id):
    return session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).one_or_none()


def save_payment(session, record):
    session.add(record)
    session.commit()
'''

P_EVENTS = '''from kafka import KafkaProducer

TOPIC = "payments.created"
producer = KafkaProducer(bootstrap_servers="kafka:9092")


def publish_created(record):
    producer.send(TOPIC, {"payment_id": record.id, "account_id": record.account_id, "amount": float(record.amount)})
'''

P_SERVICES = '''import os

from app.events import publish_created
from app.models import PaymentRecord
from app.repositories.payments import load_account, load_payment, load_payments, save_payment

MIN_BALANCE = float(os.getenv("MIN_BALANCE", "80"))
RATES = {"EUR": 1.0, "USD": 1.08, "GBP": 0.86}


class PaymentRefused(Exception):
    pass


def balance_of(account):
    """The balance a payment can use."""
    return float(account.balance)


def can_pay(account, amount):
    return balance_of(account) - amount >= MIN_BALANCE


def fee_for(amount):
    return round(amount * 0.01, 2)


def convert(amount, currency):
    return round(amount * RATES[currency], 2)


def create_payment(session, req):
    account = load_account(session, req.account_id)
    if account is None:
        raise LookupError("unknown account")
    if not can_pay(account, req.amount + fee_for(req.amount)):
        raise PaymentRefused("insufficient balance")
    record = PaymentRecord(id=f"P{req.reference}", account_id=req.account_id, amount=req.amount, currency=req.currency,
                           status="PENDING", reference=req.reference, disputed=False)
    save_payment(session, record)
    publish_created(record)
    return record


def list_payments(session, account_id):
    return [{"payment_id": p.id, "amount": float(p.amount), "status": p.status, "disputed": p.disputed}
            for p in load_payments(session, account_id)]


def account_balance(session, account_id):
    account = load_account(session, account_id)
    if account is None:
        raise LookupError("unknown account")
    return {"account_id": account_id, "balance": balance_of(account), "currency": account.currency}


def held_amount(account):
    return float(account.held) if os.getenv("HOLDS_ENABLED") == "true" else 0.0


def refund_payment(session, payment_id):
    record = load_payment(session, payment_id)
    if record is None:
        raise LookupError("unknown payment")
    record.status = "REFUNDED"
    save_payment(session, record)
    return {"refunded": float(record.amount) - fee_for(float(record.amount))}


def exchange_rates():
    return {c: convert(1.0, c) for c in RATES}
'''

P_API = '''from typing import List

from fastapi import FastAPI, HTTPException

from app.db import SessionLocal
from app.schemas import Balance, Payment, PaymentRequest, PaymentRow
from app.services.payments import (PaymentRefused, account_balance, create_payment, exchange_rates, list_payments,
                                   refund_payment)
from app.repositories.payments import load_payment

app = FastAPI()


@app.post("/payments", response_model=Payment, status_code=201)
def api_create_payment(req: PaymentRequest):
    with SessionLocal() as session:
        try:
            record = create_payment(session, req)
        except LookupError:
            raise HTTPException(status_code=404, detail="unknown account")
        except PaymentRefused:
            raise HTTPException(status_code=409, detail="insufficient balance")
        return {"payment_id": record.id, "account_id": record.account_id, "amount": float(record.amount),
                "currency": record.currency, "status": record.status}


@app.get("/payments/{payment_id}", response_model=Payment)
def api_get_payment(payment_id: str):
    with SessionLocal() as session:
        record = load_payment(session, payment_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown payment")
        return record


@app.get("/accounts/{account_id}/payments", response_model=List[PaymentRow])
def api_list_payments(account_id: str):
    with SessionLocal() as session:
        return list_payments(session, account_id)


@app.get("/accounts/{account_id}/balance", response_model=Balance)
def api_balance(account_id: str):
    with SessionLocal() as session:
        try:
            return account_balance(session, account_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="unknown account")


@app.post("/payments/{payment_id}/refund")
def api_refund(payment_id: str):
    with SessionLocal() as session:
        try:
            return refund_payment(session, payment_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="unknown payment")


@app.get("/fx/rates")
def api_rates():
    return exchange_rates()
'''

P_TESTS = '''from fastapi.testclient import TestClient

from app.api.payments import app

client = TestClient(app)


def test_create_payment():
    r = client.post("/payments", json={"account_id": "ACC1001", "amount": 50, "currency": "EUR", "reference": "INV1"})
    assert r.status_code == 201
    assert r.json()["status"] == "PENDING"


def test_balance():
    r = client.get("/accounts/ACC1001/balance")
    assert r.status_code == 200
    assert r.json()["currency"] == "EUR"


def test_unknown_payment():
    r = client.get("/payments/NOPE")
    assert r.status_code == 404
'''

P_OPENAPI = '''openapi: 3.0.3
info: {title: Northwind payments API, version: "1.0"}
paths:
  /payments/{payment_id}:
    get:
      operationId: getPayment
      parameters:
        - {name: payment_id, in: path, required: true, schema: {type: string}}
      responses:
        "200":
          description: the payment
          content:
            application/json:
              example: {payment_id: PINV1, account_id: ACC1001, amount: 50.0, currency: EUR, status: PENDING}
        "404":
          description: unknown payment
          content:
            application/json:
              example: {detail: unknown payment}
'''

P_MIGRATION = '''import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table(
        "payments",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("account_id", sa.String(12), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("reference", sa.String(18), nullable=True),
        sa.Column("disputed", sa.Boolean, nullable=False),
    )


def downgrade():
    op.drop_table("payments")
'''

P_DROP_REFERENCE = '''from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_column("reference")


def downgrade():
    pass
'''

P_SERVICE_YAML = ("service: payments-api\nowner: team-payments\ncriticality: critical\ndatabase: payments-db\n"
                  "entry_points:\n  POST /payments: Make a payment\n  GET /accounts/{account_id}/balance: Account balance\n"
                  "  GET /accounts/{account_id}/payments: Payment history\n  POST /payments/{payment_id}/refund: Refund a payment\n")

# ---- consumers ----------------------------------------------------------------------------------------------------------------------
CLIENT = '''import os

import requests

PAYMENTS_BASE_URL = os.getenv("PAYMENTS_BASE_URL", "http://payments-api")


def fetch_payments(account_id: str):
    return requests.get(f"{PAYMENTS_BASE_URL}/accounts/{account_id}/payments", timeout=5).json()
'''

STATEMENT_APP = '''from fastapi import FastAPI

from client import fetch_payments

app = FastAPI()


def statement_rows(account_id):
    """Disputed payments are left out of the statement."""
    return [p for p in fetch_payments(account_id) if not p["disputed"]]


def render_pdf(rows):
    return b"%PDF " + str(len(rows)).encode()


@app.get("/statements/{account_id}/pdf")
def statement_pdf(account_id: str):
    return render_pdf(statement_rows(account_id))
'''

STATEMENT_CONSUMER = '''from kafka import KafkaConsumer


def poll():
    consumer = KafkaConsumer("payments.created", group_id="statements")
    for msg in consumer:
        remember(msg.value)


def remember(event):
    return event
'''

STATEMENT_TEST = '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_statement_pdf():
    r = client.get("/statements/ACC1001/pdf")
    assert r.status_code == 200
'''

MOBILE_APP = '''from fastapi import FastAPI

from client import fetch_payments
from repository import recent_references

app = FastAPI()


def activity(account_id):
    """Every payment of the account, newest first."""
    return sorted(fetch_payments(account_id), key=lambda p: p["payment_id"], reverse=True)


@app.get("/mobile/accounts/{account_id}/activity")
def mobile_activity(account_id: str):
    return {"items": activity(account_id), "references": recent_references(account_id)}
'''

MOBILE_MODELS = '''from sqlalchemy import Column, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PaymentView(Base):
    __tablename__ = "payments"
    id = Column(String(20), primary_key=True)
    account_id = Column(String(12), nullable=False)
    reference = Column(String(18), nullable=True)
'''

MOBILE_REPOSITORY = '''from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import PaymentView

SessionLocal = sessionmaker(bind=create_engine("postgresql://payments-db/payments"))


def recent_references(account_id):
    with SessionLocal() as session:
        return [p.reference for p in session.query(PaymentView).filter(PaymentView.account_id == account_id).all()]
'''

# ---- web-portal (React) --------------------------------------------------------------------------------------------------------------
W_APP = '''import { BrowserRouter, Routes, Route } from "react-router-dom";
import Login from "./Login";
import Accounts from "./Accounts";
import Pay from "./Pay";
import Done from "./Done";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/accounts" element={<Accounts />} />
        <Route path="/pay" element={<Pay />} />
        <Route path="/done" element={<Done />} />
      </Routes>
    </BrowserRouter>
  );
}
'''

W_LOGIN = '''import { useState } from "react";
import { useNavigate } from "react-router-dom";

export default function Login() {
  const navigate = useNavigate();
  const [user, setUser] = useState("");
  const signIn = () => navigate("/accounts");
  return (
    <form onSubmit={e => { e.preventDefault(); signIn(); }}>
      <label htmlFor="username">User name</label>
      <input id="username" name="username" required minLength={3} maxLength={30} onChange={e => setUser(e.target.value)} />
      <label htmlFor="password">Password</label>
      <input id="password" name="password" type="password" required minLength={8} />
      <button type="submit" data-testid="sign-in">Sign in</button>
    </form>
  );
}
'''

W_ACCOUNTS = '''import { useEffect, useState } from "react";
import axios from "axios";

export default function Accounts() {
  const [account, setAccount] = useState("ACC1001");
  const [balance, setBalance] = useState(null);
  const [payments, setPayments] = useState([]);
  useEffect(() => {
    axios.get(`/accounts/${account}/balance`).then(r => setBalance(r.data));
    axios.get(`/accounts/${account}/payments`).then(r => setPayments(r.data));
  }, [account]);
  return (
    <main>
      <label htmlFor="account">Account</label>
      <select id="account" name="account" value={account} onChange={e => setAccount(e.target.value)}>
        <option value="ACC1001">ACC1001</option>
        <option value="ACC2002">ACC2002</option>
      </select>
      <a href="/pay" data-testid="make-payment">Make a payment</a>
    </main>
  );
}
'''

W_PAY = '''import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";

export default function Pay() {
  const navigate = useNavigate();
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [reference, setReference] = useState("");
  const pay = () => axios.post("/payments", { account_id: "ACC1001", amount, currency, reference }).then(() => navigate("/done"));
  return (
    <form onSubmit={e => { e.preventDefault(); pay(); }}>
      <label htmlFor="amount">Amount</label>
      <input id="amount" name="amount" type="number" required min="0.01" max="10000" onChange={e => setAmount(e.target.value)} />
      <label htmlFor="currency">Currency</label>
      <select id="currency" name="currency" required value={currency} onChange={e => setCurrency(e.target.value)}>
        <option value="EUR">EUR</option>
        <option value="USD">USD</option>
        <option value="GBP">GBP</option>
      </select>
      <label htmlFor="reference">Reference</label>
      <input id="reference" name="reference" required maxLength={18} onChange={e => setReference(e.target.value)} />
      <button type="submit" data-testid="pay">Pay</button>
    </form>
  );
}
'''

W_DONE = '''export default function Done() {
  return (
    <main>
      <h1>Payment sent</h1>
      <a href="/accounts" data-testid="back">Back to accounts</a>
    </main>
  );
}
'''

# ---- the testers' regression suite --------------------------------------------------------------------------------------------------
SUITE = '''ID,Title,Entry point,Steps,Expected Result,Priority
NW-01,Create a payment,POST /payments,"Pay 50 EUR from account ACC1001 with reference INV1",The payment is created with status PENDING,High
NW-02,Payment refused below the minimum balance,POST /payments,Pay 450 EUR from ACC1001 (balance 500),Refused: 409 insufficient balance,High
NW-03,Pay screen rejects an amount above the limit,/pay,"Open the Pay screen, enter 20000 and press Pay",The amount field shows an error,Medium
NW-04,View a payment,GET /payments/{payment_id},Open payment PINV1,The payment details are shown,Medium
NW-05,Unknown payment,GET /payments/{payment_id},Open payment NOPE,404 unknown payment,Low
NW-06,Payment history,GET /accounts/{account_id}/payments,Open the payments of ACC1001,Every payment is listed with its status,High
NW-07,Account balance,GET /accounts/{account_id}/balance,Open the balance of ACC1001,The balance and currency are shown,High
NW-08,Accounts screen shows the balance,/accounts,Sign in and open Accounts,The balance of the chosen account is shown,Medium
NW-09,Refund a payment,POST /payments/{payment_id}/refund,Refund payment PINV1,The payment is REFUNDED; the fee is kept,High
NW-10,Exchange rates,GET /fx/rates,Open the exchange rates,EUR USD and GBP are listed,Low
NW-11,Statement leaves out disputed payments,GET /statements/{account_id}/pdf,Dispute a payment then download the statement,The disputed payment is not in the PDF,High
NW-12,Mobile activity shows every payment,GET /mobile/accounts/{account_id}/activity,Open the activity of ACC1001 in the app,Every payment is listed newest first,Medium
NW-13,Sign in,/login,Enter user name and password and press Sign in,The Accounts screen opens,Medium
NW-14,Archive export reaches the archive,,Export last month's statements,The archive receives the file,Low
'''

# scenario -> (branch, what changes in payments-api)
SCENARIOS = [
    ("feature/holds", "balance_of() subtracts held amounts when the new environment variable HOLDS_ENABLED is true"),
    ("feature/min-balance", "config/app.env raises MIN_BALANCE from 80 to 100 (configuration only)"),
    ("feature/fee-change", "fee_for() charges 1.5% instead of 1% (logic change)"),
    ("feature/remove-disputed", "the `disputed` field is removed from PaymentRow, the response of the shared endpoint (breaking contract)"),
    ("feature/drop-reference", "an Alembic migration drops the payments.reference column that mobile-bff still reads (breaking data change)"),
    ("docs/clarify", "a docstring is reworded (no functional change)"),
]


# What TIA must answer for each scenario (docs/SHOWCASE.md; tests/test_showcase.py checks every value, through git and through zip uploads)
EXPECTED = {
    "feature/holds": {"status": "complete_with_gaps", "change_type": "implementation_change", "selected": ["NW-01", "NW-02", "NW-03", "NW-07", "NW-08"],
                      "entry_points": ["GET /accounts/{account_id}/balance", "POST /payments"],
                      "see": "Regression-test 5 of your 14. Configuration: balance_of now reads HOLDS_ENABLED, no file sets it (set it in Dev); "
                             "held_amount already reads the same key."},
    "feature/min-balance": {"status": "complete_with_gaps", "change_type": "config_or_file_change", "selected": ["NW-01", "NW-02", "NW-03"],
                            "entry_points": ["POST /payments"],
                            "see": "Regression-test 3 of your 14. Configuration: MIN_BALANCE changes value in config/app.env, read by can_pay. "
                                   "No value is shown."},
    "feature/fee-change": {"status": "complete_with_gaps", "change_type": "implementation_change",
                           "selected": ["NW-01", "NW-02", "NW-03", "NW-09"], "entry_points": ["POST /payments", "POST /payments/{payment_id}/refund"],
                           "see": "Regression-test 4 of your 14: making a payment and refunding one (both charge the fee)."},
    "feature/remove-disputed": {"status": "complete_with_gaps", "change_type": "api_change", "selected": ["NW-06", "NW-08", "NW-11", "NW-12"],
                                "entry_points": ["GET /accounts/{account_id}/payments", "GET /mobile/accounts/{account_id}/activity",
                                                 "GET /statements/{account_id}/pdf"],
                                "see": "BREAKING: PaymentRow.disputed removed. Critical finding on statement-service, high on mobile-bff. A rule gap "
                                       "(statement-service leaves out disputed payments, mobile-bff does not) and a consistency check. "
                                       "Regression-test 4 of your 14."},
    "feature/drop-reference": {"status": "partial", "change_type": "data_change",
                               "selected": ["NW-04", "NW-05", "NW-06", "NW-08", "NW-09", "NW-12"],
                               "entry_points": ["GET /accounts/{account_id}/payments", "GET /mobile/accounts/{account_id}/activity",
                                                "GET /payments/{payment_id}", "POST /payments/{payment_id}/refund"],
                               "see": "BREAKING data change: column payments.reference dropped while payments-api and mobile-bff (same database) "
                                      "still map it. Status PARTIAL on purpose: the walk reaches the depth limit (8), stated under Unknowns; "
                                      "raise max_depth in section 6 to follow it further. Regression-test 6 of your 14."},
    "docs/clarify": {"status": "complete_with_gaps", "change_type": "no_functional_change", "selected": [], "entry_points": [],
                     "see": "Documentation only: nothing to retest (Regression-test 0 of your 14)."},
}
UNMAPPED = ["NW-14"]                    # names nothing TIA can match: always listed for review by hand


def payments_files(**over) -> dict:
    files = {"app/__init__.py": "", "app/api/__init__.py": "", "app/services/__init__.py": "", "app/repositories/__init__.py": "",
             "app/api/payments.py": P_API, "app/services/payments.py": P_SERVICES, "app/repositories/payments.py": P_REPOSITORY,
             "app/models.py": P_MODELS, "app/schemas.py": P_SCHEMAS, "app/db.py": P_DB, "app/events.py": P_EVENTS,
             "alembic/versions/0001_init.py": P_MIGRATION, "openapi.yaml": P_OPENAPI, "tests/test_api.py": P_TESTS,
             "config/app.env": "MIN_BALANCE=80\nFX_PROVIDER=ecb\n", "tia-services.yaml": P_SERVICE_YAML, "README.md": "# payments-api\n"}
    files.update(over)
    return files


def scenario_files(branch: str) -> dict:
    """The files of payments-api that a scenario branch changes or adds."""
    if branch == "feature/holds":
        return {"app/services/payments.py": P_SERVICES.replace(
            '    """The balance a payment can use."""\n    return float(account.balance)',
            '    """The balance a payment can use."""\n    if os.getenv("HOLDS_ENABLED", "false") == "true":\n'
            '        return float(account.balance) - float(account.held)\n    return float(account.balance)')}
    if branch == "feature/min-balance":
        return {"config/app.env": "MIN_BALANCE=100\nFX_PROVIDER=ecb\n"}
    if branch == "feature/fee-change":
        return {"app/services/payments.py": P_SERVICES.replace("round(amount * 0.01, 2)", "round(amount * 0.015, 2)")}
    if branch == "feature/remove-disputed":
        return {"app/schemas.py": P_SCHEMAS.replace("    status: str\n    disputed: bool\n", "    status: str\n"),
                "app/services/payments.py": P_SERVICES.replace(', "disputed": p.disputed}', "}")}
    if branch == "feature/drop-reference":
        return {"alembic/versions/0002_drop_reference.py": P_DROP_REFERENCE}
    if branch == "docs/clarify":
        return {"app/services/payments.py": P_SERVICES.replace('"""The balance a payment can use."""',
                                                              '"""The balance a payment can use, in the account currency."""')}
    raise KeyError(branch)


REPOS = {
    "payments-api": payments_files(),
    "statement-service": {"client.py": CLIENT, "app.py": STATEMENT_APP, "consumer.py": STATEMENT_CONSUMER, "tests/test_statement.py": STATEMENT_TEST,
                          "tia-services.yaml": "service: statement-service\nowner: team-statements\ncriticality: critical\n"
                                               "config_keys:\n  PAYMENTS_BASE_URL: payments-api\n"
                                               "entry_points:\n  GET /statements/{account_id}/pdf: Monthly statement PDF\n"},
    "mobile-bff": {"client.py": CLIENT, "app.py": MOBILE_APP, "models.py": MOBILE_MODELS, "repository.py": MOBILE_REPOSITORY,
                   "tia-services.yaml": "service: mobile-bff\nowner: team-mobile\ndatabase: payments-db\n"
                                        "config_keys:\n  PAYMENTS_BASE_URL: payments-api\n"
                                        "entry_points:\n  GET /mobile/accounts/{account_id}/activity: Mobile activity\n"},
    "web-portal": {"src/App.jsx": W_APP, "src/Login.jsx": W_LOGIN, "src/Accounts.jsx": W_ACCOUNTS, "src/Pay.jsx": W_PAY, "src/Done.jsx": W_DONE,
                   "package.json": '{"name": "web-portal", "private": true}\n', "tia-services.yaml": "service: web-portal\nowner: team-web\n"},
    "qa-testcases": {"testcases/regression-suite.csv": SUITE, "README.md": "# Northwind regression suite\n",
                     "tia-services.yaml": "service: qa-testcases\nowner: team-qa\n"},
}


def build(dest: str) -> dict:
    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True)
    out = {"paths": {}, "shas": {}, "target": "payments-api"}
    for name, files in REPOS.items():
        p = root / name
        p.mkdir(parents=True, exist_ok=True)
        _run(p, "init", "-q", "-b", "main")
        _write(p, files)
        out["paths"][name] = str(p)
        sha = _commit(p, "initial")
        if name == "payments-api":
            out["shas"]["base"] = sha
    p = root / "payments-api"
    for branch, _ in SCENARIOS:
        _run(p, "checkout", "-q", "-b", branch, out["shas"]["base"])
        _write(p, scenario_files(branch))
        out["shas"][branch] = _commit(p, branch)
    _run(p, "checkout", "-q", "main")
    return out


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(build(sys.argv[1]), indent=2))
