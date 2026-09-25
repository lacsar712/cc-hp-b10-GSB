import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from rules import judge, location_hint, valid_location, valid_warehouse

SECRET = os.environ.get("JWT_SECRET", "herb-process-dev-secret")
DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54393/herb")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "processor": {"role": "writer", "password_hash": pwd.hash("herb123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class StepIn(BaseModel):
    name: str
    temp_c: float
    minutes: float


class BatchIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    steps: list[StepIn]
    location_code: str = Field(min_length=1, max_length=40)


class LocationIn(BaseModel):
    location_code: str = Field(min_length=1, max_length=40)


class RuleIn(BaseModel):
    warehouse_name: str = Field(min_length=1, max_length=12)
    shelf_digits: int = Field(default=2, ge=1, le=4)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅炮制员可写入记录")
    return user


app = FastAPI(title="饮片炮制记录台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batches (
                id serial PRIMARY KEY,
                herb text NOT NULL,
                doc jsonb NOT NULL,
                verdict text NOT NULL,
                reason text NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        conn.execute("ALTER TABLE batches ADD COLUMN IF NOT EXISTS location_code text")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS location_rules (
                id serial PRIMARY KEY,
                warehouse_name text NOT NULL,
                shelf_digits int NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS location_ledger (
                id serial PRIMARY KEY,
                batch_id int NOT NULL REFERENCES batches(id),
                location_code text NOT NULL,
                action text NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        rule_count = conn.execute("SELECT COUNT(*) AS n FROM location_rules").fetchone()["n"]
        if rule_count == 0:
            conn.execute(
                """INSERT INTO location_rules (warehouse_name, shelf_digits, created_by, created_at)
                   VALUES (%s, %s, %s, %s)""",
                ("甲仓", 2, "processor", datetime.now(timezone.utc)),
            )
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("甘草", {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
            ]
            for herb, doc in samples:
                verdict, reason = judge(doc)
                conn.execute(
                    """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
                       VALUES (%s, %s::jsonb, %s, %s, %s, %s)""",
                    (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, "processor", now),
                )
        conn.commit()


def current_rule(conn) -> dict:
    return conn.execute(
        "SELECT warehouse_name, shelf_digits, created_by, created_at FROM location_rules ORDER BY id DESC LIMIT 1"
    ).fetchone()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "herb-process-record"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/batches")
def list_batches(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, herb, doc, verdict, reason, location_code, created_by FROM batches ORDER BY id DESC"
        ).fetchall()
    return rows


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, user: dict = Depends(require_writer)):
    doc = {"steps": [s.model_dump() for s in body.steps]}
    verdict, reason = judge(doc)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        rule = current_rule(conn)
        code = body.location_code.strip()
        if not valid_location(code, rule):
            raise HTTPException(status_code=400, detail=f"货位码格式不符，应为 {location_hint(rule)} 形式")
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, location_code, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, location_code, created_by""",
            (body.herb.strip(), json.dumps(doc, ensure_ascii=False), verdict, reason, code, user["username"], now),
        ).fetchone()
        conn.execute(
            """INSERT INTO location_ledger (batch_id, location_code, action, created_by, created_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (row["id"], code, "写入", user["username"], now),
        )
        conn.commit()
    return row


@app.patch("/api/batches/{batch_id}/location")
def correct_location(batch_id: int, body: LocationIn, user: dict = Depends(require_writer)):
    """事后改正某行货位码：只追加一条改正流水，早先流水不改写。"""
    now = datetime.now(timezone.utc)
    with connect() as conn:
        rule = current_rule(conn)
        code = body.location_code.strip()
        if not valid_location(code, rule):
            raise HTTPException(status_code=400, detail=f"货位码格式不符，应为 {location_hint(rule)} 形式")
        row = conn.execute(
            """UPDATE batches SET location_code = %s
               WHERE id = %s
               RETURNING id, herb, doc, verdict, reason, location_code, created_by""",
            (code, batch_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="记录不存在")
        conn.execute(
            """INSERT INTO location_ledger (batch_id, location_code, action, created_by, created_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (batch_id, code, "改正", user["username"], now),
        )
        conn.commit()
    return row


@app.get("/api/location/rule")
def get_rule(_user: dict = Depends(current_user)):
    with connect() as conn:
        rule = current_rule(conn)
    rule["example"] = location_hint(rule)
    return rule


@app.put("/api/location/rule")
def set_rule(body: RuleIn, user: dict = Depends(require_writer)):
    """炮制员设定货位规则；变更仅约束后续提交，历史记录不追溯。"""
    warehouse = body.warehouse_name.strip()
    if not valid_warehouse(warehouse):
        raise HTTPException(status_code=400, detail="仓名须为汉字")
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO location_rules (warehouse_name, shelf_digits, created_by, created_at)
               VALUES (%s, %s, %s, %s)
               RETURNING warehouse_name, shelf_digits, created_by, created_at""",
            (warehouse, body.shelf_digits, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    row["example"] = location_hint(row)
    return row


@app.get("/api/location/ledger")
def list_ledger(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            """SELECT l.id, l.batch_id, b.herb, l.location_code, l.action, l.created_by, l.created_at
               FROM location_ledger l JOIN batches b ON b.id = l.batch_id
               ORDER BY l.id DESC"""
        ).fetchall()
    return rows
