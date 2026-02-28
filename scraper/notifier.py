"""
notifier.py — Telegram run summary notification.

Sends a structured message at the end of each scraper run.
Uses raw requests — no Telegram library needed for a simple POST.

A silent success is acceptable. A silent failure is NOT.
The Telegram message is the 30-second health check that confirms
the pipeline is alive without requiring a dashboard.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

import config

log = logging.getLogger(__name__)

STATUS_ICONS = {
    "SUCCESS": "✅",
    "PARTIAL":  "⚠️ ",
    "FAILED":   "❌",
}


def send_summary(aggregate_stats: Dict,
                 run_stats: Dict,
                 duration_seconds: float,
                 total_listings: Optional[int] = None) -> None:
    """
    Build and send the Telegram run summary.

    Args:
        aggregate_stats: {new, updated, price_changes, suspected_sold, geocoded, geocode_total}
        run_stats:       {source: {status, new, updated, error, ...}}
        duration_seconds: total pipeline wall-clock time
        total_listings:  current count of all rows in raw_data.scraped_listings
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials not set — skipping notification")
        return

    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%a %d %b %Y %H:%M UTC")

    lines = [f"🏠 *PropertyScraper — {now_str}*\n"]

    # Per-portal status lines
    for source, info in run_stats.items():
        icon    = STATUS_ICONS.get(info.get("status", "FAILED"), "❓")
        new_ct  = info.get("new",            0)
        upd_ct  = info.get("updated",        0)
        sold_ct = info.get("suspected_sold", 0)
        err     = info.get("error")

        if info.get("status") == "SUCCESS":
            lines.append(
                f"{icon} *{source}:* {new_ct} new, {upd_ct} updated, {sold_ct} suspected\\_sold"
            )
        elif info.get("status") == "PARTIAL":
            lines.append(
                f"{icon} *{source}:* PARTIAL — {err or 'see logs'}; {new_ct} new scraped"
            )
        else:
            lines.append(f"{icon} *{source}:* FAILED — {err or 'unknown error'}")

    lines.append("")

    # Aggregate stats
    geocoded       = aggregate_stats.get("geocoded", 0)
    geocode_total  = aggregate_stats.get("geocode_total", 1)
    geocode_pct    = (geocoded / geocode_total * 100) if geocode_total else 0

    parsed         = aggregate_stats.get("prices_parsed", 0)
    parsed_total   = aggregate_stats.get("prices_total",  1)
    parsed_pct     = (parsed / parsed_total * 100) if parsed_total else 0

    lines.append(f"📍 *Geocoding:* {geocoded}/{geocode_total} enriched ({geocode_pct:.1f}%)")
    lines.append(f"💰 *Prices parsed:* {parsed}/{parsed_total} ({parsed_pct:.1f}%)")
    lines.append(f"🏘️  *Suspected sold this run:* {aggregate_stats.get('suspected_sold', 0)}")

    if total_listings is not None:
        lines.append(f"🗄️  *Total scraped\\_listings:* {total_listings:,} records")

    mins, secs = divmod(int(duration_seconds), 60)
    lines.append(f"\n⏱️  *Run completed in* {mins}m {secs}s")

    # Warn if any portal was non-SUCCESS
    non_success = [s for s, i in run_stats.items() if i.get("status") != "SUCCESS"]
    if non_success:
        lines.append(f"⚠️  {len(non_success)} portal(s) non-SUCCESS — review GitHub Actions log")

    message = "\n".join(lines)
    _send(message)


def send_error(error_message: str) -> None:
    """Send a short error alert — used when the orchestrator crashes before completing."""
    _send(f"❌ *PropertyScraper crashed*\n\n```{error_message[:1000]}```")


def _send(text: str) -> None:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    config.TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Telegram notification sent")
    except requests.RequestException as exc:
        log.error("Failed to send Telegram notification: %s", exc)