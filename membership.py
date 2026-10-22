# -*- coding: utf-8 -*-
"""会员账号与权益数据层（membership）。

职责边界：
  - 只负责本地数据（用户 / 会员 / 订单 / Webhook 事件），**不 import stripe**；
  - Stripe 相关逻辑全部在 payments.py，由 app.py 做中转注入，避免循环导入。

设计要点：
  - SQLite（标准库 sqlite3），库文件路径 data/hj.db，零新增 pip 依赖；
  - 每请求短连接 + WAL，避免 Flask 多线程下跨线程共享连接；
  - 所有 SQL 一律参数化绑定，禁止字符串拼接；
  - 订单状态跃迁与 Webhook 事件去重必须在一个事务内完成，保证幂等。
"""

import os
import re
import uuid
import time
import sqlite3
import threading
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("MEMBERSHIP_DB") or os.path.join(BASE_DIR, "data", "hj.db")

# ---- 可调项（均可用环境变量覆盖）----
MIN_PASSWORD = int(os.environ.get("MIN_PASSWORD", 8))
MAX_PASSWORD = int(os.environ.get("MAX_PASSWORD", 128))
ORDER_TTL = int(os.environ.get("ORDER_TTL", 24 * 3600))          # pending 订单有效期（秒）
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ORDER_PENDING = "pending"
ORDER_PAID = "paid"
ORDER_EXPIRED = "expired"
ORDER_FAILED = "failed"

# 需要处理的 Webhook 事件类型白名单（白名单外一律忽略，不发货）
SUPPORTED_EVENTS = (
    "checkout.session.completed",
    "checkout.session.expired",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
)

_schema_lock = threading.Lock()
_schema_ready = False


class MembershipError(Exception):
    """面向用户的可预期错误（文案可直接回显到前端）。"""


# ---------------------------------------------------------------- 连接与建表

def connect():
    """获取一个数据库连接（调用方负责关闭）。"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """建表与索引。幂等，可重复调用。"""
    global _schema_ready
    with _schema_lock:
        if _schema_ready:
            return
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            TEXT PRIMARY KEY,
                    email         TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at    REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memberships (
                    user_id            TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    plan               TEXT NOT NULL,
                    status             TEXT NOT NULL DEFAULT 'active',
                    source_order_id    TEXT,
                    source_session_id  TEXT,
                    granted_at         REAL NOT NULL,
                    expires_at         REAL            -- NULL = 终身会员
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id                    TEXT PRIMARY KEY,
                    user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    plan                  TEXT NOT NULL,
                    amount                INTEGER NOT NULL,
                    currency              TEXT NOT NULL,
                    status                TEXT NOT NULL DEFAULT 'pending',
                    stripe_session_id     TEXT,
                    stripe_payment_intent TEXT,
                    checkout_url          TEXT,
                    created_at            REAL NOT NULL,
                    paid_at               REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_session
                    ON orders(stripe_session_id) WHERE stripe_session_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_orders_user_plan
                    ON orders(user_id, plan, status);

                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id    TEXT PRIMARY KEY,
                    event_type  TEXT NOT NULL,
                    received_at REAL NOT NULL
                );
                """
            )
            conn.commit()
            _schema_ready = True
        finally:
            conn.close()


# ---------------------------------------------------------------- 用户

def normalize_email(raw):
    email = (raw or "").strip().lower()
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        raise MembershipError("邮箱格式不正确")
    return email


def create_user(email, password):
    """注册。邮箱已存在或密码不合规时抛 MembershipError。"""
    email = normalize_email(email)
    password = password or ""
    if len(password) < MIN_PASSWORD:
        raise MembershipError(f"密码至少需要 {MIN_PASSWORD} 位")
    if len(password) > MAX_PASSWORD:
        raise MembershipError(f"密码最长 {MAX_PASSWORD} 位")

    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise MembershipError("该邮箱已注册，请直接登录")
        user_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO users(id, email, password_hash, created_at) VALUES(?,?,?,?)",
            (user_id, email, generate_password_hash(password), time.time()),
        )
        conn.commit()
        return {"id": user_id, "email": email}
    except sqlite3.IntegrityError:
        raise MembershipError("该邮箱已注册，请直接登录")
    finally:
        conn.close()


def verify_user(email, password):
    """登录校验。成功返回 user dict，失败抛 MembershipError。

    不区分「邮箱不存在」与「密码错误」，避免账号枚举。
    """
    email = normalize_email(email)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    finally:
        conn.close()

    if not row:
        # 邮箱不存在时也执行一次同等开销的哈希校验，抹平时序差异
        check_password_hash("scrypt:32768:8:1$probe$probe", "probe-password")
        raise MembershipError("邮箱或密码不正确")
    if not check_password_hash(row["password_hash"], password or ""):
        raise MembershipError("邮箱或密码不正确")
    return {"id": row["id"], "email": row["email"]}


