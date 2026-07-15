"""
checkpoint.py — Scraper state checkpoint and recovery manager.
Supports both discovery and health-check modes.
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from scraper.models import RawListing

log = logging.getLogger(__name__)

CHECKPOINT_PATH = ".scraper_checkpoint.json"
MAX_AGE_HOURS = 24


def save_checkpoint(state: Dict[str, Any]) -> None:
    """Atomically write scraper state to a checkpoint file."""
    try:
        # Shallow copy to avoid mutating caller's dictionary
        state_copy = dict(state)
        state_copy["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        # Serialize RawListing objects in discovery mode
        if "collected_raw_listings" in state_copy and state_copy["collected_raw_listings"]:
            import dataclasses
            serialized_listings = []
            for item in state_copy["collected_raw_listings"]:
                if isinstance(item, RawListing):
                    serialized_listings.append(dataclasses.asdict(item))
                else:
                    serialized_listings.append(item)
            state_copy["collected_raw_listings"] = serialized_listings

        # Write to temporary file first, then swap atomically to avoid corruption
        temp_path = CHECKPOINT_PATH + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(state_copy, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, CHECKPOINT_PATH)
        log.debug("Checkpoint saved: %s", CHECKPOINT_PATH)
    except Exception as exc:
        log.error("Failed to save checkpoint: %s", exc, exc_info=True)


def load_checkpoint(expected_mode: str) -> Optional[Dict[str, Any]]:
    """
    Load, validate, and deserialize the checkpoint.
    Returns None if no checkpoint exists, if it's expired (>24h),
    or if the mode doesn't match the active execution path.
    """
    if not os.path.exists(CHECKPOINT_PATH):
        return None

    try:
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)

        # Validate mode
        if state.get("mode") != expected_mode:
            log.info("Checkpoint mode %r does not match expected mode %r. Ignoring.", state.get("mode"), expected_mode)
            return None

        # Validate timestamp age
        ts_str = state.get("timestamp")
        if not ts_str:
            log.warning("Checkpoint has no timestamp. Ignoring.")
            return None
        
        timestamp = datetime.fromisoformat(ts_str)
        now = datetime.now(timezone.utc)
        if now - timestamp > timedelta(hours=MAX_AGE_HOURS):
            log.info("Checkpoint is expired (older than %d hours). Ignoring.", MAX_AGE_HOURS)
            return None

        # Deserialise RawListings if in discovery mode
        if expected_mode == "discovery" and "collected_raw_listings" in state:
            deserialized = []
            for item in state["collected_raw_listings"]:
                deserialized.append(RawListing(**item))
            state["collected_raw_listings"] = deserialized

        log.info("Loaded valid checkpoint for mode %r dated %s", expected_mode, ts_str)
        return state
    except Exception as exc:
        log.error("Failed to load checkpoint: %s", exc, exc_info=True)
        return None


def clear_checkpoint() -> None:
    """Remove the checkpoint file if it exists."""
    if os.path.exists(CHECKPOINT_PATH):
        try:
            os.remove(CHECKPOINT_PATH)
            log.info("Cleared checkpoint file.")
        except Exception as exc:
            log.error("Failed to delete checkpoint file: %s", exc)
