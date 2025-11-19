from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "vero-echo-tool.db"

__all__ = [
    "get_conn",
    "insert_campaign",
    "fetch_campaigns",
    "insert_creator_rows",
    "create_user",
    "get_user_by_email",
    "update_last_login",
]


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def insert_campaign(
    result: Dict[str, float],
    inv: float,
    campaign_name: str,
    client: str,
    market: str,
    *,
    owner_id: Optional[int] = None,
    objective: Optional[str] = None,
    objective_focus: Optional[str] = None,
    campaign_start: Optional[str] = None,
    campaign_end: Optional[str] = None,
    currency: Optional[str] = "THB",
    investment_k: Optional[float] = None,
    custom_budget_flag: bool | int = False,
    source: str = "manual",
) -> int:
    """
    Persist a campaign summary row and return its ID.
    Optional keyword-only args contain the richer Campaign Brief inputs.
    """
    payload = {
        "owner_id": owner_id,
        "campaign_name": campaign_name,
        "client": client,
        "market": market or None,
        "objective": objective,
        "objective_focus": objective_focus,
        "campaign_start": campaign_start,
        "campaign_end": campaign_end,
        "currency": currency or "THB",
        "investment": inv,
        "investment_k": investment_k,
        "custom_budget_flag": 1 if custom_budget_flag else 0,
        "media_echo": result["media"],
        "creator_echo": result["creator"],
        "community_echo": result["community"],
        "tev": result["tev"],
        "roi_m": result["roi_m"],
        "roi_pct": result["roi_pct"],
        "source": source,
    }

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO campaigns (
                owner_id, campaign_name, client, market, objective,
                objective_focus, campaign_start, campaign_end,
                currency, investment, investment_k, custom_budget_flag,
                media_echo, creator_echo, community_echo,
                tev, roi_m, roi_pct, source
            ) VALUES (
                :owner_id, :campaign_name, :client, :market, :objective,
                :objective_focus, :campaign_start, :campaign_end,
                :currency, :investment, :investment_k, :custom_budget_flag,
                :media_echo, :creator_echo, :community_echo,
                :tev, :roi_m, :roi_pct, :source
            )
            """,
            payload,
        )
        return cur.lastrowid


def fetch_campaigns(
    client: Optional[str] = None,
    market: Optional[str] = None,
    campaign_name: Optional[str] = None,
    owner_id: Optional[int] = None,
) -> pd.DataFrame:
    where = []
    params: Dict[str, Any] = {}

    if client:
        where.append("client = :client")
        params["client"] = client
    if market:
        where.append("market = :market")
        params["market"] = market
    if campaign_name:
        where.append("campaign_name = :campaign_name")
        params["campaign_name"] = campaign_name
    if owner_id:
        where.append("owner_id = :owner_id")
        params["owner_id"] = owner_id

    clause = f"WHERE {' AND '.join(where)}" if where else ""

    query = f"""
        SELECT
            owner_id,
            id,
            created_at,
            campaign_name,
            client,
            market,
            objective,
            objective_focus,
            campaign_start,
            campaign_end,
            currency,
            investment,
            investment_k,
            custom_budget_flag,
            media_echo,
            creator_echo,
            community_echo,
            tev,
            roi_m,
            roi_pct
        FROM campaigns
        {clause}
        ORDER BY datetime(created_at) DESC
    """

    with get_conn() as conn:
        return pd.read_sql_query(query, conn, params=params)


def insert_creator_rows(campaign_id: int, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return

    normalized = [
        {
            "campaign_id": campaign_id,
            "platform": row.get("platform"),
            "content_type": row.get("content_type"),
            "tier": row.get("tier"),
            "num_posts": row.get("num_posts", 0),
            "rate": row.get("rate", 0),
            "source_campaign_id": row.get("source_campaign_id"),
        }
        for row in rows
    ]

    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO creator_echo_entries (
                campaign_id, platform, content_type, tier, num_posts, rate, source_campaign_id
            )
            VALUES (
                :campaign_id, :platform, :content_type, :tier, :num_posts, :rate, :source_campaign_id
            )
            """,
            normalized,
        )


def create_user(email: str,
                password_hash: str,
                name: Optional[str] = None,
                company: Optional[str] = None,
                team: Optional[str] = None,
                role: str = "internal") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO users (email, password_hash, name, company, team, role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (email, password_hash, name, company, team, role),
        )
        return cur.lastrowid


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        return dict(row) if row else None


def update_last_login(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id,),
        )
