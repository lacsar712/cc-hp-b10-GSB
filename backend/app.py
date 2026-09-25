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

from rules import judge, normalize_location, validate_warehouse

SECRET = os.environ.get("JWT_SECRET", "herb-process-dev-secret")
DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54393/herb")
# 首次启用时的默认仓名规则
DEFAULT_WAREHOUSE = os.environ.get("DEFAULT_WAREHOUSE", "甲仓")
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
    # 入库货位码：新写强制，格式由炮制员设定的仓名规则约束（仓名/两位货架号）。
    location_code: str = Field(min_length=1, max_length=40)
    steps: list[StepIn]


class RuleIn(BaseModel):
    warehouse: str = Field(min_length=1, max_length=20)


class LocationFixIn(BaseModel):
    location_code: str = Field(min_length=1, max_length=40)


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
                location_code text,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        # 历史库可能缺列，幂等补齐
        cols = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'batches'"
        ).fetchall()}
        if "location_code" not in cols:
            conn.execute("ALTER TABLE batches ADD COLUMN location_code text")

        # 货位规则单行表（id 固定为 1）。炮制员可改，质检员只读。
        conn.execute(
            """CREATE TABLE IF NOT EXISTS location_rules (
                id int PRIMARY KEY DEFAULT 1,
                warehouse text NOT NULL,
                updated_by text NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT location_rules_singleton CHECK (id = 1)
            )"""
        )
        # 货位流水：只追加。新写一条记“写入”，事后改正记“改正”；
        # 早先那一条永不被改写或删除。
        conn.execute(
            """CREATE TABLE IF NOT EXISTS location_ledger (
                id serial PRIMARY KEY,
                batch_id int NOT NULL,
                herb text NOT NULL,
                action text NOT NULL,
                location_code text NOT NULL,
                operator text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )

        if conn.execute("SELECT COUNT(*) AS n FROM location_rules").fetchone()["n"] == 0:
            conn.execute(
                """INSERT INTO location_rules (id, warehouse, updated_by, updated_at)
                   VALUES (1, %s, %s, %s)""",
                (DEFAULT_WAREHOUSE, "processor", datetime.now(timezone.utc)),
            )

        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("甘草", {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}, "甲仓/01"),
                ("黄芩", {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}, "甲仓/02"),
            ]
            for herb, doc, code in samples:
                verdict, reason = judge(doc)
                row = conn.execute(
                    """INSERT INTO batches (herb, doc, verdict, reason, location_code, created_by, created_at)
                       VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, code, "processor", now),
                ).fetchone()
                conn.execute(
                    """INSERT INTO location_ledger
                           (batch_id, herb, action, location_code, operator, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (row["id"], herb, "写入", code, "processor", now),
                )
        conn.commit()


def get_rule(conn) -> dict:
    return conn.execute(
        "SELECT warehouse, updated_by, updated_at FROM location_rules WHERE id = 1"
    ).fetchone()


def enforce_location(conn, code: str) -> str:
    """按当前仓名规则校验并规范化货位码；不符则抛 422。"""
    try:
        normalized = normalize_location(code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    warehouse = get_rule(conn)["warehouse"]
    prefix = warehouse + "/"
    if not normalized.startswith(prefix):
        raise HTTPException(
            status_code=422,
            detail=f"货位码仓名须为「{warehouse}」，格式 {warehouse}/两位货架号，例如 {warehouse}/01",
        )
    return normalized


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
        # 货位码按“当前”规则强制校验，不符直接拒写（不落任何记录）。
        location_code = enforce_location(conn, body.location_code)
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, location_code, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, location_code, created_by""",
            (body.herb.strip(), json.dumps(doc, ensure_ascii=False), verdict, reason,
             location_code, user["username"], now),
        ).fetchone()
        # 货位码随写入进入货位流水
        conn.execute(
            """INSERT INTO location_ledger
                   (batch_id, herb, action, location_code, operator, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (row["id"], body.herb.strip(), "写入", location_code, user["username"], now),
        )
        conn.commit()
    return row


@app.get("/api/location/rule")
def get_location_rule(_user: dict = Depends(current_user)):
    with connect() as conn:
        rule = get_rule(conn)
    return rule


@app.put("/api/location/rule")
def update_location_rule(body: RuleIn, user: dict = Depends(require_writer)):
    try:
        warehouse = validate_warehouse(body.warehouse)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute(
            """UPDATE location_rules
                  SET warehouse = %s, updated_by = %s, updated_at = %s
                WHERE id = 1""",
            (warehouse, user["username"], now),
        )
        conn.commit()
        rule = get_rule(conn)
    # 规则变更仅约束后续提交：不触碰既有批次，也不回改流水。
    return rule


@app.get("/api/location/ledger")
def list_location_ledger(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, batch_id, herb, action, location_code, operator, created_at
                 FROM location_ledger
                ORDER BY id DESC"""
        ).fetchall()
    return rows


@app.put("/api/batches/{batch_id}/location")
def fix_batch_location(batch_id: int, body: LocationFixIn, user: dict = Depends(require_writer)):
    now = datetime.now(timezone.utc)
    with connect() as conn:
        batch = conn.execute(
            "SELECT id, herb, location_code FROM batches WHERE id = %s", (batch_id,)
        ).fetchone()
        if batch is None:
            raise HTTPException(status_code=404, detail="记录不存在")
        # 改正同样按当前规则校验，不符拒写。
        new_code = enforce_location(conn, body.location_code)
        if batch["location_code"] == new_code:
            raise HTTPException(status_code=422, detail="货位码与现值相同，无需改正")
        conn.execute(
            "UPDATE batches SET location_code = %s WHERE id = %s",
            (new_code, batch_id),
        )
        # 只追加一条“改正”流水；早先“写入”那条保持不变。
        conn.execute(
            """INSERT INTO location_ledger
                   (batch_id, herb, action, location_code, operator, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (batch_id, batch["herb"], "改正", new_code, user["username"], now),
        )
        conn.commit()
    return {"id": batch_id, "location_code": new_code}
