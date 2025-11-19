import os
import base64
from datetime import date, timedelta
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
import streamlit as st

from auth import hash_password, verify_password
from db import (
    create_user,
    fetch_campaigns,
    get_user_by_email,
    insert_campaign,
    insert_creator_rows,
    update_last_login,
)
from logic.calculator import calculate_campaign

# ------------ BASIC CONFIG ------------

st.set_page_config(
    page_title="Vero Echo Effect Tool",
    layout="wide",
)

# Ensure data dir exists
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

if "user" not in st.session_state:
    st.session_state["user"] = None
st.session_state.setdefault("show_register", False)
st.session_state.setdefault("show_forgot", False)
st.session_state.setdefault("remember_me_email", "")
st.session_state.setdefault("campaign_info", {})


def reset_campaign_builder_state() -> None:
    for key in [
        "campaign_info",
        "media_cards",
        "media_editor",
        "creator_cards",
        "creator_editor",
        "creator_upload_summary",
        "community_cards",
        "community_editor",
        "last_result",
        "last_inv",
        "last_campaign_name",
        "last_client",
        "last_market",
        "media_data_editor",
    ]:
        st.session_state.pop(key, None)
    st.session_state["wizard_completed"] = {step: False for step in WIZARD_STEPS}
    st.session_state["active_wizard_step"] = WIZARD_STEPS[0]


def goto_page(page_name: str, reset_builder: bool = False) -> None:
    if reset_builder:
        reset_campaign_builder_state()
    st.session_state["active_page"] = page_name


def start_new_campaign() -> None:
    goto_page(PAGE_CAMPAIGN_BUILDER, reset_builder=True)


def open_campaign_library() -> None:
    goto_page(PAGE_CAMPAIGN_LIBRARY)


def open_account_info() -> None:
    goto_page(PAGE_ACCOUNT_INFO)


def open_settings() -> None:
    goto_page(PAGE_SETTINGS)
PAGE_CAMPAIGN_BUILDER = "Campaign Builder"
PAGE_CAMPAIGN_LIBRARY = "Campaign Performance"
PAGE_ACCOUNT_INFO = "Account Info"
PAGE_SETTINGS = "Settings"
ALL_PAGES = {
    PAGE_CAMPAIGN_BUILDER,
    PAGE_CAMPAIGN_LIBRARY,
    PAGE_ACCOUNT_INFO,
    PAGE_SETTINGS,
}
st.session_state.setdefault("active_page", PAGE_CAMPAIGN_BUILDER)
if st.session_state["active_page"] not in ALL_PAGES:
    st.session_state["active_page"] = PAGE_CAMPAIGN_BUILDER

MARKET_OPTIONS = ["Thailand", "Vietnam", "Singapore", "Malaysia", "Myanmar", "Philippines"]
CURRENCY_OPTIONS = ["THB", "USD"]
OBJECTIVE_OPTIONS = [
    "Brand Awareness",
    "Perception Shift",
    "Community Growth",
    "Advocacy & UGC",
    "Product Launch",
    "Other",
]
DEFAULT_MAX_INVESTMENT_K = 2000.0  # equals 2M
MEDIA_CHANNEL_OPTIONS = ["Online Article", "Social Media"]
MEDIA_TIER_PRESETS = ["Major", "Industry", "Local/Niche", "Tier 1", "Tier 2", "Tier 3"]
CREATOR_PLATFORM_OPTIONS = ["Facebook", "Instagram", "TikTok", "YouTube", "X (Twitter)", "Other"]
CREATOR_CONTENT_OPTIONS = ["Static Post", "Video Post"]
CREATOR_TIER_OPTIONS = ["Mega", "Macro", "Mid-tier", "Micro", "Nano"]
COMMUNITY_PLATFORM_OPTIONS = ["Facebook", "Instagram", "TikTok", "YouTube", "X (Twitter)", "Other"]
WIZARD_STEPS = ["Campaign Brief", "Echo Studio", "Echo Impact Report"]


def get_creator_presets(platform: str) -> list[dict[str, Any]]:
    if platform == "TikTok":
        combos = [
            ("Static Post", "Macro"),
            ("Static Post", "Mega"),
            ("Static Post", "Micro"),
            ("Video Post", "Micro"),
            ("Static Post", "Mid-tier"),
            ("Video Post", "Mid-tier"),
            ("Static Post", "Nano"),
        ]
    else:
        combos = [
            (content, tier)
            for content in CREATOR_CONTENT_OPTIONS
            for tier in CREATOR_TIER_OPTIONS
        ]
    return [
        {"platform": platform, "content_type": content, "tier": tier, "num_posts": 0}
        for content, tier in combos
    ]


def merge_platform_rows(master_df: pd.DataFrame, platform: str) -> pd.DataFrame:
    preset_df = pd.DataFrame(get_creator_presets(platform))
    if master_df.empty:
        return preset_df.copy()

    platform_rows = master_df[master_df["platform"] == platform]
    if platform_rows.empty:
        return preset_df.copy()

    existing_idx = platform_rows.set_index(["platform", "content_type", "tier"])
    preset_idx = preset_df.set_index(["platform", "content_type", "tier"])
    merged = existing_idx.combine_first(preset_idx).reset_index()
    merged["num_posts"] = pd.to_numeric(merged["num_posts"], errors="coerce").fillna(0.0)
    return merged


def ensure_community_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            [
                {
                    "platform": platform,
                    "content_creation": 0,
                    "passive_engagement": 0,
                    "active_engagement": 0,
                    "amplification": 0,
                }
                for platform in COMMUNITY_PLATFORM_OPTIONS
            ]
        )

    existing = df["platform"].astype(str).tolist()
    missing = [platform for platform in COMMUNITY_PLATFORM_OPTIONS if platform not in existing]
    if not missing:
        return df

    extra_rows = [
        {
            "platform": platform,
            "content_creation": 0,
            "passive_engagement": 0,
            "active_engagement": 0,
            "amplification": 0,
        }
        for platform in missing
    ]
    return pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True)


