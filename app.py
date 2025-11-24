import os
import base64
from datetime import date, timedelta
from pathlib import Path
from typing import Any, BinaryIO

import altair as alt
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
except ImportError:  # optional dependency
    plt = None
    sns = None
try:
    from streamlit_echarts import st_echarts
except ImportError:  # optional dependency
    st_echarts = None
import pandas as pd
import streamlit as st

from auth import hash_password, verify_password
from db import (
    create_user,
    fetch_campaigns,
    fetch_creator_rows,
    fetch_media_rows,
    fetch_community_rows,
    get_user_by_email,
    insert_campaign,
    insert_creator_rows,
    replace_media_rows,
    replace_community_rows,
    replace_creator_rows,
    update_campaign,
    update_last_login,
)
from logic.calculator import calculate_campaign

# ------------ BASIC CONFIG ------------

st.set_page_config(
    page_title="Vero Echo Effect Tool",
    layout="wide",
)

# ------------ VERO DESIGN TOKENS ------------
VERO_PRIMARY = "#0a6cc2"
VERO_PRIMARY_SOFT = "#fbf9e5"
VERO_DARK = "#0a223a"
VERO_TEXT_MUTED = "#6b7280"
VERO_BORDER = "#d9dee7"
VERO_CARD_BG = "#ffffff"
VERO_PAGE_BG = "#f4f6fb"
VERO_ACCENT = "#4bb7e5"

BORDER_RADIUS = "16px"
SHADOW_SOFT = "0 10px 25px rgba(15, 23, 42, 0.08)"
FONT_FAMILY = "'TT Commons Pro', 'TT Commons', sans-serif"


def _embed_tt_commons() -> None:
    """Embed TT Commons Pro woff2 fonts as base64 for consistent display."""
    font_dir = Path("static/font/TT Common Pro/woff2")
    variants = {
        "400": "TT_Commons_Pro_Regular.woff2",
        "500": "TT_Commons_Pro_Medium.woff2",
        "700": "TT_Commons_Pro_Bold.woff2",
    }
    css_parts: list[str] = []
    for weight, filename in variants.items():
        font_path = font_dir / filename
        try:
            font_data = font_path.read_bytes()
        except FileNotFoundError:
            continue
        b64 = base64.b64encode(font_data).decode("utf-8")
        css_parts.append(
            f"""
            @font-face {{
                font-family: 'TT Commons Pro';
                src: url(data:font/woff2;base64,{b64}) format('woff2');
                font-weight: {weight};
                font-style: normal;
                font-display: swap;
            }}
            """
        )
    if css_parts:
        st.markdown(f"<style>{''.join(css_parts)}</style>", unsafe_allow_html=True)

# Global base styles (embed font first)
_embed_tt_commons()

