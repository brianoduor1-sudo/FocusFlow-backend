from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.database import db
from app.models import Subscription

subscription_bp = Blueprint("subscription", __name__, url_prefix="/api/subscription")

PLANS = {
    "free": {
        "id": "free",
        "name": "Free",
        "monthly_price": 0,
        "yearly_price": 0,
        "features": [
            "Up to 3 active projects",
            "Basic task & note tracking",
            "Standard focus timer",
            "1 connected GitHub account",
        ],
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "monthly_price": 9,
        "yearly_price": 90,
        "features": [
            "Unlimited projects & tasks",
            "Full GitHub repo, commit, issue & PR sync",
            "Advanced focus session analytics",
            "Priority support",
        ],
    },
    "team": {
        "id": "team",
        "name": "Team",
        "monthly_price": 24,
        "yearly_price": 240,
        "features": [
            "Everything in Pro",
            "Shared team workspaces",
            "Cross-repo activity insights",
            "Role-based access control",
        ],
    },
}

def _get_or_create_subscription(user_id: int) -> Subscription:
    sub = Subscription.query.filter_by(user_id=user_id).first()
    if not sub:
        sub = Subscription(
            user_id=user_id,
            plan="free",
            status="active",
            billing_cycle="monthly",
            current_period_start=datetime.utcnow(),
        )
        db.session.add(sub)
        db.session.commit()
    return sub

def _serialize_subscription(sub: Subscription) -> dict:
    plan_details = PLANS.get(sub.plan, PLANS["free"])
    return {
        "id": sub.id,
        "user_id": sub.user_id,
        "plan": sub.plan,
        "plan_name": plan_details["name"],
        "status": sub.status,
        "billing_cycle": sub.billing_cycle,
        "features": plan_details["features"],
        "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }

@subscription_bp.get("/plans")
def list_plans():
    
    return jsonify({"plans": list(PLANS.values())}), 200

@subscription_bp.get("")
@jwt_required()
def get_current_subscription():
    
    user_id = int(get_jwt_identity())
    sub = _get_or_create_subscription(user_id)
    return jsonify(_serialize_subscription(sub)), 200

@subscription_bp.post("/upgrade")
@jwt_required()
def upgrade_subscription():
    
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    target_plan = (data.get("plan") or "").lower()
    billing_cycle = (data.get("billing_cycle") or "monthly").lower()

    if target_plan not in PLANS:
        return jsonify({"error": f"Invalid plan '{target_plan}'. Choose from: {', '.join(PLANS.keys())}."}), 400

    if billing_cycle not in ("monthly", "yearly"):
        return jsonify({"error": "billing_cycle must be 'monthly' or 'yearly'."}), 400

    sub = _get_or_create_subscription(user_id)
    now = datetime.utcnow()
    duration_days = 365 if billing_cycle == "yearly" else 30

    sub.plan = target_plan
    sub.status = "active"
    sub.billing_cycle = billing_cycle
    sub.current_period_start = now
    sub.current_period_end = None if target_plan == "free" else now + timedelta(days=duration_days)
    sub.cancel_at_period_end = False

    db.session.commit()
    return jsonify({
        "message": f"Subscription updated to {PLANS[target_plan]['name']}.",
        "subscription": _serialize_subscription(sub),
    }), 200

@subscription_bp.post("/cancel")
@jwt_required()
def cancel_subscription():
    
    user_id = int(get_jwt_identity())
    sub = _get_or_create_subscription(user_id)

    if sub.plan == "free":
        return jsonify({"error": "Free plan cannot be canceled."}), 400

    sub.cancel_at_period_end = True
    sub.status = "canceled"
    db.session.commit()

    return jsonify({
        "message": "Subscription will downgrade to Free at the end of the current billing period.",
        "subscription": _serialize_subscription(sub),
    }), 200

@subscription_bp.post("/reactivate")
@jwt_required()
def reactivate_subscription():
    
    user_id = int(get_jwt_identity())
    sub = _get_or_create_subscription(user_id)

    if sub.plan == "free":
        return jsonify({"error": "No paid subscription to reactivate."}), 400

    sub.cancel_at_period_end = False
    sub.status = "active"
    db.session.commit()

    return jsonify({
        "message": "Subscription reactivated.",
        "subscription": _serialize_subscription(sub),
    }), 200
