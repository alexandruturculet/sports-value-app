import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        try:
            import streamlit as st
            url = st.secrets.get("SUPABASE_URL")
            key = st.secrets.get("SUPABASE_KEY")
        except Exception:
            pass
    if not url or not key:
        logger.warning("Supabase credentials not configured")
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        logger.error("Failed to create Supabase client: %s", e)
        return None


def save_ticket(picks: list, avg_confidence: float, date_str: str) -> bool:
    """Insert today's ticket only if one doesn't already exist for this date."""
    client = _get_client()
    if not client:
        return False
    try:
        existing = client.table("tickets").select("id").eq("date", date_str).execute()
        if existing.data:
            logger.info("Ticket for %s already exists — skipping save.", date_str)
            return False
        client.table("tickets").insert(
            {
                "date": date_str,
                "picks": picks,
                "avg_confidence": avg_confidence,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        return True
    except Exception as e:
        logger.error("Failed to save ticket: %s", e)
        return False


def get_all_tickets() -> list:
    """Return all tickets ordered by date descending."""
    client = _get_client()
    if not client:
        return []
    try:
        resp = client.table("tickets").select("*").order("date", desc=True).execute()
        return resp.data or []
    except Exception as e:
        logger.error("Failed to fetch tickets: %s", e)
        return []


def update_ticket_result(ticket_id: str, result: str) -> bool:
    """Set result to 'won', 'lost', or 'pending'."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("tickets").update(
            {
                "result": result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", ticket_id).execute()
        return True
    except Exception as e:
        logger.error("Failed to update ticket result: %s", e)
        return False


def update_ticket_picks_and_result(ticket_id: str, picks: list, result: str) -> bool:
    """Update both the picks array (with per-pick results) and the ticket result."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("tickets").update(
            {
                "picks": picks,
                "result": result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", ticket_id).execute()
        return True
    except Exception as e:
        logger.error("Failed to update ticket picks and result: %s", e)
        return False


def get_motivation(fixture_id: int) -> dict | None:
    """Fetch cached motivation analysis for a fixture, or None if absent."""
    client = _get_client()
    if not client:
        return None
    try:
        resp = (
            client.table("match_motivation")
            .select("*")
            .eq("fixture_id", fixture_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logger.error("Failed to fetch motivation for fixture %s: %s", fixture_id, e)
        return None


def save_motivation(fixture_id: int, home: str, away: str, analysis: dict) -> bool:
    """Upsert motivation analysis for a fixture."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("match_motivation").upsert(
            {
                "fixture_id": fixture_id,
                "home_team": home,
                "away_team": away,
                "home_motivation": analysis["home_motivation"],
                "away_motivation": analysis["away_motivation"],
                "home_factors": analysis.get("home_factors", []),
                "away_factors": analysis.get("away_factors", []),
                "summary": analysis.get("summary", ""),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="fixture_id",
        ).execute()
        return True
    except Exception as e:
        logger.error("Failed to save motivation for fixture %s: %s", fixture_id, e)
        return False


def get_portfolio() -> list:
    """Return all portfolio coins ordered by coin_id."""
    client = _get_client()
    if not client:
        return []
    try:
        resp = client.table("portfolio").select("*").order("coin_id").execute()
        return resp.data or []
    except Exception as e:
        logger.error("Failed to fetch portfolio: %s", e)
        return []


def upsert_portfolio_coin(
    coin_id: str,
    symbol: str,
    qty: float,
    staking_apy: float | None,
    staked: bool,
    tv_symbol: str | None,
) -> bool:
    """Insert or update a single portfolio coin."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("portfolio").upsert(
            {
                "coin_id": coin_id,
                "symbol": symbol,
                "qty": qty,
                "staking_apy": staking_apy,
                "staked": staked,
                "tv_symbol": tv_symbol,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="coin_id",
        ).execute()
        return True
    except Exception as e:
        logger.error("Failed to upsert portfolio coin %s: %s", coin_id, e)
        return False


def delete_portfolio_coin(coin_id: str) -> bool:
    """Remove a coin from the portfolio."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("portfolio").delete().eq("coin_id", coin_id).execute()
        return True
    except Exception as e:
        logger.error("Failed to delete portfolio coin %s: %s", coin_id, e)
        return False


def get_stock_portfolio() -> list:
    """Return all stock/ETF portfolio positions ordered by ticker."""
    client = _get_client()
    if not client:
        return []
    try:
        resp = client.table("stock_portfolio").select("*").order("ticker").execute()
        return resp.data or []
    except Exception as e:
        logger.error("Failed to fetch stock portfolio: %s", e)
        return []


def upsert_stock_position(
    ticker: str, name: str, qty: float, avg_price: float, currency: str,
    tv_symbol: str | None = None,
) -> bool:
    """Insert or update a single stock/ETF position."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("stock_portfolio").upsert(
            {
                "ticker": ticker,
                "name": name,
                "qty": qty,
                "avg_price": avg_price,
                "currency": currency,
                "tv_symbol": tv_symbol,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="ticker",
        ).execute()
        return True
    except Exception as e:
        logger.error("Failed to upsert stock position %s: %s", ticker, e)
        return False


def delete_stock_position(ticker: str) -> bool:
    """Remove a stock/ETF position."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("stock_portfolio").delete().eq("ticker", ticker).execute()
        return True
    except Exception as e:
        logger.error("Failed to delete stock position %s: %s", ticker, e)
        return False


def reset_evaluated_tickets_to_pending() -> int:
    """Reset all won/lost tickets back to pending so they can be re-evaluated.
    Returns the number of tickets reset."""
    client = _get_client()
    if not client:
        return 0
    try:
        resp = (
            client.table("tickets")
            .select("id")
            .in_("result", ["won", "lost"])
            .execute()
        )
        ids = [row["id"] for row in (resp.data or [])]
        if not ids:
            return 0
        client.table("tickets").update(
            {
                "result": "pending",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).in_("id", ids).execute()
        logger.info("Reset %d tickets to pending for re-evaluation", len(ids))
        return len(ids)
    except Exception as e:
        logger.error("Failed to reset tickets: %s", e)
        return 0
