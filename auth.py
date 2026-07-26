"""Flask-Login sitting on top of Supabase Auth + public.profiles.

Auth flow:
    signup → sb.auth.sign_up() → row in auth.users → we upsert profiles row
    signin → sb.auth.sign_in_with_password() → we load profiles row → login_user
    forgot → we sign a token, mail reset link; on submit we call
             sb.auth.admin.update_user_by_id() to change the password

Role model:
    Supabase profiles.plan carries the role for free tiers (actor/investor/
    supporter). For paid tiers we derive role from plan:
        producer                                             -> producer
        solo, writers_room, studio, prod_company             -> filmmaker
        actor / investor / supporter                         -> role == plan
    A convenience `role` attribute on the User exposes this for downstream
    gating (project creation, workspace routing).
"""
from __future__ import annotations

import os

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from db import get_sb
from mailer import send_mail

RESET_TOKEN_TTL = 30 * 60
RESET_TOKEN_SALT = "evolum-password-reset-v1"

auth_bp = Blueprint("auth", __name__)
login_manager = LoginManager()

VALID_ROLES = {"filmmaker", "producer", "actor", "investor", "supporter"}
PROJECT_ROLES = {"filmmaker", "producer"}
FREE_ROLES = {"actor", "investor", "supporter"}
ROLE_HOME = {
    "filmmaker":  "filmmaker_workspace",
    "producer":   "filmmaker_workspace",
    "actor":      "actor_casting",
    "investor":   "investor_deal_room",
    "supporter":  "supporter_feed",
}

# Filmmaker-tier plans that map back to role='filmmaker'.
_FILMMAKER_PLANS = {"solo", "writers_room", "studio", "prod_company", "trial"}


def _derive_role(plan: str | None) -> str:
    if not plan:
        return "filmmaker"
    plan = plan.lower()
    if plan in ("actor", "investor", "supporter", "producer"):
        return plan
    if plan in _FILMMAKER_PLANS:
        return "filmmaker"
    return "filmmaker"


class User(UserMixin):
    """Flask-Login user backed by a public.profiles row.

    self.id is the Supabase auth user UUID as a string (Flask-Login accepts
    string IDs). All auth checks (login_required, current_user) travel
    through this class.
    """
    def __init__(self, profile: dict):
        self.id = str(profile["id"])
        self.email = profile.get("email", "")
        self.name = profile.get("name", "") or ""
        self.plan = profile.get("plan") or "trial"
        self.role = _derive_role(profile.get("plan"))
        self.subscription_active = bool(profile.get("subscription_active"))
        self.stripe_customer_id = profile.get("stripe_customer_id") or ""
        self.stripe_subscription_id = profile.get("stripe_subscription_id") or ""

    @property
    def can_create_projects(self):
        return self.role in PROJECT_ROLES

    @property
    def role_label(self):
        return {
            "filmmaker": "Filmmaker",
            "producer":  "Above the Line",
            "actor":     "Actor",
            "investor":  "Investor",
            "supporter": "Supporter",
        }.get(self.role, "Filmmaker")


@login_manager.user_loader
def load_user(user_id: str):
    sb = get_sb()
    try:
        r = sb.table("profiles").select("*").eq("id", user_id).limit(1).execute()
        if r.data:
            return User(r.data[0])
    except Exception as e:
        print(f"⚠️  load_user failed for {user_id}: {e}", flush=True)
    return None


def init_login(app):
    login_manager.init_app(app)
    login_manager.login_view = "auth.signin"
    login_manager.login_message = ""


def _upsert_profile(sb, user_id: str, email: str, name: str = "",
                    plan: str = "trial", subscription_active: bool = False) -> dict:
    """Insert a profile row if none exists for this auth user. Returns the row."""
    r = sb.table("profiles").select("*").eq("id", user_id).limit(1).execute()
    if r.data:
        return r.data[0]
    row = {
        "id": user_id,
        "email": email,
        "name": name,
        "plan": plan,
        "subscription_active": subscription_active,
    }
    sb.table("profiles").insert(row).execute()
    r = sb.table("profiles").select("*").eq("id", user_id).limit(1).execute()
    return r.data[0] if r.data else row


# ── routes ────────────────────────────────────────────────────────────────────

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    name = (request.form.get("name") or "").strip()
    role = (request.form.get("role") or "filmmaker").strip().lower()
    plan_form = (request.form.get("plan") or "").strip().lower()

    if role not in VALID_ROLES:
        role = "filmmaker"
    if not email or not password:
        flash("Email and password required.", "error")
        return redirect(url_for("auth.signup"))
    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return redirect(url_for("auth.signup"))

    # For free roles the plan equals the role. For paid roles use whatever
    # plan came in on the form (solo / writers_room / studio / prod_company /
    # producer); default to solo if the form somehow shipped nothing.
    if role in FREE_ROLES:
        plan = role
    elif role == "producer":
        plan = "producer"
    else:  # filmmaker
        plan = plan_form if plan_form in _FILMMAKER_PLANS else "solo"

    sb = get_sb()
    try:
        result = sb.auth.sign_up({"email": email, "password": password})
    except Exception as e:
        emsg = str(e)
        if "already" in emsg.lower() or "registered" in emsg.lower():
            flash("That email is already in use. Try signing in.", "error")
            return redirect(url_for("auth.signin"))
        flash(f"Signup failed: {emsg}", "error")
        return redirect(url_for("auth.signup"))

    auth_user = getattr(result, "user", None)
    if not auth_user:
        flash("Signup couldn't complete. Try again.", "error")
        return redirect(url_for("auth.signup"))

    profile = _upsert_profile(
        sb, str(auth_user.id), email, name=name, plan=plan,
        subscription_active=(role in FREE_ROLES),
    )

    login_user(User(profile))

    if role in FREE_ROLES:
        home = ROLE_HOME.get(role, "filmmaker_workspace")
        return redirect(url_for(home))
    return redirect(url_for("billing.billing_page"))


