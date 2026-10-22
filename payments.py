# -*- coding: utf-8 -*-
"""Stripe 支付层（payments）。

职责边界：
  - 只负责与 Stripe 交互：**不直接读取 Flask 请求对象**，原始 body 与签名头由 app.py
    路由层以参数传入，便于单测直接构造输入；
  - 订单 / 会员落库由 membership.py 承担，本模块不写数据库。

幂等策略：
  - 创建 Checkout Session 时把服务端生成的 order_id 同时作为 Stripe 幂等键
    （idempotency_key）、client_reference_id 与 metadata，保证「同一份购买意图
    重复提交只可能产生一次扣款」。
"""

import os
import time
import stripe

from membership import MembershipError

# ---- 服务端唯一价源：金额只允许在这里定义，前端传什么价都无效 ----
CURRENCY = (os.environ.get("STRIPE_PRICE_LIFETIME_CURRENCY") or "cny").strip().lower()
AMOUNT = int(os.environ.get("STRIPE_PRICE_LIFETIME_AMOUNT") or 10000)   # 分 → ¥100.00

PLANS = {
    "lifetime": {
        "code": "lifetime",
        "name": "终身会员",
        "amount": AMOUNT,
        "currency": CURRENCY,
        "kind": "one_time",          # Checkout mode="payment"
        "expires_at": None,          # 终身会员，永不过期
    },
}

SESSION_TTL = int(os.environ.get("STRIPE_SESSION_TTL", 24 * 3600))
MAX_NETWORK_RETRIES = int(os.environ.get("STRIPE_MAX_NETWORK_RETRIES", 2))

SECRET_KEY = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
WEBHOOK_SECRET = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
PRICE_LIFETIME = (os.environ.get("STRIPE_PRICE_LIFETIME") or "").strip()
API_VERSION = (os.environ.get("STRIPE_API_VERSION") or "").strip() or None

_client = None


class PaymentsError(Exception):
    """面向用户的可预期支付错误（文案可直接回显，不含密钥/堆栈）。"""


def configured():
    return bool(SECRET_KEY)


def webhook_configured():
    return bool(WEBHOOK_SECRET)


def client():
    """惰性单例 StripeClient；未配置密钥时不初始化，避免 import 期报错。"""
    global _client
    if _client is None:
        if not SECRET_KEY:
            raise PaymentsError("支付服务未配置，请联系站长开通支付通道")
        kwargs = {"max_network_retries": MAX_NETWORK_RETRIES}
        if API_VERSION:
            kwargs["stripe_version"] = API_VERSION
        _client = stripe.StripeClient(SECRET_KEY, **kwargs)
    return _client


def get_plan(code):
    plan = PLANS.get((code or "").strip())
    if not plan:
        raise MembershipError("套餐不存在")
    return plan


def _line_item(plan):
    """优先用后台已建好的 Price ID；没配则按服务端金额临时生成价格数据。

    这样站长还没在 Dashboard 建产品时也能先把链路跑通。
    """
    price_id = PRICE_LIFETIME if plan["code"] == "lifetime" else ""
    if price_id:
        return {"price": price_id, "quantity": 1}
    return {
        "price_data": {
            "currency": plan["currency"],
            "unit_amount": plan["amount"],
            "product_data": {"name": f"HJ 视频下载 · {plan['name']}"},
        },
        "quantity": 1,
    }


def _absolute(base_url, path):
    return (base_url.rstrip("/") if base_url else "") + path


def ensure_checkout_session(order, email, base_url):
    """为订单创建（或复用）Stripe Checkout Session。

    Args:
        order: membership 订单字典，含 id / plan / amount / currency
        email: 用户邮箱，预填到收银台
        base_url: 站点地址，用于拼接 success_url / cancel_url
    Returns:
        (session_id, checkout_url)
    """
    plan = get_plan(order["plan"])
    if plan["amount"] != order["amount"] or plan["currency"] != order["currency"]:
        # 兜底：订单与服务端价源不一致时宁可失败，也不发出错误金额的账单
        raise PaymentsError("订单金额已失效，请重新下单")

    if order.get("stripe_session_id") and order.get("checkout_url"):
        # 幂等第一层：复用已有待支付 Session，重复点击绝不新建
        return order["stripe_session_id"], order["checkout_url"]

    success_url = _absolute(
        base_url, f"/pay/success?order={order['id']}&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = _absolute(base_url, "/pay/cancel")

    metadata = {"order_id": order["id"], "plan": plan["code"], "app": "hj-video-downloader"}

    try:
        session = client().checkout.sessions.create(
            {
                "mode": "payment",
                "line_items": [_line_item(plan)],
                "client_reference_id": order["id"],
                "customer_email": email,
                "metadata": metadata,
                "payment_intent_data": {"metadata": metadata},
                "success_url": success_url,
                "cancel_url": cancel_url,
                "expires_at": int(time.time()) + SESSION_TTL,
                "locale": "zh",
            },
            # 幂等第二层（Stripe 侧）：同一 order_id 只会被处理一次
            {"idempotency_key": order["id"]},
        )
    except stripe.StripeError as exc:
        raise PaymentsError(_friendly_stripe_error(exc))
    except Exception:
        raise PaymentsError("支付通道暂时不可用，请稍后重试")

    return session.id, session.url


def retrieve_session(session_id):
    """主动查询 Session 状态（webhook 未到达时成功页兜底同步用）。"""
    try:
        return client().checkout.sessions.retrieve(
            session_id, {"expand": ["payment_intent"]}
        )
    except stripe.StripeError as exc:
        raise PaymentsError(_friendly_stripe_error(exc))


def _friendly_stripe_error(exc):
    """把 Stripe 异常翻译成中文摘要，不暴露技术类名与请求体。"""
    message = (getattr(exc, "user_message", None) or str(exc) or "").lower()
    code = getattr(exc, "code", "") or ""
    if "amount" in message or code == "amount_too_small":
        return "支付金额不被受理，请检查后台商品价格配置"
    if "currency" in message:
        return "币种不被受理，请检查后台商品价格配置"
    if "api key" in message or "unauthorized" in message:
        return "支付密钥无效，请检查 STRIPE_SECRET_KEY 配置"
    return "支付通道返回异常，请稍后重试"


# ---------------------------------------------------------------- Webhook

def parse_webhook(raw_body, sig_header):
    """验签并解析事件。

    必须传入**原始请求体**（bytes/str）。先 json.loads 再 dumps 的写法会因
    键序与空格差异导致 HMAC 不匹配 —— 这是新手最常踩的坑。

    Raises:
        PaymentsError: 验签失败（不含 payload 细节，避免日志泄密）
    """
    if not WEBHOOK_SECRET:
        raise PaymentsError("未配置 Webhook 签名密钥")
    if not sig_header:
        raise PaymentsError("缺少 Stripe-Signature 请求头")
    try:
        return client().construct_event(raw_body, sig_header, WEBHOOK_SECRET)
    except stripe.SignatureVerificationError:
        raise PaymentsError("Stripe 回调签名校验失败")
    except ValueError:
        raise PaymentsError("Stripe 回调内容无法解析")


def session_amount_matches(session, order):
    """发货前二次校验金额：后台价格配错时宁可不发货，也不多发/少收费。"""
    total = getattr(session, "amount_total", None)
    currency = (getattr(session, "currency", "") or "").lower()
    return total is not None and int(total) == int(order["amount"]) and currency == order["currency"]