st.markdown(
    f"""
    <style>
    html, body, .stApp {{
        background: {VERO_PAGE_BG};
        font-family: {FONT_FAMILY};
        color: {VERO_DARK};
    }}
    h1, h2, h3, h4 {{
        color: {VERO_DARK};
        letter-spacing: 0.04em;
    }}
    .vero-panel {{
        background: {VERO_CARD_BG};
        border-radius: {BORDER_RADIUS};
        border: 1px solid {VERO_BORDER};
        box-shadow: {SHADOW_SOFT};
        padding: 18px 20px;
        margin-bottom: 16px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

METRIC_CARD_CSS = f"""
<style>
.metric-row {{
    margin: 6px 0 12px;
}}
.metric-row [data-testid="stMarkdownContainer"] {{
    width: 100%;
    height: 100%;
}}
.metric-card {{
    background: linear-gradient(180deg, {VERO_CARD_BG} 0%, #f8fbff 100%);
    border-radius: {BORDER_RADIUS};
    padding: 14px 16px;
    border: 1px solid rgba(217, 222, 231, 0.9);
    box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
    min-height: 140px;
    width: 100%;
    height: 100%;
}}
.metric-label {{
    font-size: 10px;
    font-weight: 600;
    color: {VERO_TEXT_MUTED};
    letter-spacing: 0.16em;
    text-transform: uppercase;
}}
.metric-value {{
    margin-top: 6px;
    font-size: 30px;
    font-weight: 800;
    color: {VERO_DARK};
}}
.metric-sub {{
    margin-top: 2px;
    font-size: 10px;
    color: #9ca3af;
}}
</style>
"""


def render_kpi_row(card_items: list[tuple[str, str, str]], cols_in_row: int = 4) -> None:
    st.markdown(METRIC_CARD_CSS, unsafe_allow_html=True)
    for i in range(0, len(card_items), cols_in_row):
        row = card_items[i : i + cols_in_row]
        cols = st.columns(len(row))
        for col, (label, main, sub) in zip(cols, row):
            sub_html = sub if sub else "&nbsp;"
            with col:
                st.markdown(
                    f"""
                    <div class="metric-card" title="{sub}">
                        <div class="metric-label">{label}</div>
                        <div class="metric-value">{main}</div>
                        <div class="metric-sub">{sub_html}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_app_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="app-shell">
          <div class="app-header">
            <div class="app-header-left">
                <div class="app-header-logo"></div>
                <div>
                    <div class="app-header-title">{title}</div>
                    <div class="app-header-sub">{subtitle}</div>
                </div>
            </div>
            <div class="app-header-shape"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _fmt_compact(num: float) -> str:
    try:
        val = float(num)
    except Exception:
        return "0"
    if abs(val) >= 1_000_000:
        return f"{val/1_000_000:.1f} M"
    if abs(val) >= 1_000:
        return f"{val/1_000:.1f} K"
    return f"{val:,.0f}"

# Ensure data dir exists
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

if "user" not in st.session_state:
    st.session_state["user"] = None
st.session_state.setdefault("show_register", False)
st.session_state.setdefault("show_forgot", False)
st.session_state.setdefault("remember_me_email", "")
st.session_state.setdefault("campaign_info", {})
st.session_state.setdefault("editing_campaign_id", None)


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
    st.session_state["editing_campaign_id"] = None
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
PLATFORMS_DISALLOW_STATIC = {"TikTok", "YouTube"}
CREATOR_TIER_OPTIONS = ["Mega", "Macro", "Mid-tier", "Micro", "Nano"]
COMMUNITY_PLATFORM_OPTIONS = ["Facebook", "Instagram", "TikTok", "YouTube", "X (Twitter)", "Other"]
WIZARD_STEPS = ["Campaign Brief", "Echo Studio", "Echo Impact Report"]


def get_allowed_content_options(platform: str) -> list[str]:
    if platform in PLATFORMS_DISALLOW_STATIC:
        return ["Video Post"]
    return CREATOR_CONTENT_OPTIONS


def get_creator_presets(platform: str) -> list[dict[str, Any]]:
    allowed_content = get_allowed_content_options(platform)
    combos = [
        (content, tier)
        for content in allowed_content
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
    allowed_content = get_allowed_content_options(platform)
    merged["content_type"] = merged["content_type"].where(
        merged["content_type"].isin(allowed_content),
        allowed_content[0],
    )
    merged = (
        merged.groupby(["platform", "content_type", "tier"], as_index=False)["num_posts"]
        .sum()
    )
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


# App-level assets (after helper is defined)
APP_SHAPE_B64 = load_base64_image(os.path.join("static", "img", "element_shape.png"))
APP_LOGO_B64 = load_base64_image(os.path.join("static", "img", "logo_vero_white.png"))


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
    working["content_type"] = working.apply(
        lambda row: row["content_type"]
        if row["content_type"] in get_allowed_content_options(row["platform"])
        else get_allowed_content_options(row["platform"])[0],
        axis=1,
    )
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


def _coerce_date_value(raw, fallback: date) -> date:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return fallback
    if isinstance(raw, date):
        return raw
    try:
        return pd.to_datetime(raw).date()
    except Exception:
        return fallback


def save_campaign(result: dict[str, float],
                  inv: float,
                  campaign_name: str,
                  client: str,
                  market: str | None = None,
                  campaign_id: int | None = None) -> int:
    owner = st.session_state.get("user") if "user" in st.session_state else None
    owner_id = owner.get("id") if isinstance(owner, dict) else None
    info = st.session_state.get("campaign_info", {})
    payload = {
        "campaign_name": campaign_name,
        "client": client,
        "market": market or "",
        "objective": info.get("campaign_objective"),
        "objective_focus": info.get("campaign_objective_choice"),
        "campaign_start": _serialize_date(info.get("campaign_start_date")),
        "campaign_end": _serialize_date(info.get("campaign_end_date")),
        "currency": info.get("campaign_currency"),
        "investment": inv,
        "investment_k": info.get("campaign_investment_k"),
        "custom_budget_flag": info.get("campaign_custom_mode", False),
        "media_echo": result["media"],
        "creator_echo": result["creator"],
        "community_echo": result["community"],
        "tev": result["tev"],
        "roi_m": result["roi_m"],
        "roi_pct": result["roi_pct"],
    }
    if campaign_id:
        update_campaign(campaign_id, payload)
    else:
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
    creator_df = st.session_state.get("creator_editor", pd.DataFrame())
    media_df = st.session_state.get("media_editor", pd.DataFrame())
    community_df = st.session_state.get("community_editor", pd.DataFrame())

    def _rows_from_df(df: pd.DataFrame, field_map: dict[str, str]) -> list[dict[str, Any]]:
        if not isinstance(df, pd.DataFrame):
            try:
                df = pd.DataFrame(df)
            except Exception:
                return []
        if df.empty:
            return []
        normalized = df.copy()
        normalized = normalized.rename(columns=field_map)
        return normalized.to_dict("records")

    creator_rows = _rows_from_df(
        creator_df,
        {
            "content_type": "content_type",
            "tier": "tier",
            "platform": "platform",
            "num_posts": "num_posts",
            "rate": "rate",
        },
    )
    media_rows = _rows_from_df(
        media_df,
        {
            "channel_type": "channel_type",
            "tier_name": "tier_name",
            "mentions": "mentions",
        },
    )
    community_rows = _rows_from_df(
        community_df,
        {
            "platform": "platform",
            "content_creation": "content_creation",
            "passive_engagement": "passive_engagement",
            "active_engagement": "active_engagement",
            "amplification": "amplification",
        },
    )

    if creator_rows:
        creator_rows = [
            {**row, "source_campaign_id": None} | {"num_posts": row.get("num_posts", 0), "rate": row.get("rate", 0)}
            for row in creator_rows
        ]
    if media_rows:
        media_rows = [{**row, "source_campaign_id": None} for row in media_rows]
    if community_rows:
        community_rows = [{**row, "source_campaign_id": None} for row in community_rows]

    replace_creator_rows(campaign_id, creator_rows)
    replace_media_rows(campaign_id, media_rows)
    replace_community_rows(campaign_id, community_rows)
    return campaign_id


def render_auth():
    logo_color = load_base64_image(os.path.join("static", "img", "logo_vero_color.png"))

    # Inline CSS for a simple centered login card
    st.markdown(
        f"""
        <style>
        body {{
            background: #f5f7fb;
        }}
        /* Card shell wraps the whole auth block */
        .login-card-shell > div {{
            width: 520px;
            max-width: 520px;
            background: #ffffff;
            border-radius: 14px;
            border: 1px solid #e7ebf3;
            box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
            padding: 28px 30px 24px;
            text-align: left;
            margin: 32px auto;
        }}
        .login-logo {{
            display: flex;
            justify-content: center;
            margin-bottom: 14px;
        }}
        .login-logo img {{
            height: 34px;
        }}
        .login-title {{
            margin: 0 0 6px;
            font-size: 20px;
            font-weight: 700;
            color: #0a223a;
        }}
        .login-subtitle {{
            margin: 0 0 16px;
            font-size: 13px;
            color: #6b7280;
        }}
        .login-panel .stTextInput label {{
            font-size: 12px;
            font-weight: 600;
            color: #4b5563;
        }}
        .login-panel .stTextInput input {{
            background: #fbfdff;
            border-radius: 10px !important;
        }}
        .btn-primary {{
            background: #5f9df8;
            color: #fff;
            border: none;
            padding: 12px 14px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 700;
            width: 100%;
        }}
        .text-link {{
            color: #0b5ed7;
            text-decoration: none;
            font-weight: 600;
            font-size: 12px;
        }}
        .login-footer-links {{
            margin-top: 12px;
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #4b5563;
        }}
        .link-muted {{
            border: none;
            background: transparent;
            color: #0b5ed7;
            font-weight: 600;
            cursor: pointer;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    logo_color_html = f'<img src="data:image/png;base64,{logo_color}" alt="Vero" />' if logo_color else ""

    show_register = st.session_state.get("show_register", False)
    show_forgot = st.session_state.get("show_forgot", False)

    card = st.container()
    with card:
        st.markdown("<div class='login-card-shell login-panel'>", unsafe_allow_html=True)
        st.markdown(f"<div class='login-logo'>{logo_color_html}</div>", unsafe_allow_html=True)

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
            st.markdown("<h3>Welcome back</h3>", unsafe_allow_html=True)
            st.markdown(
                "<p class='login-subtitle'>Sign in with your Vero email to access campaign labs.</p>",
                unsafe_allow_html=True,
            )
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
                col_a, col_b = st.columns([1, 1])
                with col_a:
                    remember_me = st.checkbox(
                        "Remember me",
                        value=bool(st.session_state.get("remember_me_email")),
                        key="remember_me",
                    )
                submitted = st.form_submit_button("Sign in", use_container_width=True)

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
                        st.session_state["active_page"] = PAGE_CAMPAIGN_BUILDER
                        st.success("Welcome back!")
                        st.rerun()
            if st.button("Forgot password?", type="secondary", use_container_width=True):
                st.session_state["show_forgot"] = True
                st.rerun()

            st.markdown(
                """
                <div class="login-footer-links">
                    <span>Don't have access yet?</span>
                    <button class="link-muted" onclick="window.location.reload()">Request an account</button>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.button(
                "Create Account",
                on_click=lambda: st.session_state.update(show_register=True),
                key="cta_register",
                use_container_width=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

if st.session_state["user"] is None:
    render_auth()
    st.stop()

# App chrome styling (post-login)
app_bg_css = f"""
<style>
.stApp {{
    background: {VERO_PAGE_BG};
    font-family: {FONT_FAMILY};
}}
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #0bf4f6 0%, #0a6cc2 65%, #0b295c 100%);
    color: #0b295c;
}}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{
    color: #391454;
}}
section[data-testid="stSidebar"] .stButton > button:disabled,
section[data-testid="stSidebar"] .stButton > button[disabled],
section[data-testid="stSidebar"] [data-baseweb="button"][disabled],
section[data-testid="stSidebar"] [role="button"][aria-disabled="true"] {{
    color: #0f172a !important;
    background: #dfe8fb !important;
    border: 1px solid #b9c9ef !important;
    opacity: 0.6 !important;
    box-shadow: none !important;
    filter: none !important;
}}
section[data-testid="stSidebar"] .stButton button {{
    font-weight: 600;
}}
section[data-testid="stSidebar"] .stRadio label {{
    color: #f5f7fb !important;
    font-weight: 600;
}}
section[data-testid="stSidebar"] .stRadio [role="radio"][aria-checked="false"] p {{
    color: #d8e2f5 !important;
}}
.app-shell {{
    padding: 1.5rem 1.5rem 0.5rem;
}}
.app-header {{
    position: relative;
    border-radius: 18px;
    background: linear-gradient(120deg, #0b295c, #0a6cc2);
    padding: 1rem 1.5rem;
    margin-bottom: 1.25rem;
    color: #ffffff;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: space-between;
}}
.app-header-left {{
    display: flex;
    align-items: center;
    gap: 0.85rem;
}}
.app-header-logo {{
    width: 120px;
    height: 32px;
    background-image: url("data:image/png;base64,{APP_LOGO_B64 or ''}");
    background-repeat: no-repeat;
    background-size: contain;
    background-position: left center;
}}
.app-header-title {{
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    opacity: 0.95;
}}
.app-header-sub {{
    font-size: 13px;
    opacity: 0.85;
}}
.app-header-shape {{
    position: absolute;
    right: -50px;
    top: -80px;
    width: 260px;
    height: 260px;
    background-image: url("data:image/png;base64,{APP_SHAPE_B64 or ''}");
    background-repeat: no-repeat;
    background-size: contain;
    opacity: 0.6;
    pointer-events: none;
}}
@media (max-width: 768px) {{
    .app-header {{
        padding: 1rem;
        border-radius: 0 0 16px 16px;
    }}
    .app-header-title {{
        font-size: 16px;
    }}
    .app-header-shape {{
        right: -70px;
        top: -100px;
        width: 220px;
    }}
}}
</style>
"""
st.markdown(app_bg_css, unsafe_allow_html=True)

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
    # ---------- Wizard state ----------
    if "wizard_completed" not in st.session_state:
        st.session_state["wizard_completed"] = {step: False for step in WIZARD_STEPS}
    st.session_state.setdefault("campaign_info", {})
    st.session_state.setdefault("active_wizard_step", WIZARD_STEPS[0])

    def compute_accessible_steps() -> list[str]:
        """
        Only allow linear progress:
        * step 1 is always accessible
        * step N is accessible when all previous steps are completed
        """
        completed = st.session_state["wizard_completed"]
        accessible: list[str] = []
        for idx, step_name in enumerate(WIZARD_STEPS):
            if idx == 0:
                accessible.append(step_name)
                if not completed.get(step_name, False):
                    break
            else:
                prev_steps = WIZARD_STEPS[:idx]
                if all(completed.get(prev, False) for prev in prev_steps):
                    accessible.append(step_name)
                    if not completed.get(step_name, False):
                        break
                else:
                    break
        return accessible

    accessible_steps = compute_accessible_steps()

    # ensure active step is always within accessible steps
    active_step = st.session_state.get("active_wizard_step", WIZARD_STEPS[0])
    if active_step not in accessible_steps:
        active_step = accessible_steps[-1]
        st.session_state["active_wizard_step"] = active_step

    # sidebar controller (simple + reliable)
    wizard_step = st.sidebar.radio(
        "Wizard step",
        accessible_steps,
        index=accessible_steps.index(active_step),
    )
    st.session_state["active_wizard_step"] = wizard_step

    if len(accessible_steps) < len(WIZARD_STEPS):
        next_locked = WIZARD_STEPS[len(accessible_steps)]
        st.sidebar.info(
            f"Complete **{accessible_steps[-1]}** to unlock **{next_locked}**."
        )

    # ---------- Visual stepper (top of page) ----------
    STEPPER_CSS = f"""
    <style>
    .wizard-shell {{
        margin: 18px 0 16px;
    }}
    .wizard-stepper {{
        display: flex;
        gap: 12px;
        padding: 12px 14px;
        border-radius: 999px;
        background: linear-gradient(135deg, {VERO_PRIMARY_SOFT}, #f2f6ff);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.8),
                    0 10px 24px rgba(10, 108, 194, 0.08);
        width: 100%;
        box-sizing: border-box;
    }}
    .wizard-step {{
        flex: 1;
        position: relative;
        text-align: center;
        font-family: {FONT_FAMILY};
        color: {VERO_TEXT_MUTED};
    }}

    /* connector line between steps */
    .wizard-step:not(:last-child)::after {{
        content: "";
        position: absolute;
        top: 50%;
        right: -6px;
        height: 2px;
        width: 12px;
        background: rgba(13, 108, 194, 0.25);
        transform: translateY(-50%);
    }}

    .wizard-pill {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 9px 14px;
        border-radius: 999px;
        background: #e7edf8;
        width: 100%;
        border: 1px solid rgba(13, 108, 194, 0.25);
        box-shadow: 0 6px 14px rgba(10, 108, 194, 0.15);
    }}

    .wizard-index {{
        min-width: 22px;
        height: 22px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 800;
        color: #0f172a;
        background: #ffffff;
        box-shadow: 0 1px 2px rgba(15,23,42,0.1);
    }}

    .wizard-label {{
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }}

    /* ACTIVE step */
    .wizard-step.active .wizard-pill {{
        background: linear-gradient(120deg, {VERO_PRIMARY}, {VERO_ACCENT});
        border-color: transparent;
        color: #ffffff;
        box-shadow: 0 12px 26px rgba(10, 108, 194, 0.35);
    }}
    .wizard-step.active .wizard-index {{
        background: #ffffff;
        color: {VERO_PRIMARY};
    }}

    /* COMPLETED step */
    .wizard-step.completed .wizard-pill {{
        background: #dbeafe;
        border-color: #bfdbfe;
        color: #1d4ed8;
    }}
    .wizard-step.completed .wizard-index {{
        background: #1d4ed8;
        color: #ffffff;
    }}

    /* UPCOMING but unlocked step */
    .wizard-step.upcoming .wizard-pill {{
        background: #e7edf8;
        border-style: solid;
        opacity: 0.95;
    }}

    /* LOCKED step */
    .wizard-step.disabled .wizard-pill {{
        background: #eef1f7;
        border-style: dashed;
        opacity: 0.7;
    }}
    .wizard-step.disabled .wizard-index {{
        background: #f3f4f6;
        color: #9ca3af;
    }}
    </style>
    """
    st.markdown(STEPPER_CSS, unsafe_allow_html=True)

    def render_wizard_stepper(current_step: str, completed: dict[str, bool], accessible: list[str]) -> None:
        html_parts = ["<div class='wizard-shell'><div class='wizard-stepper'>"]
        for idx, label in enumerate(WIZARD_STEPS, start=1):
            if completed.get(label, False):
                state_class = "completed"
                index_text = "✔"
            elif label == current_step:
                state_class = "active"
                index_text = "●"
            elif label in accessible:
                state_class = "upcoming"
                index_text = str(idx)
            else:
                state_class = "disabled"
                index_text = str(idx)

            html_parts.append(
                f"<div class=\"wizard-step {state_class}\">"
                f"<div class=\"wizard-pill\">"
                f"<div class=\"wizard-index\">{index_text}</div>"
                f"<div class=\"wizard-label\">{label}</div>"
                f"</div></div>"
            )
        html_parts.append("</div></div>")
        st.markdown("".join(html_parts), unsafe_allow_html=True)

    render_app_header("Campaign Lab", "Create & simulate echo-driven campaigns")
    # render visual stepper at top of page
    render_wizard_stepper(
        current_step=wizard_step,
        completed=st.session_state["wizard_completed"],
        accessible=accessible_steps,
    )

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

        tab_labels = ["Media Echo", "Creator Echo", "Community Echo"]
        st.session_state.setdefault("active_echo_tab", tab_labels[0])
        active_tab = st.radio("Echo sections", tab_labels, horizontal=True, key="active_echo_tab")

        def go_next_tab(current_label: str) -> None:
            if current_label not in tab_labels:
                return
            idx = tab_labels.index(current_label)
            if idx + 1 < len(tab_labels):
                st.session_state["active_echo_tab"] = tab_labels[idx + 1]
                st.rerun()

        if active_tab == "Media Echo":
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
            cleaned_media = pd.DataFrame(media_editor).copy()
            cleaned_media["channel_type"] = cleaned_media["channel_type"].fillna(MEDIA_CHANNEL_OPTIONS[0])
            cleaned_media["tier_name"] = cleaned_media["tier_name"].fillna(MEDIA_TIER_PRESETS[0])
            cleaned_media["mentions"] = pd.to_numeric(cleaned_media["mentions"], errors="coerce").fillna(0.0)
            st.session_state["media_cards"] = cleaned_media.to_dict("records")
            st.session_state["media_editor"] = cleaned_media
            st.button(
                "Next tab ->",
                key="btn_media_next",
                type="secondary",
                on_click=lambda: go_next_tab("Media Echo"),
            )

        elif active_tab == "Creator Echo":
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
                        "Next tab ->",
                        key="btn_creator_next_from_upload",
                        type="secondary",
                        on_click=lambda: go_next_tab("Creator Echo"),
                    )
            with tab_manual:
                st.session_state.setdefault("creator_cards", [])
                creator_manual_df = pd.DataFrame(st.session_state["creator_cards"])
                if creator_manual_df.empty:
                    creator_manual_df = pd.DataFrame(columns=["platform", "content_type", "tier", "num_posts"])

                st.caption("Pick a platform to add or edit rows. Changes save automatically.")
                platform_target = st.selectbox(
                    "Platform to edit",
                    CREATOR_PLATFORM_OPTIONS,
                    key="creator_platform_target",
                )

                platform_rows = merge_platform_rows(creator_manual_df, platform_target)
                content_choices = get_allowed_content_options(platform_target)

                filter_cols = st.columns(2)
                with filter_cols[0]:
                    manual_content_filter = st.selectbox(
                        "Content type filter",
                        ["All"] + content_choices,
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
                            options=content_choices,
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
                cleaned_creator = pd.DataFrame(creator_editor).copy()
                cleaned_creator["num_posts"] = pd.to_numeric(cleaned_creator["num_posts"], errors="coerce").fillna(0.0)
                cleaned_creator["platform"] = platform_target
                subset_index = editable_rows.index
                platform_rows.loc[subset_index, ["content_type", "tier", "num_posts"]] = cleaned_creator[
                    ["content_type", "tier", "num_posts"]
                ].values
                updated = creator_manual_df[creator_manual_df["platform"] != platform_target]
                updated = pd.concat([updated, platform_rows], ignore_index=True)
                st.session_state["creator_cards"] = updated.to_dict("records")
                st.session_state["creator_editor"] = updated
                st.button(
                    "Next tab ->",
                    key="btn_creator_to_community",
                    type="secondary",
                    on_click=lambda: go_next_tab("Creator Echo"),
                )
        elif active_tab == "Community Echo":
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
            cleaned_comm = pd.DataFrame(community_editor).copy()
            for col, _, _ in community_columns:
                cleaned_comm[col] = pd.to_numeric(cleaned_comm[col], errors="coerce").fillna(0.0)
            st.session_state["community_cards"] = cleaned_comm.to_dict("records")
            st.session_state["community_editor"] = cleaned_comm
            st.button(
                "Next tab ->",
                key="btn_community_to_report",
                type="secondary",
                on_click=lambda: st.session_state.update(active_wizard_step="Echo Impact Report"),
            )

        st.session_state["wizard_completed"]["Echo Studio"] = True
        if st.button("Next: Echo Impact Report", key="btn_to_impact_report", type="primary"):
            go_to_next_step("Echo Studio")
    elif wizard_step == "Echo Impact Report":
        st.subheader("3. Echo Impact Report")
        if st.button("Back to Echo Studio", type="secondary"):
            st.session_state["active_wizard_step"] = "Echo Studio"
            st.session_state["active_echo_tab"] = "Media Echo"
            st.rerun()
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

            # KPI cards (compact format)
            tev = float(result["tev"])
            media = float(result["media"])
            creator = float(result["creator"])
            community = float(result["community"])
            roi_m = float(result["roi_m"])
            roi_pct = float(result["roi_pct"])

            card_items = [
                ("Total Echo Value", _fmt_compact(tev), f"{tev:,.0f} THB"),
                ("Media Echo Value", _fmt_compact(media), f"{media:,.0f} THB"),
                ("Creator Echo Value", _fmt_compact(creator), f"{creator:,.0f} THB"),
                ("Community Echo Value", _fmt_compact(community), f"{community:,.0f} THB"),
                ("ROIM (TEV / INV)", f"{roi_m:.2f}x", "TEV ÷ Investment"),
                ("ROI %", f"{roi_pct:.2f}%", f"{roi_pct/100:.2f}x multiple"),
            ]
            st.markdown("<div class='metric-row'>", unsafe_allow_html=True)
            render_kpi_row(card_items[:4], cols_in_row=4)
            render_kpi_row(card_items[4:], cols_in_row=2)
            st.markdown("</div>", unsafe_allow_html=True)

            # TEV breakdown mini chart (Altair)
            breakdown_df = pd.DataFrame(
                {
                    "Component": ["Media", "Creator", "Community"],
                    "Value": [media, creator, community],
                }
            )
            tev_chart = (
                alt.Chart(breakdown_df)
                .mark_bar(cornerRadiusTopRight=6, cornerRadiusBottomRight=6, color=VERO_PRIMARY)
                .encode(
                    y=alt.Y("Component:N", sort="-x", title="Component"),
                    x=alt.X("Value:Q", title="Echo Value (THB)", axis=alt.Axis(format="~s")),
                    tooltip=[
                        alt.Tooltip("Component:N"),
                        alt.Tooltip("Value:Q", format=",.0f", title="Value (THB)"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(tev_chart, use_container_width=True)

            st.markdown("### Save Campaign")
            if not campaign_name or not client:
                st.info("Enter *Campaign name* and *Client / Brand* above to enable saving.")
            else:
                editing_id = st.session_state.get("editing_campaign_id")
                save_label = "Update saved campaign" if editing_id else "Save this campaign to local database"
                if st.button(save_label):
                    try:
                        save_campaign(
                            result,
                            st.session_state.get("last_inv", inv),
                            campaign_name,
                            client,
                            market,
                            campaign_id=editing_id,
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
    render_app_header("Campaign Performance", "Benchmarks across saved TEV analyses")

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

        # ===== Summary + charts layout =====
        def _fmt_value(num: float) -> str:
            try:
                val = float(num)
            except Exception:
                return "0"
            if abs(val) >= 1_000_000:
                return f"{val/1_000_000:.1f} M"
            if abs(val) >= 1_000:
                return f"{val/1_000:.1f} K"
            return f"{val:,.0f}"

        total_tev_val = filtered_df["tev"].sum()
        total_media_val = filtered_df["media_echo"].sum()
        total_creator_val = filtered_df["creator_echo"].sum()
        total_comm_val = filtered_df["community_echo"].sum()
        total_inv_val = filtered_df["investment"].sum() if "investment" in filtered_df else 0.0
        avg_roi = filtered_df["roi_pct"].mean()
        total_campaigns = len(filtered_df)

        row1_cards = [
            ("Total TEV", _fmt_compact(total_tev_val), f"{total_tev_val:,.0f} THB"),
            ("Media Echo", _fmt_compact(total_media_val), f"{total_media_val:,.0f} THB"),
            ("Creator Echo", _fmt_compact(total_creator_val), f"{total_creator_val:,.0f} THB"),
            ("Community Echo", _fmt_compact(total_comm_val), f"{total_comm_val:,.0f} THB"),
        ]
        row2_cards = [
            ("# Campaigns", _fmt_value(total_campaigns), f"{total_campaigns}"),
            ("AVG ROI %", f"{avg_roi:.1f}%", ""),
            ("ROIM (TEV / INV)", f"{(total_tev_val / total_inv_val):.2f}x" if total_inv_val else "0.00x", "TEV ÷ Investment"),
            ("Investment", _fmt_compact(total_inv_val), f"{total_inv_val:,.0f} THB"),
        ]
        render_kpi_row(row1_cards, cols_in_row=4)
        render_kpi_row(row2_cards, cols_in_row=4)

        # Donuts row using Altair (grey background container)
        donut_colors = {
            "media": "#003170",
            "creator": "#0a6cc2",
            "community": "#4bb7e5",
            "muted": "#d9dce3",
        }
        total_media = float(filtered_df["media_echo"].sum()) if "media_echo" in filtered_df else 0.0
        total_creator = float(filtered_df["creator_echo"].sum()) if "creator_echo" in filtered_df else 0.0
        total_comm = float(filtered_df["community_echo"].sum()) if "community_echo" in filtered_df else 0.0
        total_tev = total_media + total_creator + total_comm if (total_media + total_creator + total_comm) > 0 else 1.0

        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        # Campaign filter for charts
        chart_campaigns: list[str] = []
        default_selection: list[str] = []
        if "campaign_name" in display_df:
            sorted_campaigns_df = display_df.dropna(subset=["campaign_name"]).copy()
            if "campaign_end" in sorted_campaigns_df:
                sorted_campaigns_df["campaign_end_sort"] = pd.to_datetime(
                    sorted_campaigns_df["campaign_end"], errors="coerce"
                )
                sort_cols = ["campaign_end_sort"]
                if "id" in sorted_campaigns_df:
                    sort_cols.append("id")
                sorted_campaigns_df = sorted_campaigns_df.sort_values(sort_cols, ascending=False)
            else:
                sorted_campaigns_df = sorted_campaigns_df.iloc[::-1]
            chart_campaigns = sorted_campaigns_df["campaign_name"].unique().tolist()
            default_selection = chart_campaigns[:2]  # two newest/top campaigns by default
        selected_campaigns = st.multiselect(
            "Select campaigns to display in charts",
            chart_campaigns,
            default=default_selection,
        )
        chart_df = filtered_df[filtered_df["campaign_name"].isin(selected_campaigns)] if selected_campaigns else filtered_df.iloc[0:0]

        c_chart1, c_chart2 = st.columns(2)
        with c_chart1:
            st.subheader("TEV by campaign")

            if chart_df.empty:
                st.info("Select at least one campaign to see TEV.")
            else:
                tev_base = chart_df[["campaign_name", "tev"]].dropna()
                echo_long = (
                    chart_df[["campaign_name", "media_echo", "creator_echo", "community_echo"]]
                    .melt(id_vars="campaign_name", var_name="metric", value_name="value")
                    .dropna(subset=["value"])
                )
                metric_labels = {
                    "media_echo": "Media Echo",
                    "creator_echo": "Creator Echo",
                    "community_echo": "Community Echo",
                }
                metric_colors = {
                    "Media Echo": "#0b6ac8",
                    "Creator Echo": "#38bdf8",
                    "Community Echo": "#6366f1",
                }
                echo_long["metric_label"] = echo_long["metric"].map(metric_labels)
                campaign_order = tev_base.sort_values("tev", ascending=False)["campaign_name"].tolist()

                base_bar = (
                    alt.Chart(tev_base)
                    .mark_bar(color="#fecaca")
                    .encode(
                        y=alt.Y("campaign_name:N", title="Campaign", sort=campaign_order),
                        x=alt.X("tev:Q", title="Value (THB)", axis=alt.Axis(format="~s")),
                        tooltip=[
                            alt.Tooltip("campaign_name:N", title="Campaign"),
                            alt.Tooltip("tev:Q", title="Total TEV", format=",.0f"),
                        ],
                    )
                )

                echo_bar = (
                    alt.Chart(echo_long)
                    .mark_bar()
                    .encode(
                        y=alt.Y("campaign_name:N", title="Campaign", sort=campaign_order),
                        x=alt.X("value:Q", title="Value (THB)", stack="zero"),
                        color=alt.Color(
                            "metric_label:N",
                            title="Metric",
                            scale=alt.Scale(
                                domain=list(metric_colors.keys()),
                                range=list(metric_colors.values()),
                            ),
                        ),
                        tooltip=[
                            alt.Tooltip("campaign_name:N", title="Campaign"),
                            alt.Tooltip("metric_label:N", title="Component"),
                            alt.Tooltip("value:Q", title="Value", format=",.0f"),
                        ],
                    )
                )

                tev_chart = (base_bar + echo_bar).properties(height=320, background=VERO_CARD_BG)
                st.altair_chart(tev_chart, use_container_width=True)
        with c_chart2:
            st.subheader("ROI by campaign")
            roi_chart_df = chart_df[["campaign_name", "roi_pct"]].dropna(subset=["roi_pct"])
            if roi_chart_df.empty:
                st.info("Select at least one campaign to see ROI.")
            else:
                roi_chart_df = roi_chart_df.sort_values("roi_pct", ascending=False)

                roi_chart = (
                    alt.Chart(roi_chart_df)
                    .mark_bar(color="#0b6ac8")
                    .encode(
                        y=alt.Y("campaign_name:N", title="Campaign", sort=roi_chart_df["campaign_name"].tolist()),
                        x=alt.X("roi_pct:Q", title="ROI %", axis=alt.Axis(format=",.0f")),
                        tooltip=[
                            alt.Tooltip("campaign_name:N", title="Campaign"),
                            alt.Tooltip("roi_pct:Q", title="ROI %", format=",.1f"),
                        ],
                    )
                    .properties(height=320, background=VERO_CARD_BG)
                )

                st.altair_chart(roi_chart, use_container_width=True)

        st.subheader("Campaign Table")
        st.dataframe(display_df[existing_columns], width="stretch")

        st.subheader("Edit saved campaign")
        id_map = {int(row["id"]): row for _, row in filtered_df.iterrows() if pd.notna(row.get("id"))}
        if not id_map:
            st.info("No editable campaigns found.")
        else:
            selected_id = st.selectbox(
                "Select a campaign to edit",
                list(id_map.keys()),
                format_func=lambda cid: f"{id_map[cid].get('campaign_name','(untitled)')} - {id_map[cid].get('client','')}",
            )
            selected_row = id_map[selected_id]

            inv_k_existing = float(
                selected_row.get("investment_k")
                if pd.notna(selected_row.get("investment_k"))
                else (selected_row.get("investment") or 0.0) / 1000
            )
            start_default = _coerce_date_value(selected_row.get("campaign_start"), date.today())
            end_default = _coerce_date_value(
                selected_row.get("campaign_end"),
                start_default + timedelta(days=30),
            )

            with st.form(f"edit_campaign_form_{selected_id}"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    campaign_name_edit = st.text_input(
                        "Campaign name",
                        value=selected_row.get("campaign_name", ""),
                    )
                with c2:
                    client_edit = st.text_input(
                        "Client / Brand",
                        value=selected_row.get("client", ""),
                    )
                with c3:
                    market_edit = st.selectbox(
                        "Market / Country",
                        MARKET_OPTIONS,
                        index=MARKET_OPTIONS.index(selected_row.get("market", "Thailand"))
                        if selected_row.get("market") in MARKET_OPTIONS
                        else 0,
                    )

                c4, c5, c6 = st.columns(3)
                with c4:
                    objective_focus_edit = st.text_input(
                        "Objective focus",
                        value=selected_row.get("objective_focus", selected_row.get("objective", "")) or "",
                        help="Update the headline KPI focus.",
                    )
                with c5:
                    start_edit = st.date_input(
                        "Campaign start",
                        value=start_default,
                    )
                with c6:
                    end_edit = st.date_input(
                        "Campaign end",
                        value=end_default,
                    )

                c7, c8, c9 = st.columns(3)
                with c7:
                    currency_edit = st.selectbox(
                        "Currency",
                        CURRENCY_OPTIONS,
                        index=CURRENCY_OPTIONS.index(selected_row.get("currency", "THB"))
                        if selected_row.get("currency") in CURRENCY_OPTIONS
                        else 0,
                    )
                with c8:
                    inv_k_edit = st.number_input(
                        "Investment (K)",
                        min_value=0.0,
                        step=10.0,
                        value=inv_k_existing,
                    )
                with c9:
                    custom_flag_edit = st.checkbox(
                        "Custom budget mode",
                        value=bool(selected_row.get("custom_budget_flag")),
                    )

                st.markdown("##### Echo values")
                v1, v2, v3, v4 = st.columns(4)
                with v1:
                    media_echo_edit = st.number_input(
                        "Media Echo",
                        min_value=0.0,
                        step=1000.0,
                        value=float(selected_row.get("media_echo", 0.0) or 0.0),
                    )
                with v2:
                    creator_echo_edit = st.number_input(
                        "Creator Echo",
                        min_value=0.0,
                        step=1000.0,
                        value=float(selected_row.get("creator_echo", 0.0) or 0.0),
                    )
                with v3:
                    community_echo_edit = st.number_input(
                        "Community Echo",
                        min_value=0.0,
                        step=1000.0,
                        value=float(selected_row.get("community_echo", 0.0) or 0.0),
                    )
                with v4:
                    roi_pct_raw = selected_row.get("roi_pct", 0.0)
                    roi_pct_existing = float(roi_pct_raw) if pd.notna(roi_pct_raw) else 0.0
                    roi_pct_hint = f"{roi_pct_existing:.1f}%" if roi_pct_existing else "auto"
                    st.caption(f"ROI % will auto-calc on save ({roi_pct_hint}).")

                go_builder = st.form_submit_button("Open in builder to recalculate", type="secondary")
                save_clicked = st.form_submit_button("Update campaign", type="primary")

                if save_clicked:
                    inv_value = inv_k_edit * 1000
                    tev_value = media_echo_edit + creator_echo_edit + community_echo_edit
                    roi_m_value = (tev_value / inv_value) if inv_value else 0.0
                    roi_pct_value = roi_m_value * 100

                    payload = {
                        "campaign_name": campaign_name_edit,
                        "client": client_edit,
                        "market": market_edit,
                        "objective_focus": objective_focus_edit or None,
                        "campaign_start": _serialize_date(start_edit),
                        "campaign_end": _serialize_date(end_edit),
                        "currency": currency_edit,
                        "investment": inv_value,
                        "investment_k": inv_k_edit,
                        "custom_budget_flag": 1 if custom_flag_edit else 0,
                        "media_echo": media_echo_edit,
                        "creator_echo": creator_echo_edit,
                        "community_echo": community_echo_edit,
                        "tev": tev_value,
                        "roi_m": roi_m_value,
                        "roi_pct": roi_pct_value,
                    }
                    try:
                        update_campaign(selected_id, payload)
                        st.success("Campaign updated.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to update campaign: {exc}")

                if go_builder:
                    reset_campaign_builder_state()
                    st.session_state["editing_campaign_id"] = selected_id
                    st.session_state["active_page"] = PAGE_CAMPAIGN_BUILDER
                    st.session_state["campaign_info"] = {
                        "campaign_name": selected_row.get("campaign_name", ""),
                        "campaign_client": selected_row.get("client", ""),
                        "campaign_market": selected_row.get("market", "Thailand"),
                        "campaign_objective_choice": selected_row.get(
                            "objective_focus", selected_row.get("objective", "")
                        ),
                        "campaign_objective": selected_row.get("objective", ""),
                        "campaign_start_date": _coerce_date_value(
                            selected_row.get("campaign_start"), date.today()
                        ),
                        "campaign_end_date": _coerce_date_value(
                            selected_row.get("campaign_end"), date.today() + timedelta(days=30)
                        ),
                        "campaign_currency": selected_row.get("currency", "THB"),
                        "campaign_custom_mode": bool(selected_row.get("custom_budget_flag")),
                        "campaign_investment_k": inv_k_existing,
                        "campaign_investment": inv_k_existing * 1000,
                    }
                    try:
                        creator_rows_df = fetch_creator_rows(selected_id)
                    except Exception:
                        creator_rows_df = pd.DataFrame()
                    if not creator_rows_df.empty:
                        creator_rows_df["content_type"] = creator_rows_df.apply(
                            lambda row: row["content_type"]
                            if row["content_type"] in get_allowed_content_options(row["platform"])
                            else get_allowed_content_options(row["platform"])[0],
                            axis=1,
                        )
                        st.session_state["creator_cards"] = creator_rows_df.to_dict("records")
                        st.session_state["creator_editor"] = creator_rows_df
                    try:
                        media_rows_df = fetch_media_rows(selected_id)
                    except Exception:
                        media_rows_df = pd.DataFrame()
                    if not media_rows_df.empty:
                        st.session_state["media_cards"] = media_rows_df.to_dict("records")
                        st.session_state["media_editor"] = media_rows_df
                    try:
                        community_rows_df = fetch_community_rows(selected_id)
                    except Exception:
                        community_rows_df = pd.DataFrame()
                    if not community_rows_df.empty:
                        st.session_state["community_cards"] = community_rows_df.to_dict("records")
                        st.session_state["community_editor"] = community_rows_df
                    st.session_state["active_wizard_step"] = WIZARD_STEPS[0]
                    st.session_state["wizard_completed"] = {step: False for step in WIZARD_STEPS}
                    st.rerun()


elif page == PAGE_ACCOUNT_INFO:
    render_app_header("Account", "Your profile and workspace details")
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
    render_app_header("Workspace Settings", "Configure your preferences")
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
