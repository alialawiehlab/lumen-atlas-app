"""
Lumen Atlas — Supabase-backed authentication (adapted from Cortex Atlas)

Implements the classic signup-then-verify flow:
  1. User submits name + academic email + affiliation + password.
  2. Supabase creates the user as unverified and emails a confirmation link.
  3. User clicks the link, is marked verified, and can log in.

Local-dev fallback: if SUPABASE_URL or SUPABASE_ANON_KEY is missing, the module
falls back to a single shared password (env var LUMEN_ATLAS_PASSWORD) so the
PI can keep iterating locally without standing up Supabase.

Env vars used:
  SUPABASE_URL              — project URL, e.g. https://abcdef.supabase.co
  SUPABASE_ANON_KEY         — anon public key (safe to ship to clients)
  SUPABASE_REDIRECT_URL     — where the verification email lands the user
                              (e.g. https://your-space.hf.space). Optional;
                              if unset, Supabase uses the project default.
  LUMEN_ATLAS_PASSWORD     — local-dev fallback password.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import streamlit as st

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
SUPABASE_REDIRECT_URL = os.environ.get("SUPABASE_REDIRECT_URL", "").strip()
LEGACY_PASSWORD = os.environ.get("LUMEN_ATLAS_PASSWORD", "lumen-atlas-2026")

SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_ANON_KEY)

ACADEMIC_DOMAIN_RE = re.compile(
    r"\.(edu|edu\.[a-z]{2,3}|ac\.[a-z]{2,3})$", re.IGNORECASE
)


def _is_academic_email(email: str) -> bool:
    """Accept .edu, .edu.<cc>, and .ac.<cc> (e.g. .edu.au, .ac.uk, .ac.jp)."""
    return bool(ACADEMIC_DOMAIN_RE.search((email or "").strip()))


@st.cache_resource
def _get_supabase_client():
    if not SUPABASE_ENABLED:
        return None
    from supabase import create_client  # imported lazily so local dev needn't install it
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def current_user() -> Optional[dict]:
    """Return a dict {email, name, affiliation, role} for the signed-in user, or None."""
    return st.session_state.get("lumen_user")


def is_admin() -> bool:
    """True iff the signed-in user has role == 'admin' in their Supabase user metadata."""
    u = current_user()
    return bool(u and u.get("role") == "admin")


def sign_out() -> None:
    client = _get_supabase_client()
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    for k in ("lumen_user", "lumen_session", "authenticated"):
        st.session_state.pop(k, None)
    st.rerun()


# ---------------------------------------------------------------------------
# Local-dev fallback (shared password)
# ---------------------------------------------------------------------------
def _legacy_password_gate(logo_path: Optional[Path], has_logo: bool) -> bool:
    if st.session_state.get("authenticated", False):
        return True
    cols = st.columns([1, 2, 1])
    with cols[1]:
        if has_logo and logo_path is not None:
            st.image(str(logo_path), width=320)
        else:
            st.title("Lumen Atlas")
        st.markdown("#### Neurointerventional Co-Authorship Network")
        st.caption(
            "Local-dev mode — Supabase auth not configured. "
            "Set SUPABASE_URL and SUPABASE_ANON_KEY to enable academic accounts."
        )
        pw = st.text_input("Password", type="password")
        if st.button("Login", width="stretch"):
            if pw == LEGACY_PASSWORD:
                st.session_state["authenticated"] = True
                st.session_state["lumen_user"] = {
                    "email": "local-dev@lumen.atlas",
                    "name": "Local developer",
                    "affiliation": "Local",
                    "role": "admin",
                }
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


# ---------------------------------------------------------------------------
# Supabase signup / login UI
# ---------------------------------------------------------------------------
def _render_signup_tab(client) -> None:
    st.markdown(
        "Lumen Atlas is open to verified academic researchers. "
        "Accounts require an email address from an `.edu`, `.ac.<country>`, or "
        "`.edu.<country>` domain."
    )
    with st.form("signup_form", clear_on_submit=False):
        name = st.text_input("Full name")
        email = st.text_input("Academic email", placeholder="you@university.edu")
        affiliation = st.text_input(
            "Affiliation",
            placeholder="Department, institution, country",
        )
        pw = st.text_input("Choose a password (min 8 characters)", type="password")
        pw2 = st.text_input("Confirm password", type="password")
        agree = st.checkbox(
            "I am an academic researcher and consent to my email and "
            "affiliation being stored for account management."
        )
        submitted = st.form_submit_button("Request account", width="stretch")

    if not submitted:
        return

    if not name.strip() or not affiliation.strip():
        st.error("Name and affiliation are required.")
        return
    if not _is_academic_email(email):
        st.error(
            "Email must be from an academic domain (e.g. `.edu`, `.ac.uk`, `.edu.au`). "
            "If your institution uses a different domain and you are an academic "
            "researcher, please use the Contact page to request manual access."
        )
        return
    if len(pw) < 8:
        st.error("Password must be at least 8 characters.")
        return
    if pw != pw2:
        st.error("Passwords do not match.")
        return
    if not agree:
        st.error("Please confirm consent before submitting.")
        return

    options: dict = {
        "data": {"name": name.strip(), "affiliation": affiliation.strip()},
    }
    if SUPABASE_REDIRECT_URL:
        options["email_redirect_to"] = SUPABASE_REDIRECT_URL

    try:
        client.auth.sign_up(
            {"email": email.strip(), "password": pw, "options": options}
        )
    except Exception as e:
        msg = str(e)
        if "already registered" in msg.lower() or "exists" in msg.lower():
            st.error(
                "An account with this email already exists. "
                "Use the **Sign in** tab, or check your inbox for an unfinished "
                "verification email."
            )
        else:
            st.error(f"Sign-up failed: {msg}")
        return

    st.success(
        "Account requested. We sent a verification link to **"
        + email.strip()
        + "** — click it from any device to confirm your address, then return "
        "here and sign in."
    )


def _render_signin_tab(client) -> None:
    with st.form("signin_form"):
        email = st.text_input("Email")
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", width="stretch")

    if not submitted:
        return

    try:
        resp = client.auth.sign_in_with_password(
            {"email": email.strip(), "password": pw}
        )
    except Exception as e:
        msg = str(e).lower()
        if "email not confirmed" in msg or "not confirmed" in msg:
            st.error(
                "Your email is not yet verified. Check your inbox (and spam folder) "
                "for the verification link."
            )
        elif "invalid login" in msg or "invalid" in msg:
            st.error("Invalid email or password.")
        else:
            st.error(f"Sign-in failed: {e}")
        return

    user = getattr(resp, "user", None)
    session = getattr(resp, "session", None)
    if not user or not session:
        st.error("Sign-in returned no session. Please try again.")
        return

    meta = getattr(user, "user_metadata", None) or {}

    # Single-use credential enforcement.
    # A user can be flagged single_use=true in their user_metadata (set via
    # Supabase dashboard or admin API). The first successful sign-in flips
    # consumed=true; any subsequent attempt is refused.
    if meta.get("single_use") is True:
        if meta.get("consumed") is True:
            try:
                client.auth.sign_out()
            except Exception:
                pass
            st.error(
                "This is a single-use credential and has already been used. "
                "Please request a new account via the **Request account** tab, "
                "or contact the developers for another invite."
            )
            return
        # First (and only) sign-in: mark consumed before granting access.
        new_meta = dict(meta)
        new_meta["consumed"] = True
        new_meta["consumed_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        try:
            client.auth.update_user({"data": new_meta})
            meta = new_meta
        except Exception as e:
            try:
                client.auth.sign_out()
            except Exception:
                pass
            st.error(
                "Could not mark this single-use credential as consumed. "
                "For safety, sign-in was aborted. Please contact the developers. "
                f"Detail: {e}"
            )
            return

    st.session_state["lumen_session"] = session.access_token
    st.session_state["lumen_user"] = {
        "email": user.email,
        "name": meta.get("name", user.email),
        "affiliation": meta.get("affiliation", ""),
        "role": meta.get("role", "user"),
        "single_use": bool(meta.get("single_use")),
    }
    st.session_state["authenticated"] = True
    st.rerun()


def _render_forgot_tab(client) -> None:
    st.caption(
        "Enter the email you registered with. We will send a password-reset link."
    )
    with st.form("forgot_form"):
        email = st.text_input("Email", key="forgot_email")
        submitted = st.form_submit_button("Send reset link", width="stretch")
    if not submitted:
        return
    if not _is_academic_email(email):
        st.error("That does not look like a registered academic email.")
        return
    try:
        kwargs = {}
        if SUPABASE_REDIRECT_URL:
            kwargs["redirect_to"] = SUPABASE_REDIRECT_URL
        client.auth.reset_password_email(email.strip(), **kwargs)
        st.success("If an account exists for that email, a reset link is on its way.")
    except Exception as e:
        st.error(f"Could not send reset email: {e}")


def _render_supabase_screen(logo_path: Optional[Path], has_logo: bool) -> None:
    cols = st.columns([1, 2, 1])
    with cols[1]:
        if has_logo and logo_path is not None:
            st.image(str(logo_path), width=320)
        else:
            st.title("Lumen Atlas")
        st.markdown("#### Neurointerventional Co-Authorship Network")
        st.caption("Sign in with your academic email, or request a new account.")

        client = _get_supabase_client()
        tab_in, tab_up, tab_forgot = st.tabs(
            ["Sign in", "Request account", "Forgot password"]
        )
        with tab_in:
            _render_signin_tab(client)
        with tab_up:
            _render_signup_tab(client)
        with tab_forgot:
            _render_forgot_tab(client)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def require_login(logo_path: Optional[Path] = None, has_logo: bool = False) -> bool:
    """Render auth UI if needed; return True iff the user is signed in.

    Caller pattern:
        if not auth.require_login(LOGO_PATH, HAS_LOGO):
            st.stop()
    """
    if st.session_state.get("authenticated", False):
        return True
    if not SUPABASE_ENABLED:
        return _legacy_password_gate(logo_path, has_logo)
    _render_supabase_screen(logo_path, has_logo)
    return False


def render_sidebar_user_card() -> None:
    """Show the signed-in user's name + a sign-out button in the sidebar."""
    u = current_user()
    if not u:
        return
    st.sidebar.markdown("---")
    badge = ""
    if u.get("role") == "admin":
        badge = " 🛡️ *Admin*"
    elif u.get("single_use"):
        badge = " 🎟️ *Guest (single-use)*"
    st.sidebar.markdown(f"**Signed in as**  \n{u['name']}{badge}")
    if u.get("affiliation"):
        st.sidebar.caption(u["affiliation"])
    if u.get("single_use"):
        st.sidebar.caption(
            "This is a single-use credential. Once you sign out, it cannot be reused."
        )
    if st.sidebar.button("Sign out", key="sign_out_btn", width="stretch"):
        sign_out()
