# -*- coding: utf-8 -*-
"""会员账号与 Stripe 支付回归测试。

运行方式（必须用项目虚拟环境）：
    .venv\Scripts\python.exe tests\test_membership.py
"""

import os
import sys
import time
import uuid
import json
import hmac
import hashlib
import tempfile

DB_PATH = os.path.join(tempfile.gettempdir(), "hj_membership_test_%s.db" % uuid.uuid4().hex)
os.environ["MEMBERSHIP_DB"] = DB_PATH
os.environ["APP_SECRET_KEY"] = "test-app-secret"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_placeholder_for_unittest"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_secret_for_unittest"
os.environ["STRIPE_PRICE_LIFETIME"] = ""

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import app as app_module                    # noqa: E402
import membership                           # noqa: E402
import payments                             # noqa: E402
import summarizer                           # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  PASS  %s" % name)
    else:
        FAILED.append(name)
        print("  FAIL  %s %s" % (name, detail))


def raises(func):
    try:
        func()
        return False
    except membership.MembershipError:
        return True


def sign(payload, secret=None, ts=None):
    """按 Stripe 规范构造 Stripe-Signature 头。"""
    secret = secret or payments.WEBHOOK_SECRET
    stamp = ts or int(time.time())
    signed = ("%d." % stamp).encode("utf-8") + payload.encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), msg=signed, digestmod=hashlib.sha256).hexdigest()
    return "t=%d,v1=%s" % (stamp, mac)


def make_event(order_id, session_id, amount=10000, event_id=None):
    return json.dumps({
        "id": event_id or ("evt_%s" % uuid.uuid4().hex[:12]),
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "client_reference_id": order_id,
            "amount_total": amount,
            "currency": "cny",
            "payment_intent": "pi_test_intent",
            "payment_status": "paid",
        }},
    })


def login_session(client, user_id, csrf="token-A"):
    with client.session_transaction() as sess:
        sess["uid"] = user_id
        sess["csrf"] = csrf
    return csrf


def current_csrf(client):
    """读取当前会话里的 CSRF Token。

    登录成功后服务端会轮换 Token（防会话固定），因此不能沿用旧值。
    """
    with client.session_transaction() as sess:
        return sess.get("csrf", "")


