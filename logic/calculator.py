from functools import lru_cache

import pandas as pd

from db import get_conn


# ========= LOAD REFERENCE TABLES =========

@lru_cache(maxsize=1)
def load_reference_tables():
    """
    Load the reference tables from SQLite.
    """
    with get_conn() as conn:
        media_tier_df = pd.read_sql_query(
            """
            SELECT
                category AS Category,
                type AS Type,
                tier_value
            FROM media_rate_reference
            """,
            conn,
        )
        creator_rate_df = pd.read_sql_query(
            """
            SELECT
                platform AS Platform,
                content_type AS Type,
                tier AS Tier,
                rate AS Rate
            FROM creator_rate_reference
            """,
            conn,
        )
        cpe_df = pd.read_sql_query(
            """
            SELECT
                platform,
                weight_content,
                weight_passive,
                weight_active,
                weight_amplification
            FROM community_rate_reference
            """,
            conn,
        )

    return media_tier_df, creator_rate_df, cpe_df


# ========= MEDIA ECHO =========

def _normalize_media_inputs(media_inputs: pd.DataFrame) -> pd.DataFrame:
    """
    Map friendly 'tier_name' values from the UI to the 'Type'
    values in the media_tier sheet.

    UI values (tier_name):
        - 'Major', 'Industry', 'Local/Niche'
        - 'Tier 1', 'Tier 2', 'Tier 3'

    Excel 'media_tier' sheet values:
        - Category: 'Online Article' / 'Social Media'
        - Type: 'Major national media', 'Industry-specific', 'Local/niche', '1', '2', '3'
    """
    df = media_inputs.copy()

    # Map our UI names to the Excel 'Type' values
    type_map = {
        "Major": "Major national media",
        "Industry": "Industry-specific",
        "Local/Niche": "Local/niche",
        "Tier 1": "1",
        "Tier 2": "2",
        "Tier 3": "3",
    }

    df["Category"] = df["channel_type"]
    df["TypeForJoin"] = df["tier_name"].map(type_map).fillna(df["tier_name"])
    return df


def calculate_media_echo(media_inputs: pd.DataFrame) -> float:
    """
    media_inputs columns from Streamlit:
        - channel_type   ('Online Article' / 'Social Media')
        - tier_name      ('Major', 'Industry', 'Local/Niche', 'Tier 1', 'Tier 2', 'Tier 3')
        - mentions
    """
    if media_inputs is None or media_inputs.empty:
        return 0.0

    media_tier_df, _, _ = load_reference_tables()

    df_norm = _normalize_media_inputs(media_inputs)

    merged = df_norm.merge(
        media_tier_df,
        left_on=["Category", "TypeForJoin"],
        right_on=["Category", "Type"],
        how="left",
    )

    rate_col = "tier_value"

    if rate_col not in merged.columns:
        return 0.0

    merged["mentions"] = merged["mentions"].fillna(0)
    merged[rate_col] = merged[rate_col].fillna(0)

    merged["value"] = merged["mentions"] * merged[rate_col]
    return float(merged["value"].sum())


# ========= CREATOR ECHO =========

def _normalize_creator_inputs(creator_inputs: pd.DataFrame) -> pd.DataFrame:
    """
    Map UI 'content_type' to Excel 'Type'.

    UI content_type:
        - 'Static Post'
        - 'Video Post'

    Excel 'creator_rate' Type:
        - 'Static/General Post'
        - 'Video Post'
    """
    df = creator_inputs.copy()

    type_map = {
        "Static Post": "Static/General Post",
        "Static/General Post": "Static/General Post",
        "Video Post": "Video Post",
    }

    df["TypeForJoin"] = df["content_type"].map(type_map).fillna(df["content_type"])
    return df