def load_base64_image(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")


def inject_stylesheet(css_path: Path, replacements: dict[str, str] | None = None) -> None:
    try:
        css_raw = css_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return

    replacements = replacements or {}
    for placeholder, value in replacements.items():
        css_raw = css_raw.replace(placeholder, value)

    st.markdown(f"<style>{css_raw}</style>", unsafe_allow_html=True)


def _stringify(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalize_platform(value: Any) -> str:
    mapping = {
        "FACEBOOK": "Facebook",
        "INSTAGRAM": "Instagram",
        "TIKTOK": "TikTok",
        "YOUTUBE": "YouTube",
        "YOUTUBE SHORTS": "YouTube",
        "X": "X (Twitter)",
        "TWITTER": "X (Twitter)",
        "X (TWITTER)": "X (Twitter)",
        "LEMON 8": "Lemon 8",
        "LEMON8": "Lemon 8",
    }
    raw = _stringify(value).upper()
    return mapping.get(raw, _stringify(value))


def _normalize_content_type(value: Any) -> str:
    raw = _stringify(value).lower()
    if "video" in raw or "reel" in raw or "story" in raw:
        return "Video Post"
    return "Static Post"


def _normalize_tier(value: Any) -> str:
    mapping = {
        "MEGA": "Mega",
        "MACRO": "Macro",
        "MIDTIER": "Mid-tier",
        "MID-TIER": "Mid-tier",
        "MID TIER": "Mid-tier",
        "MICRO": "Micro",
        "NANO": "Nano",
    }
    raw = _stringify(value).replace("-", "").replace(" ", "").upper()
    return mapping.get(raw, "Macro")


def parse_creator_upload(uploaded_file: BinaryIO) -> tuple[pd.DataFrame, dict[str, Any]]:
    if uploaded_file is None:
        raise ValueError("No file provided.")
    uploaded_file.seek(0)
    df = pd.read_excel(uploaded_file, skiprows=4)
    rename_map = {
        "Profile": "profile",
        "Network": "platform",
        "Creator Tier": "tier",
        "Content Type": "content_type",
    }
    for column in rename_map:
        if column not in df.columns:
            raise ValueError(f"Missing column '{column}' in uploaded file.")
    working = df.rename(columns=rename_map).dropna(subset=list(rename_map.values()))
    working["profile"] = working["profile"].apply(_stringify)
    working["platform"] = working["platform"].apply(_normalize_platform)
    working["tier"] = working["tier"].apply(_normalize_tier)
    working["content_type"] = working["content_type"].apply(_normalize_content_type)
    working = working[working["profile"] != ""]

    grouped = (
        working.groupby(["platform", "content_type", "tier"])
        .size()
        .reset_index(name="num_posts")
        .sort_values(["platform", "tier"])
        .reset_index(drop=True)
    )
    grouped["num_posts"] = grouped["num_posts"].astype(int)
    summary = {
        "total_posts": int(working.shape[0]),
        "unique_creators": int(working["profile"].nunique()),
        "platform_breakdown": {
            platform: int(count) for platform, count in working["platform"].value_counts().items()
        },
    }
    return grouped, summary


def _serialize_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        return value
    return None


def save_campaign(result: dict[str, float],
                  inv: float,
                  campaign_name: str,
                  client: str,
                  market: str | None = None) -> int:
    owner = st.session_state.get("user") if "user" in st.session_state else None
    owner_id = owner.get("id") if isinstance(owner, dict) else None
    info = st.session_state.get("campaign_info", {})
    campaign_id = insert_campaign(
        result,
        inv,
        campaign_name,
        client,
        market or "",
        owner_id=owner_id,
        objective=info.get("campaign_objective"),
        objective_focus=info.get("campaign_objective_choice"),
        campaign_start=_serialize_date(info.get("campaign_start_date")),
        campaign_end=_serialize_date(info.get("campaign_end_date")),
        currency=info.get("campaign_currency"),
        investment_k=info.get("campaign_investment_k"),
        custom_budget_flag=info.get("campaign_custom_mode", False),
    )
    creator_df = st.session_state.get("creator_editor")
    if isinstance(creator_df, pd.DataFrame) and not creator_df.empty:
        insert_creator_rows(
            campaign_id,
            [
                {
                    "platform": row.get("platform"),
                    "content_type": row.get("content_type"),
                    "tier": row.get("tier"),
                    "num_posts": row.get("num_posts", 0),
                    "rate": row.get("rate", 0),
                    "source_campaign_id": None,
                }
                for row in creator_df.to_dict("records")
            ],
        )
    return campaign_id


def render_auth():
    backdrop = load_base64_image(os.path.join("img", "backdrop_gradient.png"))
    hero_texture = load_base64_image(os.path.join("img", "element_shape.png"))
    hero_figure = load_base64_image(os.path.join("img", "kol.png"))
    logo_src = load_base64_image(os.path.join("img", "logo_vero_white.png"))

    inject_stylesheet(
        Path("styles/landing.css"),
        {
            "__BACKDROP__": (
                f"url('data:image/png;base64,{backdrop}')"
                if backdrop
                else "linear-gradient(135deg,#f6f9ff 0%,#e0e8ff 100%)"
            ),
            "__HERO_TEXTURE__": (
                f"url('data:image/png;base64,{hero_texture}')"
                if hero_texture
                else "none"
            ),
            "__HERO_FIGURE__": (
                f"url('data:image/png;base64,{hero_figure}')"
                if hero_figure
                else "none"
            ),
        },
    )

    logo_html = (
        f'<img src="data:image/png;base64,{logo_src}" alt="Vero" />'
        if logo_src
        else '<div style="font-size:28px;font-weight:600;color:#fff;">VERO</div>'
    )

    show_register = st.session_state.get("show_register", False)
    show_forgot = st.session_state.get("show_forgot", False)

    st.markdown("<div class='auth-landing'>", unsafe_allow_html=True)

    hero_html = f"""
    <div class="hero-panel">
        <div class="hero-content">
            <div class="hero-logo">{logo_html}</div>
            <h1>Premium Analytics for Creator & Media Impact</h1>
            <p class="hero-tagline">Transform your campaign data into executive-ready insights with consulting-grade analytics.</p>
            <div class="hero-bullets">
                <div class="hero-bullet">
                    <span></span>
                    <div>Calculate total echo value across media, creators, and community.</div>
                </div>
                <div class="hero-bullet">
                    <span></span>
                    <div>Track ROI & earned reach with precision ripple metrics.</div>
                </div>
                <div class="hero-bullet">
                    <span></span>
                    <div>Generate presentation-ready dashboards instantly.</div>
                </div>
            </div>
        </div>
        <div class="hero-figure"></div>
    </div>
    """

    st.markdown(
        f"<div class='landing-wrapper'><div class='hero-cell'>{hero_html}</div><div class='login-column'><div class='login-panel'>",
        unsafe_allow_html=True,
    )

    if show_forgot:
        st.markdown("<h3>Reset Password</h3>", unsafe_allow_html=True)
        st.markdown(
            "<p class='subtitle'>We will send a reset link to your email.</p>",
            unsafe_allow_html=True,
        )
        with st.form("forgot_form"):
            email = st.text_input("Work Email", key="forgot_email")
            submitted = st.form_submit_button("Send reset link")
            if submitted:
                if not email or "@" not in email:
                    st.error("Enter a valid email.")
                elif not get_user_by_email(email):
                    st.error("No account found for this email.")
                else:
                    st.info("If an account exists, reset instructions have been sent.")
                    st.session_state["show_forgot"] = False
        st.button("Back to sign in", on_click=lambda: st.session_state.update(show_forgot=False))

    elif show_register:
        st.markdown("<h3>Create Account</h3>", unsafe_allow_html=True)
        st.markdown(
            "<p class='subtitle'>Get access to the Vero Echo Effect tool.</p>",
            unsafe_allow_html=True,
        )
        with st.form("register_form"):
            name = st.text_input("Full Name", key="register_name")
            company = st.text_input("Company / Organization", key="register_company")
            team = st.text_input("Team / Department", key="register_team")
            email = st.text_input("Work Email (use company domain)", key="register_email")
            password = st.text_input("Password", type="password", key="register_password")
            confirm = st.text_input("Confirm Password", type="password", key="register_confirm")
            submitted = st.form_submit_button("Create account")

            if submitted:
                if not (name and email and password and confirm):
                    st.error("Please complete all fields.")
                elif password != confirm:
                    st.error("Passwords do not match.")
                elif get_user_by_email(email):
                    st.error("An account with this email already exists.")
                else:
                    hashed_pw = hash_password(password)
                    create_user(
                        email=email,
                        password_hash=hashed_pw,
                        name=name,
                        company=company or None,
                        team=team or None,
                    )
                    st.success("Account created. Please sign in.")
                    st.session_state["show_register"] = False
        st.button("Back to sign in", on_click=lambda: st.session_state.update(show_register=False))

    else:
        st.markdown("<h3>Welcome Back</h3>", unsafe_allow_html=True)
        st.markdown("<p class='subtitle'>Sign in to access your campaigns</p>", unsafe_allow_html=True)
        with st.form("login_form"):
            email = st.text_input(
                "Email",
                key="login_email",
                value=st.session_state.get("remember_me_email", ""),
                placeholder="your.email@company.com",
            )
            password = st.text_input(
                "Password",
                type="password",
                key="login_password",
                placeholder="Enter your password",
            )
            remember_me = st.checkbox(
                "Remember me",
                value=bool(st.session_state.get("remember_me_email")),
                key="remember_me",
            )
            submitted = st.form_submit_button("Sign In")

            if submitted:
                user = get_user_by_email(email)
                if not user:
                    st.error("Account not found.")
                elif not verify_password(password, user["password_hash"]):
                    st.error("Incorrect password. Try again.")
                else:
                    st.session_state["user"] = user
                    update_last_login(user["id"])
                    st.session_state["remember_me_email"] = email if remember_me else ""
                    st.success("Welcome back!")

        st.markdown("<div class='login-links'>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.button(
                "Create Account",
                on_click=lambda: st.session_state.update(show_register=True),
                key="cta_register",
            )
        with col2:
            st.button(
                "Forgot Password",
                on_click=lambda: st.session_state.update(show_forgot=True),
                key="cta_forgot",
            )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div></div></div>", unsafe_allow_html=True)  # close login panel + column + wrapper
    st.markdown(
        "<p class='login-footnote'>Premium analytics for creator & media impact.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)  # close auth-landing

if st.session_state["user"] is None:
    render_auth()
    st.stop()

user = st.session_state.get("user")
if user:
    st.sidebar.write(f"**Signed in:** {user.get('name') or user.get('email')}")
    if st.sidebar.button("Sign out"):
        st.session_state["user"] = None
        goto_page(PAGE_CAMPAIGN_BUILDER, reset_builder=True)
        st.rerun()

page = st.session_state.get("active_page", PAGE_CAMPAIGN_BUILDER)
st.sidebar.header("Campaign Lab")
st.sidebar.button(
    "Create New Campaign",
    type="primary" if page == PAGE_CAMPAIGN_BUILDER else "secondary",
    use_container_width=True,
    on_click=start_new_campaign,
)
st.sidebar.button(
    "Campaign Performance",
    type="primary" if page == PAGE_CAMPAIGN_LIBRARY else "secondary",
    use_container_width=True,
    on_click=open_campaign_library,
)
st.sidebar.header("My Account")
st.sidebar.button(
    "Account Info",
    type="primary" if page == PAGE_ACCOUNT_INFO else "secondary",
    use_container_width=True,
    on_click=open_account_info,
)
st.sidebar.button(
    "Settings",
    type="primary" if page == PAGE_SETTINGS else "secondary",
    use_container_width=True,
    on_click=open_settings,
)


# ============ PAGE: CALCULATOR ============

if page == PAGE_CAMPAIGN_BUILDER:
    st.title("Campaign Lab · Create New Campaign")
    st.caption("Model Media, Creator, and Community echoes to compute TEV & ROI.")

    if "wizard_completed" not in st.session_state:
        st.session_state["wizard_completed"] = {step: False for step in WIZARD_STEPS}
    st.session_state.setdefault("campaign_info", {})

    def compute_accessible_steps() -> list[str]:
        accessible: list[str] = []
        for idx, step_name in enumerate(WIZARD_STEPS):
            if idx == 0:
                accessible.append(step_name)
                if not st.session_state["wizard_completed"][step_name]:
                    break
            else:
                prev_steps = WIZARD_STEPS[:idx]
                if all(st.session_state["wizard_completed"][prev] for prev in prev_steps):
                    accessible.append(step_name)
                    if not st.session_state["wizard_completed"][step_name]:
                        break
                else:
                    break
        return accessible

    accessible_steps = compute_accessible_steps()
    if "active_wizard_step" not in st.session_state:
        st.session_state["active_wizard_step"] = accessible_steps[0]
    if st.session_state["active_wizard_step"] not in accessible_steps:
        st.session_state["active_wizard_step"] = accessible_steps[-1]

    wizard_step = st.sidebar.radio(
        "Wizard step",
        accessible_steps,
        index=accessible_steps.index(st.session_state["active_wizard_step"]),
    )
    st.session_state["active_wizard_step"] = wizard_step

    if len(accessible_steps) < len(WIZARD_STEPS):
        next_locked = WIZARD_STEPS[len(accessible_steps)]
        st.sidebar.info(
            f"Complete **{accessible_steps[-1]}** to unlock **{next_locked}**."
        )

    STEPPER_CSS = """
    <style>
    .wizard-stepper {
        margin: 25px 0 15px;
        display: flex;
        gap: 28px;
        padding: 14px 10px;
        border-radius: 999px;
        background: linear-gradient(135deg, #f2f6ff, #ebeefe);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.6), 0 6px 18px rgba(15,28,63,0.08);
    }
    .wizard-step {
        flex: 1;
        text-align: center;
        color: #8b94a8;
        font-weight: 500;
        position: relative;
    }
    .wizard-step::after {
        content: "";
        position: absolute;
        height: 2px;
        width: calc(100% + 20px);
        right: -10px;
        top: 16px;
        background: rgba(143,155,179,0.25);
    }
    .wizard-step:last-child::after {
        display: none;
    }
    .wizard-step .pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 9px 16px;
        border-radius: 999px;
        background: #e7ecf7;
        color: #6b768e;
        font-weight: 600;
        min-width: 120px;
    }
    .wizard-step.active .pill {
        background: linear-gradient(120deg, #6a7bff, #a968ff);
        color: #fff;
        box-shadow: 0 8px 18px rgba(106,123,255,0.25);
    }
    .wizard-step.completed .pill {
        background: #b8c4ff;
        color: #ffffff;
    }
    </style>
    """
    st.markdown(STEPPER_CSS, unsafe_allow_html=True)

    stepper_html = "<div class='wizard-stepper'>"
    for idx, label in enumerate(WIZARD_STEPS, start=1):
        state_class = ""
        if st.session_state["wizard_completed"].get(label):
            state_class = "completed"
        if label == wizard_step:
            state_class = "active"
        stepper_html += f"<div class='wizard-step {state_class}'><div class='pill'>{idx} {label}</div></div>"
    stepper_html += "</div>"
    st.markdown(stepper_html, unsafe_allow_html=True)
    TAB_STYLE = """
    <style>
    .stTabs [data-baseweb="tab"] {
        color: #6b768e;
        font-weight: 500;
        border: none;
        padding: 8px 18px;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: linear-gradient(120deg, #6a7bff, #a968ff);
        color: #ffffff;
        border-radius: 999px;
        box-shadow: 0 6px 16px rgba(106,123,255,0.25);
    }
    .stTabs [data-baseweb="tab"]:not([aria-selected="true"]) {
        background: #f1f3fb;
        border-radius: 999px;
    }
    </style>
    """
    st.markdown(TAB_STYLE, unsafe_allow_html=True)

    def go_to_next_step(current: str) -> None:
        idx = WIZARD_STEPS.index(current)
        if idx + 1 < len(WIZARD_STEPS):
            st.session_state["active_wizard_step"] = WIZARD_STEPS[idx + 1]
            st.rerun()

    if wizard_step == "Campaign Brief":
        st.subheader("1. Campaign Brief")
        stored_info = st.session_state.get("campaign_info", {})
        c1, c2, c3 = st.columns(3)
        with c1:
            campaign_name = st.text_input(
                "Campaign name",
                key="campaign_name",
                value=stored_info.get("campaign_name", ""),
            )
        with c2:
            client = st.text_input(
                "Client / Brand",
                key="campaign_client",
                value=stored_info.get("campaign_client", ""),
            )
        with c3:
            market = st.selectbox(
                "Market / Country",
                MARKET_OPTIONS,
                index=MARKET_OPTIONS.index(stored_info.get("campaign_market", "Thailand"))
                if stored_info.get("campaign_market", "Thailand") in MARKET_OPTIONS
                else 0,
                key="campaign_market",
            )

        c4, c5, c6 = st.columns(3)
        with c4:
            objective_choice = st.selectbox(
                "Primary Objective",
                OBJECTIVE_OPTIONS,
                index=OBJECTIVE_OPTIONS.index(
                    stored_info.get("campaign_objective_choice", "Brand Awareness")
                )
                if stored_info.get("campaign_objective_choice") in OBJECTIVE_OPTIONS
                else 0,
                key="campaign_objective_choice",
                help="Pick the main KPI focus for this campaign.",
            )

        def _coerce_date(raw, fallback):
            if raw is None:
                return fallback
            if isinstance(raw, str):
                try:
                    return date.fromisoformat(raw)
                except ValueError:
                    return fallback
            if isinstance(raw, date):
                return raw
            if hasattr(raw, "date"):
                return raw.date()
            return fallback

        start_default = _coerce_date(stored_info.get("campaign_start_date"), date.today())
        end_default = _coerce_date(
            stored_info.get("campaign_end_date"), start_default + timedelta(days=30)
        )

        with c5:
            duration_from = st.date_input(
                "Campaign start",
                value=start_default,
                key="campaign_start_date",
            )
        with c6:
            duration_to = st.date_input(
                "Campaign end",
                value=end_default,
                key="campaign_end_date",
            )

        objective = st.text_area(
            "Campaign Description",
            key="campaign_objective",
            value=stored_info.get("campaign_objective", ""),
            placeholder="Add nuance about expected outcomes or KPIs.",
        )

        currency = st.selectbox(
            "Budget currency",
            CURRENCY_OPTIONS,
            index=CURRENCY_OPTIONS.index(stored_info.get("campaign_currency", "THB"))
            if stored_info.get("campaign_currency", "THB") in CURRENCY_OPTIONS
            else 0,
            key="campaign_currency",
            help="Default currency is THB.",
        )

        preset_k = float(
            stored_info.get("campaign_investment_k", stored_info.get("campaign_investment", 0.0) / 1000)
        )
        slider_ceiling = preset_k if preset_k > DEFAULT_MAX_INVESTMENT_K else DEFAULT_MAX_INVESTMENT_K
        custom_default = bool(stored_info.get("campaign_custom_mode", False) or preset_k > slider_ceiling)
        custom_mode = st.checkbox(
            "Manually input budget (use for >2M THB/USD)",
            value=custom_default,
            key="campaign_custom_mode",
        )
        if custom_mode:
            inv_k = st.number_input(
                "Investment (INV) in K units",
                min_value=0.0,
                step=10.0,
                key="campaign_investment_k",
                value=preset_k if preset_k > 0 else slider_ceiling,
            )
        else:
            inv_k = st.slider(
                "Investment (INV) in K units",
                min_value=0.0,
                max_value=slider_ceiling,
                step=10.0,
                value=min(preset_k, slider_ceiling),
                key="campaign_investment_k",
            )
        inv = inv_k * 1000

        duration_valid = True
        if duration_to and duration_from and duration_to < duration_from:
            st.error("Campaign end date must be on or after the start date.")
            duration_valid = False

        info_complete = bool(campaign_name and client and inv > 0 and duration_valid)
        st.session_state["wizard_completed"]["Campaign Brief"] = info_complete
        if info_complete:
            if st.button("Next: Echo Studio"):
                st.session_state["campaign_info"] = {
                    "campaign_name": campaign_name,
                    "campaign_client": client,
                    "campaign_market": market,
                    "campaign_objective_choice": objective_choice,
                    "campaign_objective": objective,
                    "campaign_start_date": duration_from,
                    "campaign_end_date": duration_to,
                    "campaign_currency": currency,
                    "campaign_custom_mode": custom_mode,
                    "campaign_investment_k": inv_k,
                    "campaign_investment": inv,
                }
                go_to_next_step("Campaign Brief")
        else:
            st.info("Fill all required fields to continue.")

    elif wizard_step == "Echo Studio":
        st.subheader("2. Echo Studio")
        st.caption("Capture Media, Creator, and Community signals to power the TEV model.")
        status_placeholder = st.empty()

        default_media_cards = [
            {"channel_type": "Online Article", "tier_name": "Major", "mentions": 0},
            {"channel_type": "Online Article", "tier_name": "Industry", "mentions": 0},
            {"channel_type": "Online Article", "tier_name": "Local/Niche", "mentions": 0},
            {"channel_type": "Social Media", "tier_name": "Tier 1", "mentions": 0},
            {"channel_type": "Social Media", "tier_name": "Tier 2", "mentions": 0},
            {"channel_type": "Social Media", "tier_name": "Tier 3", "mentions": 0},
        ]
        st.session_state.setdefault("media_cards", default_media_cards)

        st.session_state.setdefault("creator_cards", [])

        comm_default = pd.DataFrame(
            [
                {
                    "platform": platform,
                    "content_creation": 0,
                    "passive_engagement": 0,
                    "active_engagement": 0,
                    "amplification": 0,
                }
                for platform in COMMUNITY_PLATFORM_OPTIONS
            ]
        )
        st.session_state.setdefault("community_cards", comm_default.to_dict("records"))

        tab_labels = ['Media Echo', 'Creator Echo', 'Community Echo']
        st.session_state.setdefault('_echo_tab_target', 'Media Echo')
        tabs = st.tabs(tab_labels)
        media_tab, creator_tab, community_tab = tabs

        with media_tab:
            st.caption("Log earned media coverage by tier to estimate Media Echo.")
            media_df = pd.DataFrame(st.session_state["media_cards"])
            media_editor = st.data_editor(
                media_df,
                column_config={
                    "channel_type": st.column_config.SelectboxColumn(
                        "Channel Type",
                        options=MEDIA_CHANNEL_OPTIONS,
                        required=True,
                    ),
                    "tier_name": st.column_config.SelectboxColumn(
                        "Tier",
                        options=MEDIA_TIER_PRESETS,
                        required=True,
                    ),
                    "mentions": st.column_config.NumberColumn(
                        "Mentions / Posts",
                        min_value=0.0,
                        step=1.0,
                        format="%.0f",
                        required=True,
                    ),
                },
                hide_index=True,
                num_rows="dynamic",
                use_container_width=True,
                key="media_data_editor",
            )
            col_media_save, col_media_next = st.columns([3, 1])
            with col_media_save:
                if st.button("Save Media Data", key="btn_save_media"):
                    cleaned = pd.DataFrame(media_editor).copy()
                    if cleaned.empty:
                        st.warning("Add at least one row before saving.")
                    else:
                        cleaned["channel_type"] = cleaned["channel_type"].fillna(MEDIA_CHANNEL_OPTIONS[0])
                        cleaned["tier_name"] = cleaned["tier_name"].fillna(MEDIA_TIER_PRESETS[0])
                        cleaned["mentions"] = pd.to_numeric(cleaned["mentions"], errors="coerce").fillna(0.0)
                        st.session_state["media_cards"] = cleaned.to_dict("records")
                        st.session_state["media_editor"] = cleaned
                        st.success("Media Data saved.")
            with col_media_next:
                st.button(
                    "Next tab →",
                    key="btn_media_next",
                    type="secondary",
                    on_click=lambda: st.session_state.update(_echo_tab_target="Creator Echo"),
                )

        with creator_tab:
            st.caption("Capture creator activations manually or via Fanpage Karma upload.")
            tab_upload, tab_manual = st.tabs(["Import Fanpage Karma data", "Manual entry"])
            with tab_upload:
                st.info("Upload your Fanpage Karma data - Top 500 posts export to pre-fill creator data.")
                uploaded = st.file_uploader("Upload .xlsx file", type=["xlsx"], key="creator_upload_primary")
                disabled = uploaded is None
                if st.button("Summarize Uploaded File", disabled=disabled):
                    if uploaded is None:
                        st.error("Attach a file first.")
                    else:
                        try:
                            creator_df, summary = parse_creator_upload(uploaded)
                            st.session_state["creator_cards"] = creator_df.to_dict("records")
                            st.session_state["creator_editor"] = creator_df
                            st.session_state["creator_upload_summary"] = summary
                            st.success("Creator upload parsed successfully.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed to parse upload: {exc}")
                summary = st.session_state.get("creator_upload_summary")
                if summary:
                    platform_lines = ", ".join(
                        f"{platform}: {count}"
                        for platform, count in summary["platform_breakdown"].items()
                    )
                    st.success(
                        f"Parsed {summary['total_posts']} posts from {summary['unique_creators']} creators. "
                        f"Platform breakdown: {platform_lines or 'N/A'}."
                    )
                creator_preview_df = st.session_state.get("creator_editor")
                if isinstance(creator_preview_df, pd.DataFrame) and not creator_preview_df.empty:
                    st.markdown("##### Preview uploaded rows")
                    filt_cols = st.columns(3)
                    with filt_cols[0]:
                        upload_platform_filter = st.selectbox(
                            "Platform filter",
                            ["All"] + CREATOR_PLATFORM_OPTIONS,
                            key="upload_filter_platform",
                        )
                    with filt_cols[1]:
                        upload_content_filter = st.selectbox(
                            "Content type filter",
                            ["All"] + CREATOR_CONTENT_OPTIONS,
                            key="upload_filter_content",
                        )
                    with filt_cols[2]:
                        upload_tier_filter = st.selectbox(
                            "Tier filter",
                            ["All"] + CREATOR_TIER_OPTIONS,
                            key="upload_filter_tier",
                        )

                    filtered = creator_preview_df.copy()
                    if upload_platform_filter != "All":
                        filtered = filtered[filtered["platform"] == upload_platform_filter]
                    if upload_content_filter != "All":
                        filtered = filtered[filtered["content_type"] == upload_content_filter]
                    if upload_tier_filter != "All":
                        filtered = filtered[filtered["tier"] == upload_tier_filter]

                    if filtered.empty:
                        st.info("No rows match the selected filters.")
                    else:
                        st.dataframe(filtered, use_container_width=True)
                col_creator_upload_next = st.columns([3, 1])[1]
                with col_creator_upload_next:
                    st.button(
                        "Next tab →",
                        key="btn_creator_next_from_upload",
                        type="secondary",
                        on_click=lambda: st.session_state.update(_echo_tab_target="Manual entry"),
                    )
            with tab_manual:
                st.session_state.setdefault("creator_cards", [])
                creator_manual_df = pd.DataFrame(st.session_state["creator_cards"])
                if creator_manual_df.empty:
                    creator_manual_df = pd.DataFrame(columns=["platform", "content_type", "tier", "num_posts"])

                st.caption("Pick a platform to add or edit rows. Each save updates only that platform.")
                platform_target = st.selectbox(
                    "Platform to edit",
                    CREATOR_PLATFORM_OPTIONS,
                    key="creator_platform_target",
                )

                platform_rows = merge_platform_rows(creator_manual_df, platform_target)

                filter_cols = st.columns(2)
                with filter_cols[0]:
                    manual_content_filter = st.selectbox(
                        "Content type filter",
                        ["All"] + CREATOR_CONTENT_OPTIONS,
                        key="manual_filter_content",
                    )
                with filter_cols[1]:
                    manual_tier_filter = st.selectbox(
                        "Tier filter",
                        ["All"] + CREATOR_TIER_OPTIONS,
                        key="manual_filter_tier",
                    )

                filter_mask = pd.Series(True, index=platform_rows.index)
                if manual_content_filter != "All":
                    filter_mask &= platform_rows["content_type"] == manual_content_filter
                if manual_tier_filter != "All":
                    filter_mask &= platform_rows["tier"] == manual_tier_filter

                editable_rows = platform_rows[filter_mask].copy()
                if editable_rows.empty:
                    st.info("No rows match the selected filters for this platform. Showing all rows.")
                    editable_rows = platform_rows.copy()
                    filter_mask = pd.Series(True, index=platform_rows.index)

                creator_editor = st.data_editor(
                    editable_rows[["content_type", "tier", "num_posts"]],
                    column_config={
                        "content_type": st.column_config.SelectboxColumn(
                            "Content Type",
                            options=CREATOR_CONTENT_OPTIONS,
                            required=True,
                        ),
                        "tier": st.column_config.SelectboxColumn(
                            "Tier",
                            options=CREATOR_TIER_OPTIONS,
                            required=True,
                        ),
                        "num_posts": st.column_config.NumberColumn(
                            "Number of posts",
                            min_value=0.0,
                            step=1.0,
                            format="%.0f",
                            required=True,
                        ),
                    },
                    hide_index=True,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="creator_data_editor",
                )
                save_label = f"Save {platform_target} entries"
                if st.button(save_label, key="btn_save_creator"):
                    cleaned = pd.DataFrame(creator_editor).copy()
                    if cleaned.empty:
                        st.warning("Add at least one row before saving.")
                    else:
                        cleaned["num_posts"] = pd.to_numeric(cleaned["num_posts"], errors="coerce").fillna(0.0)
                        cleaned["platform"] = platform_target
                        subset_index = editable_rows.index
                        platform_rows.loc[subset_index, ["content_type", "tier", "num_posts"]] = cleaned[
                            ["content_type", "tier", "num_posts"]
                        ].values
                        updated = creator_manual_df[creator_manual_df["platform"] != platform_target]
                        updated = pd.concat([updated, platform_rows], ignore_index=True)
                        st.session_state["creator_cards"] = updated.to_dict("records")
                        st.session_state["creator_editor"] = updated
                        st.success(f"{platform_target} entries saved.")
                st.button(
                    "Next tab →",
                    key="btn_creator_to_community",
                    type="secondary",
                    on_click=lambda: st.session_state.update(_echo_tab_target="Community Echo"),
                )
            creator_preview = st.session_state.get("creator_editor")
            if isinstance(creator_preview, pd.DataFrame) and not creator_preview.empty:
                st.markdown("##### Current creator table")
                st.dataframe(creator_preview, use_container_width=True)

        with community_tab:
            st.caption("Quantify owned-community contribution to the echo.")
            community_columns = [
                (
                    "content_creation",
                    "Content Creation",
                    "Number of new posts/videos produced by the community.",
                ),
                (
                    "passive_engagement",
                    "Passive Engagement",
                    "Surface-level interactions such as likes or reactions.",
                ),
                (
                    "active_engagement",
                    "Active Engagement",
                    "Deeper interactions including comments and replies.",
                ),
                (
                    "amplification",
                    "Amplification",
                    "Re-distribution actions like shares or retweets.",
                ),
            ]
            community_df_raw = pd.DataFrame(st.session_state["community_cards"])
            community_df = ensure_community_rows(community_df_raw)
            if len(community_df) != len(community_df_raw):
                st.session_state["community_cards"] = community_df.to_dict("records")
            community_editor = st.data_editor(
                community_df,
                column_config={
                    "platform": st.column_config.SelectboxColumn(
                        "Platform",
                        options=COMMUNITY_PLATFORM_OPTIONS,
                        required=True,
                    ),
                    **{
                        col: st.column_config.NumberColumn(
                            label,
                            min_value=0.0,
                            step=1.0,
                            format="%.0f",
                            required=True,
                            help=help_text,
                        )
                        for col, label, help_text in community_columns
                    },
                },
                hide_index=True,
                num_rows="dynamic",
                use_container_width=True,
                key="community_data_editor",
            )
            col_comm_save, col_comm_next = st.columns([3, 1])
            with col_comm_save:
                save_clicked = st.button("Save Community Data", key="btn_save_community")
            with col_comm_next:
                st.button(
                    "Next tab →",
                    key="btn_community_to_report",
                    type="secondary",
                    on_click=lambda: st.session_state.update(_echo_tab_target="Community Echo"),
                )
            if save_clicked:
                cleaned = pd.DataFrame(community_editor).copy()
                if cleaned.empty:
                    st.warning("Add at least one row before saving.")
                else:
                    for col, _, _ in community_columns:
                        cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce").fillna(0.0)
                    st.session_state["community_cards"] = cleaned.to_dict("records")
                    st.session_state["community_editor"] = cleaned
                    st.success("Community Data saved.")

        media_ready = isinstance(st.session_state.get("media_editor"), pd.DataFrame)
        creator_ready = isinstance(st.session_state.get("creator_editor"), pd.DataFrame) or (
            "creator_upload_summary" in st.session_state
        )
        community_ready = isinstance(st.session_state.get("community_editor"), pd.DataFrame)
        inputs_complete = bool(media_ready and creator_ready and community_ready)
        st.session_state["wizard_completed"]["Echo Studio"] = inputs_complete
        if inputs_complete:
            status_placeholder.success("All inputs captured. Continue to Echo Impact Report when ready.")
            if st.button("Next: Echo Impact Report"):
                go_to_next_step("Echo Studio")
        else:
            status_placeholder.info("Provide media, creator, and community data to continue.")

    elif wizard_step == "Echo Impact Report":
        st.subheader("3. Echo Impact Report")
        campaign_data = st.session_state.get("campaign_info", {})
        campaign_name = campaign_data.get("campaign_name", "")
        client = campaign_data.get("campaign_client", "")
        market = campaign_data.get("campaign_market", "")
        objective_choice = campaign_data.get("campaign_objective_choice", "")
        objective = campaign_data.get("campaign_objective", "")
        currency = campaign_data.get("campaign_currency", "THB")
        inv = campaign_data.get("campaign_investment", 0.0)
        inv_k = campaign_data.get("campaign_investment_k")
        if inv_k is None:
            inv_k = inv / 1000 if inv else 0.0

        def _format_date(value):
            if value is None:
                return "N/A"
            if isinstance(value, str):
                return value
            try:
                return value.strftime("%Y-%m-%d")
            except AttributeError:
                return str(value)

        start_label = _format_date(campaign_data.get("campaign_start_date"))
        end_label = _format_date(campaign_data.get("campaign_end_date"))
        st.write(
            f"- **Campaign:** {campaign_name or 'N/A'}  \n"
            f"- **Client:** {client or 'N/A'}  \n"
            f"- **Market:** {market or 'N/A'}  \n"
            f"- **Objective:** {objective_choice or objective or 'N/A'}  \n"
            f"- **Duration:** {start_label} -> {end_label}  \n"
            f"- **Investment:** {currency} {inv_k:,.1f}K"
        )
        st.info("Review Data and click Calculate when ready.")

        media_df = st.session_state.get("media_editor", pd.DataFrame())
        creator_df = st.session_state.get("creator_editor", pd.DataFrame())
        comm_df = st.session_state.get("community_editor", pd.DataFrame())

        st.markdown("---")
        calc_clicked = st.button("Calculate", type="primary")

        if calc_clicked:
            if inv <= 0:
                st.error("Investment (INV) must be greater than 0.")
            else:
                result = calculate_campaign(inv, media_df, creator_df, comm_df)
                st.session_state["last_result"] = result
                st.session_state["last_inv"] = inv
                st.session_state["last_campaign_name"] = campaign_name
                st.session_state["last_client"] = client
                st.session_state["last_market"] = market

        if "last_result" in st.session_state:
            result = st.session_state["last_result"]

            st.subheader("Results")
            c1, c2, c3 = st.columns(3)
            c1.metric("Media Echo Value", f"{result['media']:,.0f}")
            c2.metric("Creator Echo Value", f"{result['creator']:,.0f}")
            c3.metric("Community Echo Value", f"{result['community']:,.0f}")

            c4, c5, c6 = st.columns(3)
            c4.metric("Total Echo Value (TEV)", f"{result['tev']:,.0f}")
            c5.metric("ROIM (TEV / INV)", f"{result['roi_m']:.2f}")
            c6.metric("ROI %", f"{result['roi_pct']:.2f}%")

            breakdown_df = pd.DataFrame(
                {
                    "Component": ["Media", "Creator", "Community"],
                    "Value": [result["media"], result["creator"], result["community"]],
                }
            ).set_index("Component")
            st.bar_chart(breakdown_df)

            st.markdown("### Save Campaign")
            if not campaign_name or not client:
                st.info("Enter *Campaign name* and *Client / Brand* above to enable saving.")
            else:
                if st.button("Save this campaign to local database"):
                    try:
                        save_campaign(
                            result,
                            st.session_state.get("last_inv", inv),
                            campaign_name,
                            client,
                            market,
                        )
                        st.success("Campaign saved! View it anytime in the Campaign Performance.")
                    except Exception as e:
                        st.error(f"Failed to save campaign: {e}")

            st.markdown("---")
            col_new, col_library = st.columns(2)
            with col_new:
                if st.button("Start a new campaign", key="btn_new_campaign"):
                    start_new_campaign()
                    st.rerun()
            with col_library:
                if st.button("Review saved campaigns", key="btn_view_library"):
                    open_campaign_library()
                    st.rerun()


# ============ PAGE: Campaign Performance ============

elif page == PAGE_CAMPAIGN_LIBRARY:
    st.title("Campaign Performance")
    st.caption("Review saved TEV analyses and ROI benchmarks.")

    try:
        df = fetch_campaigns(owner_id=st.session_state["user"]["id"])
    except Exception as e:
        st.error(f"Failed to load campaigns: {e}")
        st.stop()

    if df.empty:
        st.info(
            "No campaigns saved yet. Use **Create New Campaign** in the Campaign Lab to model a campaign "
            "and save it to see it here."
        )
    else:
        st.subheader("Filters")
        col1, col2, col3 = st.columns(3)
        with col1:
            clients = ["All"] + sorted(df["client"].dropna().unique().tolist())
            client_filter = st.selectbox("Client", clients, index=0)
        with col2:
            markets = ["All"] + sorted(df["market"].dropna().unique().tolist())
            market_filter = st.selectbox("Market", markets, index=0)
        with col3:
            campaigns = ["All"] + sorted(df["campaign_name"].dropna().unique().tolist())
            campaign_filter = st.selectbox("Campaign", campaigns, index=0)

        filtered_df = df.copy()
        if client_filter != "All":
            filtered_df = filtered_df[filtered_df["client"] == client_filter]
        if market_filter != "All":
            filtered_df = filtered_df[filtered_df["market"] == market_filter]
        if campaign_filter != "All":
            filtered_df = filtered_df[filtered_df["campaign_name"] == campaign_filter]

        display_df = filtered_df.copy()
        if "objective_focus" in display_df.columns:
            focus_series = display_df["objective_focus"]
            if "objective" in display_df.columns:
                focus_series = focus_series.fillna(display_df["objective"])
            display_df["Objective Focus"] = focus_series.fillna("")
        elif "objective" in display_df.columns:
            display_df["Objective Focus"] = display_df["objective"].fillna("")
        else:
            display_df["Objective Focus"] = ""

        if "campaign_start" in display_df.columns:
            display_df["Campaign Start"] = (
                pd.to_datetime(display_df["campaign_start"], errors="coerce").dt.strftime("%Y-%m-%d")
            )
        else:
            display_df["Campaign Start"] = ""
        if "campaign_end" in display_df.columns:
            display_df["Campaign End"] = (
                pd.to_datetime(display_df["campaign_end"], errors="coerce").dt.strftime("%Y-%m-%d")
            )
        else:
            display_df["Campaign End"] = ""

        if "investment_k" in display_df.columns:
            display_df["Investment (K)"] = display_df["investment_k"].fillna(
                display_df["investment"] / 1000
            )
        else:
            display_df["Investment (K)"] = display_df["investment"] / 1000

        if "currency" in display_df.columns:
            display_df["Currency"] = display_df["currency"].fillna("THB")
        else:
            display_df["Currency"] = "THB"

        columns_to_show = [
            "campaign_name",
            "client",
            "market",
            "Objective Focus",
            "Campaign Start",
            "Campaign End",
            "Currency",
            "Investment (K)",
            "media_echo",
            "creator_echo",
            "community_echo",
            "tev",
            "roi_pct",
        ]
        existing_columns = [col for col in columns_to_show if col in display_df.columns]

        st.subheader("Campaign Table")
        st.dataframe(display_df[existing_columns], width="stretch")

        if filtered_df.empty:
            st.warning("No campaigns match the current filters.")
        else:
            st.subheader("Summary KPIs")
            c1, c2, c3 = st.columns(3)
            c1.metric("Total TEV", f"{filtered_df['tev'].sum():,.0f}")
            c2.metric("Average ROI %", f"{filtered_df['roi_pct'].mean():.1f}%")
            c3.metric("Number of Campaigns", len(filtered_df))

            st.subheader("TEV by Campaign")
            tev_chart_df = filtered_df.set_index("campaign_name")[["tev"]]
            st.bar_chart(tev_chart_df)

            st.subheader("ROI % by Campaign")
            roi_chart_df = filtered_df.set_index("campaign_name")[["roi_pct"]]
            st.bar_chart(roi_chart_df)


elif page == PAGE_ACCOUNT_INFO:
    st.title("Account Info")
    user = st.session_state.get("user")
    if not user:
        st.info("You are not signed in. Please sign in to view account information.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Name", user.get("name") or "—")
            st.metric("Company", user.get("company") or "—")
        with col2:
            st.metric("Email", user.get("email") or "—")
            st.metric("Team", user.get("team") or "—")
        st.write("### Recent Activity")
        st.write(
            f"- Last login: {user.get('last_login', 'N/A')}  \n"
            f"- Role: {user.get('role', 'member')}"
        )


elif page == PAGE_SETTINGS:
    st.title("Settings")
    st.write("Configure your workspace preferences.")

    st.subheader("Notifications")
    st.checkbox("Email me when a teammate shares a campaign.", key="setting_notify_share")
    st.checkbox("Send a weekly TEV performance digest.", key="setting_notify_digest")

    st.subheader("Data Preferences")
    st.selectbox(
        "Default currency display",
        CURRENCY_OPTIONS,
        key="setting_currency",
    )
    st.select_slider(
        "Default ROI precision",
        options=["1 decimal", "2 decimals", "3 decimals"],
        key="setting_roi_precision",
    )

