"""Stripe subscription wiring — Supabase-backed.

Five monthly plans (solo / writers_room / studio / prod_company / producer).
Subscription state is written to public.profiles (subscription_active, plan,
stripe_customer_id, stripe_subscription_id). Webhooks are signature-verified.
"""
from __future__ import annotations

import os

import stripe
from flask import Blueprint, request, redirect, url_for, jsonify, render_template
from flask_login import login_required, current_user

from db import get_sb

billing_bp = Blueprint("billing", __name__)


def _stripe():
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return stripe


_PLANS = {
    # Filmmaker tier plans
    "solo":          {"env": "STRIPE_PRICE_SOLO",          "label": "Solo",             "price": "$10/mo",  "role": "filmmaker"},
    "writers_room":  {"env": "STRIPE_PRICE_WRITERS_ROOM",  "label": "Writer's Room",    "price": "$25/mo",  "role": "filmmaker"},
    "prod_company":  {"env": "STRIPE_PRICE_PROD_COMPANY",  "label": "Production Co.",   "price": "$75/mo",  "role": "filmmaker"},
    "studio":        {"env": "STRIPE_PRICE_STUDIO",        "label": "Studio",           "price": "$150/mo", "role": "filmmaker"},
    # Above the Line (producer/DP/director)
    "producer":      {"env": "STRIPE_PRICE_PRODUCER",      "label": "Above the Line",   "price": "$49/mo",  "role": "producer"},
}


def plans_for_role(role: str) -> dict:
    """Return only the plans available to the given role."""
    return {k: v for k, v in _PLANS.items() if v.get("role") == role}


def get_price_id(plan: str) -> str:
    cfg = _PLANS.get(plan, _PLANS["solo"])
    return os.environ.get(cfg["env"], "")


def is_subscribed(user_id) -> bool:
    """Quick check used by the subscription_required decorator."""
    sb = get_sb()
    try:
        r = sb.table("profiles").select("subscription_active").eq("id", user_id).limit(1).execute()
        return bool(r.data and r.data[0].get("subscription_active"))
    except Exception:
        return False


def _update_profile_by_id(user_id: str, patch: dict) -> None:
    sb = get_sb()
    sb.table("profiles").update(patch).eq("id", user_id).execute()


def _update_profile_by_customer(customer_id: str, patch: dict) -> None:
    sb = get_sb()
    sb.table("profiles").update(patch).eq("stripe_customer_id", customer_id).execute()


# ── routes ────────────────────────────────────────────────────────────────────

@billing_bp.route("/billing")
@login_required
def billing_page():
    role = getattr(current_user, "role", "filmmaker")
    plans = plans_for_role(role) or plans_for_role("filmmaker")
    return render_template(
        "billing.html",
        user_email=current_user.email,
        current_plan=current_user.plan,
        current_role=role,
        role_label=getattr(current_user, "role_label", "Filmmaker"),
        is_subscribed=current_user.subscription_active,
        plans=plans,
    )


@billing_bp.route("/stripe/checkout", methods=["POST"])
@login_required
def create_checkout():
    plan = (request.form.get("plan") or request.json.get("plan") if request.is_json else request.form.get("plan")) or "solo"
    if plan not in _PLANS:
        plan = "solo"

    price_id = get_price_id(plan)
    if not price_id:
        return jsonify({"error": "Stripe price not configured for that plan"}), 500

    s = _stripe()
    base_url = request.host_url.rstrip("/")

    try:
        checkout = s.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=current_user.email,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{base_url}/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/billing",
            metadata={"user_id": current_user.id, "plan": plan},
            subscription_data={"trial_period_days": 3},
        )
    except Exception as e:
        print(f"⚠️ Stripe checkout error: {e}", flush=True)
        return jsonify({"error": "Could not create checkout session"}), 500

    if request.is_json:
        return jsonify({"url": checkout.url})
    return redirect(checkout.url, code=303)


@billing_bp.route("/stripe/success")
@login_required
def stripe_success():
    session_id = request.args.get("session_id", "")
    if not session_id:
        return redirect(url_for("filmmaker_workspace"))

    try:
        s = _stripe()
        checkout = s.checkout.Session.retrieve(session_id, expand=["subscription", "customer"])
        if checkout.payment_status in ("paid", "no_payment_required"):
            plan = (checkout.metadata or {}).get("plan", "solo")
            customer_id = checkout.customer if isinstance(checkout.customer, str) else (checkout.customer.id if checkout.customer else "")
            sub_id = checkout.subscription if isinstance(checkout.subscription, str) else (checkout.subscription.id if checkout.subscription else "")

            _update_profile_by_id(current_user.id, {
                "subscription_active": True,
                "plan": plan,
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": sub_id,
            })
    except Exception as e:
        print(f"⚠️ Stripe success handler error: {e}", flush=True)

    return redirect(url_for("filmmaker_workspace") + "?subscribed=1", code=303)


@billing_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Signature-verified webhook. Never trust the payload without construct_event."""
    payload = request.get_data()
    sig = request.headers.get("stripe-signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    try:
        s = _stripe()
        event = s.Webhook.construct_event(payload, sig, webhook_secret)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    etype = event["type"]

    if etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        customer_id = sub.get("customer")
        if customer_id:
            _update_profile_by_customer(customer_id, {
                "subscription_active": False,
                "plan": "trial",
                "stripe_subscription_id": "",
            })

    elif etype in ("customer.subscription.updated", "invoice.payment_succeeded"):
        obj = event["data"]["object"]
        customer_id = obj.get("customer")
        if customer_id:
            active = (obj.get("status") == "active") if etype != "invoice.payment_succeeded" else True
            if active:
                _update_profile_by_customer(customer_id, {"subscription_active": True})
            else:
                _update_profile_by_customer(customer_id, {"subscription_active": False, "plan": "trial"})

    return jsonify({"ok": True})
