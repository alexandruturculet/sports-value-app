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
    """Upsert today's ticket (safe to call on every page load)."""
    client = _get_client()
    if not client:
        return False
    try:
        client.table("tickets").upsert(
            {
                "date": date_str,
                "picks": picks,
                "avg_confidence": avg_confidence,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="date",
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