def calculate_creator_echo(creator_inputs: pd.DataFrame) -> float:
    """
    creator_inputs from Streamlit:
        - platform       (Facebook, Instagram, TikTok, ...)
        - content_type   ('Static Post', 'Video Post')
        - tier           ('Mega', 'Macro', 'Micro', 'Nano')
        - num_posts
    """
    if creator_inputs is None or creator_inputs.empty:
        return 0.0

    _, creator_rate_df, _ = load_reference_tables()

    df_norm = _normalize_creator_inputs(creator_inputs)

    merged = df_norm.merge(
        creator_rate_df,
        left_on=["platform", "TypeForJoin", "tier"],
        right_on=["Platform", "Type", "Tier"],
        how="left",
    )

    rate_col = "Rate"  # from creator_rate sheet

    if rate_col not in merged.columns:
        return 0.0

    merged["num_posts"] = merged["num_posts"].fillna(0)
    merged[rate_col] = merged[rate_col].fillna(0)

    merged["value"] = merged["num_posts"] * merged[rate_col]
    return float(merged["value"].sum())


# ========= COMMUNITY ECHO =========

def calculate_community_echo(comm_inputs: pd.DataFrame) -> float:
    """
    comm_inputs from Streamlit:
        - platform
        - content_creation (number of posts/videos by community)  [we'll add this in app.py]
        - passive_engagement
        - active_engagement
        - amplification

    cpe_df columns (from Excel):
        - 'Platform'
        - 'Content Creation (New Posts, Videos)'
        - 'Passive Engagement (Likes, Reactions)'
        - 'Active Engagement (Comments, Replies)'
        - 'Amplification (Shares, Retweets)'
    """
    if comm_inputs is None or comm_inputs.empty:
        return 0.0

    # Make sure the column exists even if UI doesn't send it yet
    if "content_creation" not in comm_inputs.columns:
        comm_inputs = comm_inputs.copy()
        comm_inputs["content_creation"] = 0

    _, _, cpe_df = load_reference_tables()

    merged = comm_inputs.merge(
        cpe_df,
        on="platform",
        how="left",
    )

    for col in [
        "content_creation",
        "passive_engagement",
        "active_engagement",
        "amplification",
        "weight_content",
        "weight_passive",
        "weight_active",
        "weight_amplification",
    ]:
        if col not in merged.columns:
            merged[col] = 0

    merged["content_creation"] = merged["content_creation"].fillna(0)
    merged["passive_engagement"] = merged["passive_engagement"].fillna(0)
    merged["active_engagement"] = merged["active_engagement"].fillna(0)
    merged["amplification"] = merged["amplification"].fillna(0)

    merged["weight_content"] = merged["weight_content"].fillna(0)
    merged["weight_passive"] = merged["weight_passive"].fillna(0)
    merged["weight_active"] = merged["weight_active"].fillna(0)
    merged["weight_amplification"] = merged["weight_amplification"].fillna(0)

    merged["value"] = (
        merged["content_creation"] * merged["weight_content"]
        + merged["passive_engagement"] * merged["weight_passive"]
        + merged["active_engagement"] * merged["weight_active"]
        + merged["amplification"] * merged["weight_amplification"]
    )

    return float(merged["value"].sum())


# ========= MAIN CAMPAIGN CALC =========

def calculate_campaign(inv: float,
                       media_df: pd.DataFrame,
                       creator_df: pd.DataFrame,
                       comm_df: pd.DataFrame) -> dict:
    """
    Main function used by app.py
    Returns:
        - media
        - creator
        - community
        - tev
        - roi_m
        - roi_pct
    """
    media_val = calculate_media_echo(media_df)
    creator_val = calculate_creator_echo(creator_df)
    comm_val = calculate_community_echo(comm_df)

    tev = media_val + creator_val + comm_val

    if inv and inv > 0:
        roi_m = tev / inv
        roi_pct = (tev - inv) / inv * 100
    else:
        roi_m = 0.0
        roi_pct = 0.0

    return {
        "media": media_val,
        "creator": creator_val,
        "community": comm_val,
        "tev": tev,
        "roi_m": roi_m,
        "roi_pct": roi_pct,
    }