@auth_bp.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "GET":
        return render_template("signin.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    sb = get_sb()
    try:
        result = sb.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        emsg = str(e)
        if "invalid" in emsg.lower() or "credentials" in emsg.lower():
            flash("Email or password incorrect.", "error")
        else:
            flash(f"Sign-in failed: {emsg}", "error")
        return redirect(url_for("auth.signin"))

    auth_user = getattr(result, "user", None)
    if not auth_user:
        flash("Sign-in failed.", "error")
        return redirect(url_for("auth.signin"))

    profile = _upsert_profile(sb, str(auth_user.id), email)
    login_user(User(profile))
    user = User(profile)
    home = ROLE_HOME.get(user.role, "filmmaker_workspace")
    return redirect(url_for(home))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Password reset ────────────────────────────────────────────────────────────
def _reset_serializer():
    secret = current_app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-only"
    return URLSafeTimedSerializer(secret, salt=RESET_TOKEN_SALT)


@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    """Generic 200 regardless — never leaks whether the email exists."""
    email = (request.form.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": True}, 200

    sb = get_sb()
    try:
        r = sb.table("profiles").select("id,email").eq("email", email).limit(1).execute()
        row = r.data[0] if r.data else None
    except Exception as e:
        print(f"⚠️  forgot_password lookup failed: {e}", flush=True)
        row = None

    if row:
        token = _reset_serializer().dumps(str(row["id"]))
        base = request.host_url.rstrip("/")
        link = f"{base}/reset-password/{token}"
        subject = "Reset your EVOLUM password"
        text = (
            f"Someone (hopefully you) asked to reset the password for {email}.\n\n"
            f"Open this link to set a new one — it expires in 30 minutes:\n\n"
            f"{link}\n\n"
            f"If you didn't request this, ignore this email. Your password stays the same."
        )
        html = (
            f'<div style="font-family:Georgia,serif;font-size:15px;color:#222;line-height:1.6;'
            f'max-width:560px;margin:0 auto;padding:32px;">'
            f'<div style="font-family:monospace;font-size:11px;letter-spacing:2px;'
            f'text-transform:uppercase;color:#c5562a;margin-bottom:18px;">EVOLUM</div>'
            f'<h1 style="font-family:Georgia,serif;font-style:italic;font-weight:400;'
            f'font-size:26px;color:#111;margin:0 0 18px;">Reset your password.</h1>'
            f'<p>Someone (hopefully you) asked to reset the password for '
            f'<strong>{email}</strong>.</p>'
            f'<p>Open the button below to set a new one — the link expires in 30 minutes.</p>'
            f'<p style="margin:28px 0;"><a href="{link}" '
            f'style="display:inline-block;background:#c5562a;color:#fff;text-decoration:none;'
            f'padding:12px 22px;font-family:monospace;font-size:12px;letter-spacing:1.2px;'
            f'text-transform:uppercase;">Reset password →</a></p>'
            f'<p style="font-size:13px;color:#666;">If the button doesn\'t work, paste this URL:<br>'
            f'<span style="word-break:break-all;color:#c5562a;">{link}</span></p>'
            f'<p style="font-size:13px;color:#888;margin-top:32px;">'
            f'If you didn\'t request this, ignore this email. Your password stays the same.</p>'
            f'</div>'
        )
        try:
            send_mail(email, subject, text, html)
        except Exception as e:
            print(f"⚠️  forgot_password: mail send failed: {e}", flush=True)
        print(f"password-reset issued for user_id={row['id']}", flush=True)
    return {"ok": True}, 200


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    try:
        user_id = _reset_serializer().loads(token, max_age=RESET_TOKEN_TTL)
    except SignatureExpired:
        return render_template("reset_password.html",
                               error="This reset link has expired. Request a new one.",
                               link_dead=True, dead_reason="expired"), 400
    except BadSignature:
        return render_template("reset_password.html",
                               error="This reset link is invalid.",
                               link_dead=True, dead_reason="invalid"), 400

    sb = get_sb()
    try:
        r = sb.table("profiles").select("*").eq("id", user_id).limit(1).execute()
        row = r.data[0] if r.data else None
    except Exception:
        row = None
    if not row:
        return render_template("reset_password.html",
                               error="Account not found.",
                               link_dead=True, dead_reason="missing"), 400

    if request.method == "POST":
        new_password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(new_password) < 8:
            return render_template("reset_password.html", token=token, email=row["email"],
                                   error="Password must be at least 8 characters."), 400
        if new_password != confirm:
            return render_template("reset_password.html", token=token, email=row["email"],
                                   error="Passwords don't match."), 400
        try:
            sb.auth.admin.update_user_by_id(user_id, {"password": new_password})
        except Exception as e:
            print(f"⚠️  reset_password: update_user_by_id failed: {e}", flush=True)
            return render_template("reset_password.html", token=token, email=row["email"],
                                   error="Couldn't set the new password. Try again."), 500
        login_user(User(row))
        home = ROLE_HOME.get(_derive_role(row.get("plan")), "filmmaker_workspace")
        return redirect(url_for(home))

    return render_template("reset_password.html", token=token, email=row["email"])