def get_user(user_id):
    if not user_id:
        return None
    conn = connect()
    try:
        row = conn.execute("SELECT id, email FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------- 会员

def is_member(user_id):
    """是否具备有效会员（终身或仍在有效期内）。"""
    if not user_id:
        return False
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM memberships WHERE user_id=? AND status='active' "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (user_id, time.time()),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_membership(user_id):
    if not user_id:
        return None
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM memberships WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------- 订单

def has_paid_order(user_id, plan):
    """是否已为某套餐付过款（幂等第一层：阻断重复购买）。"""
    if not user_id:
        return False
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM orders WHERE user_id=? AND plan=? AND status=?",
            (user_id, plan, ORDER_PAID),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def find_reusable_order(user_id, plan):
    """查找 24h 内可复用的 pending 订单（幂等第一层续：阻断重复下单）。

    同一个购买意图在支付完成前永远只对应一个 Checkout Session，
    用户反复点「立即开通」只会跳回同一个收银台，绝不会产生第二次扣款。
    """
    if not user_id:
        return None
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE user_id=? AND plan=? AND status=? "
            "AND created_at > ? ORDER BY created_at DESC LIMIT 1",
            (user_id, plan, ORDER_PENDING, time.time() - ORDER_TTL),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_order(user_id, plan, amount, currency):
    """创建新订单。调用方需已确认无 paid 订单且无可复用 pending 订单。"""
    order_id = uuid.uuid4().hex
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO orders(id, user_id, plan, amount, currency, status, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (order_id, user_id, plan, amount, currency, ORDER_PENDING, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    return order_id


def attach_session(order_id, session_id, checkout_url):
    """把 Stripe Checkout Session 回写到订单。"""
    conn = connect()
    try:
        conn.execute(
            "UPDATE orders SET stripe_session_id=?, checkout_url=? WHERE id=?",
            (session_id, checkout_url, order_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_order(order_id):
    if not order_id:
        return None
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def order_belongs_to(order_id, user_id):
    """订单归属校验。成功页轮询与兜底同步必须先过这一关，杜绝越权开通。"""
    if not order_id or not user_id:
        return False
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM orders WHERE id=? AND user_id=?", (order_id, user_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_order_by_session(session_id):
    if not session_id:
        return None
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE stripe_session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_expired(order_id):
    conn = connect()
    try:
        conn.execute(
            "UPDATE orders SET status=? WHERE id=? AND status=?",
            (ORDER_EXPIRED, order_id, ORDER_PENDING),
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(order_id):
    conn = connect()
    try:
        conn.execute(
            "UPDATE orders SET status=? WHERE id=? AND status=?",
            (ORDER_FAILED, order_id, ORDER_PENDING),
        )
        conn.commit()
    finally:
        conn.close()


def try_mark_paid(order_id, session_id=None, payment_intent=None, event_id=None):
    """发货唯一入口：事件去重 + 订单条件置 paid + 幂等开通会员，全在一个事务内。

    Returns:
        True  —— 本次为首次发货（会员已开通）
        False —— 已处理过（事件重投 / 订单非 pending），未做任何变更
    """
    conn = connect()
    try:
        with conn:
            if event_id:
                # 幂等第三层：同一个 Stripe 事件重复投递，直接跳过
                cur = conn.execute(
                    "INSERT OR IGNORE INTO webhook_events(event_id, event_type, received_at) "
                    "VALUES(?,?,?)",
                    (event_id, "checkout.session.completed", time.time()),
                )
                if cur.rowcount == 0:
                    return False

            # 幂等第四层：只有 pending → paid 的跃迁才发货
            cur = conn.execute(
                "UPDATE orders SET status=?, paid_at=?, stripe_session_id=?, "
                "stripe_payment_intent=? WHERE id=? AND status=?",
                (
                    ORDER_PAID,
                    time.time(),
                    session_id,
                    payment_intent,
                    order_id,
                    ORDER_PENDING,
                ),
            )
            if cur.rowcount == 0:
                return False

            row = conn.execute(
                "SELECT user_id, plan FROM orders WHERE id=?", (order_id,)
            ).fetchone()

            # 终身会员 expires_at 留空；重复开通走 DO NOTHING
            conn.execute(
                "INSERT OR IGNORE INTO memberships"
                "(user_id, plan, status, source_order_id, source_session_id, granted_at, expires_at) "
                "VALUES(?,?,'active',?,?,?,NULL)",
                (
                    row["user_id"],
                    row["plan"],
                    order_id,
                    session_id,
                    time.time(),
                ),
            )
        return True
    finally:
        conn.close()
