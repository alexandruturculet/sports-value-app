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
