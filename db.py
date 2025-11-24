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
    "fetch_creator_rows",
    "replace_creator_rows",
    "fetch_media_rows",
    "replace_media_rows",
    "fetch_community_rows",
    "replace_community_rows",
    "update_campaign",
    "insert_creator_rows",
    "create_user",
    "get_user_by_email",
    "update_last_login",
]

_TABLES_INITIALIZED = False


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    global _TABLES_INITIALIZED
    if _TABLES_INITIALIZED:
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS creator_echo_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            platform TEXT,
            content_type TEXT,
            tier TEXT,
            num_posts REAL DEFAULT 0,
            rate REAL DEFAULT 0,
            source_campaign_id INTEGER,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS media_echo_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            channel_type TEXT,
            tier_name TEXT,
            mentions REAL DEFAULT 0,
            source_campaign_id INTEGER,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS community_echo_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            platform TEXT,
            content_creation REAL DEFAULT 0,
            passive_engagement REAL DEFAULT 0,
            active_engagement REAL DEFAULT 0,
            amplification REAL DEFAULT 0,
            source_campaign_id INTEGER,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );
        """
    )
    _ensure_column(conn, "media_echo_entries", "source_campaign_id", "INTEGER")
    _ensure_column(conn, "community_echo_entries", "source_campaign_id", "INTEGER")
    _ensure_column(conn, "creator_echo_entries", "source_campaign_id", "INTEGER")
    _TABLES_INITIALIZED = True


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition};")
        except sqlite3.OperationalError:
            pass


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


def update_campaign(campaign_id: int, payload: Dict[str, Any]) -> None:
    """
    Update a campaign row with the provided fields.
    Only keys present in `payload` are included in the UPDATE statement.
    """
    if not payload:
        return

    allowed_keys = {
        "campaign_name",
        "client",
        "market",
        "objective",
        "objective_focus",
        "campaign_start",
        "campaign_end",
        "currency",
        "investment",
        "investment_k",
        "custom_budget_flag",
        "media_echo",
        "creator_echo",
        "community_echo",
        "tev",
        "roi_m",
        "roi_pct",
    }
    filtered = {k: v for k, v in payload.items() if k in allowed_keys}
    if not filtered:
        return

    set_clause = ", ".join(f"{key} = :{key}" for key in filtered)
    filtered["id"] = campaign_id
    query = f"UPDATE campaigns SET {set_clause} WHERE id = :id"

    with get_conn() as conn:
        conn.execute(query, filtered)


def fetch_creator_rows(campaign_id: int) -> pd.DataFrame:
    query = """
        SELECT platform, content_type, tier, num_posts, rate, source_campaign_id
        FROM creator_echo_entries
        WHERE campaign_id = ?
    """
    with get_conn() as conn:
        return pd.read_sql_query(query, conn, params=(campaign_id,))


def replace_creator_rows(campaign_id: int, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    with get_conn() as conn:
        conn.execute("DELETE FROM creator_echo_entries WHERE campaign_id = ?", (campaign_id,))
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO creator_echo_entries (
                campaign_id, platform, content_type, tier, num_posts, rate, source_campaign_id
            ) VALUES (
                :campaign_id, :platform, :content_type, :tier, :num_posts, :rate, :source_campaign_id
            )
            """,
            [
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
            ],
        )


def fetch_media_rows(campaign_id: int) -> pd.DataFrame:
    query = """
        SELECT channel_type, tier_name, mentions, source_campaign_id
        FROM media_echo_entries
        WHERE campaign_id = ?
    """
    with get_conn() as conn:
        return pd.read_sql_query(query, conn, params=(campaign_id,))


def replace_media_rows(campaign_id: int, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    with get_conn() as conn:
        conn.execute("DELETE FROM media_echo_entries WHERE campaign_id = ?", (campaign_id,))
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO media_echo_entries (
                campaign_id, channel_type, tier_name, mentions, source_campaign_id
            ) VALUES (
                :campaign_id, :channel_type, :tier_name, :mentions, :source_campaign_id
            )
            """,
            [
                {
                    "campaign_id": campaign_id,
                    "channel_type": row.get("channel_type"),
                    "tier_name": row.get("tier_name"),
                    "mentions": row.get("mentions", 0),
                    "source_campaign_id": row.get("source_campaign_id"),
                }
                for row in rows
            ],
        )


def fetch_community_rows(campaign_id: int) -> pd.DataFrame:
    query = """
        SELECT platform, content_creation, passive_engagement, active_engagement, amplification, source_campaign_id
        FROM community_echo_entries
        WHERE campaign_id = ?
    """
    with get_conn() as conn:
        return pd.read_sql_query(query, conn, params=(campaign_id,))


def replace_community_rows(campaign_id: int, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    with get_conn() as conn:
        conn.execute("DELETE FROM community_echo_entries WHERE campaign_id = ?", (campaign_id,))
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO community_echo_entries (
                campaign_id, platform, content_creation, passive_engagement,
                active_engagement, amplification, source_campaign_id
            ) VALUES (
                :campaign_id, :platform, :content_creation, :passive_engagement,
                :active_engagement, :amplification, :source_campaign_id
            )
            """,
            [
                {
                    "campaign_id": campaign_id,
                    "platform": row.get("platform"),
                    "content_creation": row.get("content_creation", 0),
                    "passive_engagement": row.get("passive_engagement", 0),
                    "active_engagement": row.get("active_engagement", 0),
                    "amplification": row.get("amplification", 0),
                    "source_campaign_id": row.get("source_campaign_id"),
                }
                for row in rows
            ],
        )


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