def run():
    client = app_module.app.test_client()
    membership.init_db()

    print("\n[1] 数据层：密码哈希与邮箱唯一")
    user_a = membership.create_user("Alice@Example.com", "abcd12345")
    check("邮箱归一化为小写", user_a["email"] == "alice@example.com")
    check("同一密码可校验通过", membership.verify_user("alice@example.com", "abcd12345")["id"] == user_a["id"])
    check("错误密码被拒绝", raises(lambda: membership.verify_user("alice@example.com", "bad-password")))
    check("重复邮箱被拒绝", raises(lambda: membership.create_user("ALICE@example.com", "abcd12345")))
    check("弱密码被拒绝", raises(lambda: membership.create_user("bob@example.com", "123")))
    check("非法邮箱被拒绝", raises(lambda: membership.create_user("not-an-email", "abcd12345")))

    print("\n[2] CSRF 守卫")
    r = client.post("/api/auth/register", json={"email": "csrf@example.com", "password": "abcd12345"})
    check("缺 CSRF Token → 403", r.status_code == 403, r.get_data(as_text=True))
    with client.session_transaction() as sess:
        sess["csrf"] = "token-A"
    r = client.post("/api/auth/register", json={"email": "carol@example.com", "password": "abcd12345"},
                    headers={"X-CSRF-Token": "token-A"})
    check("带正确 Token → 200", r.status_code == 200, r.get_data(as_text=True))

    print("\n[3] 登录态与登出")
    check("登录后 CSRF Token 已轮换", current_csrf(client) != "token-A")
    client.post("/api/auth/logout", json={}, headers={"X-CSRF-Token": current_csrf(client)})
    check("登出后 /api/me 未登录", client.get("/api/me").get_json()["logged_in"] is False)
    r = client.post("/api/auth/login", json={"email": "carol@example.com", "password": "wrong"},
                    headers={"X-CSRF-Token": current_csrf(client)})
    check("密码错误 → 400", r.status_code == 400, r.get_data(as_text=True))
    r = client.get("/api/me")
    check("初始为免费版", r.get_json()["is_member"] is False)

    print("\n[4] 下单幂等：重复点击只产生一个 Checkout Session")
    calls = []

    def fake_ensure(order, email, base_url):
        # 必须与真实实现一致：已有 Session 时原样复用，不产生新调用
        if order.get("stripe_session_id") and order.get("checkout_url"):
            return order["stripe_session_id"], order["checkout_url"]
        calls.append(order["id"])
        return ("cs_fake_%s" % order["id"][:8], "https://checkout.stripe.test/%s" % order["id"])

    real_ensure = payments.ensure_checkout_session
    payments.ensure_checkout_session = fake_ensure
    try:
        csrf = login_session(client, user_a["id"])
        r1 = client.post("/api/checkout", json={"plan": "lifetime"}, headers={"X-CSRF-Token": csrf})
        check("首次下单 200", r1.status_code == 200, r1.get_data(as_text=True))
        order_id = r1.get_json()["order_id"]

        r2 = client.post("/api/checkout", json={"plan": "lifetime"}, headers={"X-CSRF-Token": csrf})
        check("重复下单返回同一订单", r2.get_json()["order_id"] == order_id)
        check("重复下单未再次调用 Stripe", len(calls) == 1, "实际调用 %d 次" % len(calls))

        order = membership.get_order(order_id)
        check("金额取自服务端价源", order["amount"] == payments.PLANS["lifetime"]["amount"])
        check("订单尚未支付", order["status"] == membership.ORDER_PENDING)
    finally:
        payments.ensure_checkout_session = real_ensure

    session_id = "cs_fake_%s" % order_id[:8]

    print("\n[5] 订单越权访问")
    r = client.get("/api/order/%s" % order_id)
    check("本人可查订单", r.status_code == 200 and r.get_json()["status"] == "pending")
    other = membership.create_user("other@example.com", "abcd12345")
    login_session(client, other["id"])
    r = client.get("/api/order/%s" % order_id)
    check("他人订单 → 404", r.status_code == 404)
    anon = app_module.app.test_client()
    with anon.session_transaction() as sess:
        sess["csrf"] = "t-anon"
    check("未登录查订单 → 401", anon.get("/api/order/%s" % order_id).status_code == 401)

    print("\n[6] Webhook 验签与拒绝发货")
    payload = make_event(order_id, session_id)
    r = client.post("/api/stripe/webhook", data=payload,
                    headers={"Stripe-Signature": "t=%d,v1=deadbeef" % int(time.time()),
                             "Content-Type": "application/json"})
    check("错误签名 → 400", r.status_code == 400, r.get_data(as_text=True))
    check("错误签名不发货", membership.get_order(order_id)["status"] == membership.ORDER_PENDING)
    r = client.post("/api/stripe/webhook", data=payload)
    check("缺少签名头 → 400", r.status_code == 400)

    login_session(client, user_a["id"])

    print("\n[7] 金额异常：宁可不发货")
    bad = make_event(order_id, session_id, amount=1)
    r = client.post("/api/stripe/webhook", data=bad,
                    headers={"Stripe-Signature": sign(bad), "Content-Type": "application/json"})
    check("金额不匹配时返回 200 但标记异常", r.status_code == 200 and r.get_json().get("amount_mismatch") is True)
    check("金额不匹配不发会员", membership.is_member(user_a["id"]) is False)

    print("\n[8] 正常发货与事件重投幂等")
    good = make_event(order_id, session_id, event_id="evt_first")
    r = client.post("/api/stripe/webhook", data=good,
                    headers={"Stripe-Signature": sign(good), "Content-Type": "application/json"})
    check("合法签名 → 200", r.status_code == 200, r.get_data(as_text=True))
    check("首次发货 granted=True", r.get_json().get("granted") is True)
    check("会员已开通", membership.is_member(user_a["id"]) is True)

    paid_before = membership.get_order(order_id)["paid_at"]
    r = client.post("/api/stripe/webhook", data=good,
                    headers={"Stripe-Signature": sign(good), "Content-Type": "application/json"})
    check("同一事件重投 granted=False", r.get_json().get("granted") is False)
    check("重投未改动 paid_at", membership.get_order(order_id)["paid_at"] == paid_before)

    another = make_event(order_id, session_id, event_id="evt_second")
    r = client.post("/api/stripe/webhook", data=another,
                    headers={"Stripe-Signature": sign(another), "Content-Type": "application/json"})
    check("不同事件重发同一订单 granted=False", r.get_json().get("granted") is False)
    check("会员记录仍只有一条", _membership_count(user_a["id"]) == 1)

    print("\n[9] 已是会员时禁止重复购买")
    login_session(client, user_a["id"])
    r = client.post("/api/checkout", json={"plan": "lifetime"}, headers={"X-CSRF-Token": "token-A"})
    check("已付费再下单 → 409", r.status_code == 409, r.get_data(as_text=True))

    print("\n[10] AI 总结接口的会员鉴权")
    real_run = summarizer.run_summary
    summarizer.run_summary = lambda job, url: job.update({"stage": "done"})
    try:
        r = anon.post("/api/summarize", json={"url": "https://example.com/v"})
        check("未登录 → 401", r.status_code == 401)
        check("错误码为 login_required", r.get_json().get("code") == "login_required")

        login_session(client, other["id"])
        r = client.post("/api/summarize", json={"url": "https://example.com/v"})
        check("免费用户 → 403", r.status_code == 403)
        check("错误码为 membership_required", r.get_json().get("code") == "membership_required")

        r = client.get("/api/summary/subtitle/deadbeef01")
        check("字幕接口同样被拦截", r.status_code == 403)

        login_session(client, user_a["id"])
        r = client.post("/api/summarize", json={"url": "https://example.com/v"})
        check("会员放行 → 200", r.status_code == 200, r.get_data(as_text=True))
        check("返回 job_id", bool(r.get_json().get("job_id")))
    finally:
        summarizer.run_summary = real_run

    print("\n[11] 页面可渲染（会员登录态）")
    for path in ("/", "/pricing", "/summarize", "/account", "/pay/success", "/faq"):
        check("GET %s → 200" % path, client.get(path).status_code == 200)
    pricing_html = client.get("/pricing").get_data(as_text=True)
    check("定价页显示已购态", "你已是终身会员" in pricing_html)
    check("定价页展示 100 元价格", ">100<" in pricing_html)

    print("\n[12] 密钥不回显")
    body = client.get("/api/me").get_data(as_text=True)
    check("响应中不含 any Stripe 密钥", "sk_test" not in body and "whsec" not in body)


def _membership_count(user_id):
    conn = membership.connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM memberships WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        run()
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(DB_PATH + suffix)
            except OSError:
                pass
    print("\n================ 结果：%d 通过 / %d 失败 ================" % (len(PASSED), len(FAILED)))
    sys.exit(1 if FAILED else 0)
