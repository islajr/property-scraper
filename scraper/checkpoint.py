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


def _serialize_val(val: Any) -> Any:
    """Recursively convert custom types (datetime, dataclass) to JSON-serializable forms."""
    import dataclasses
    if isinstance(val, datetime):
        return {"__datetime__": val.isoformat()}
    elif isinstance(val, dict):
        return {k: _serialize_val(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_serialize_val(v) for v in val]
    elif isinstance(val, tuple):
        return tuple(_serialize_val(v) for v in val)
    elif dataclasses.is_dataclass(val):
        return _serialize_val(dataclasses.asdict(val))
    return val


def _deserialize_val(val: Any) -> Any:
    """Recursively restore custom types (datetime) from serialized representations."""
    if isinstance(val, dict):
        if "__datetime__" in val and len(val) == 1:
            return datetime.fromisoformat(val["__datetime__"])
        return {k: _deserialize_val(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_deserialize_val(v) for v in val]
    return val


def save_checkpoint(state: Dict[str, Any]) -> None:
    """Atomically write scraper state to a checkpoint file."""
    try:
        # Convert and serialize everything recursively
        serialized_state = _serialize_val(state)
        serialized_state["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Write to temporary file first, then swap atomically to avoid corruption
        temp_path = CHECKPOINT_PATH + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(serialized_state, f, indent=2, ensure_ascii=False)
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
            raw_state = json.load(f)

        # Validate mode
        if raw_state.get("mode") != expected_mode:
            log.info("Checkpoint mode %r does not match expected mode %r. Ignoring.", raw_state.get("mode"), expected_mode)
            return None

        # Validate timestamp age
        ts_str = raw_state.get("timestamp")
        if not ts_str:
            log.warning("Checkpoint has no timestamp. Ignoring.")
            return None
        
        timestamp = datetime.fromisoformat(ts_str)
        now = datetime.now(timezone.utc)
        if now - timestamp > timedelta(hours=MAX_AGE_HOURS):
            log.info("Checkpoint is expired (older than %d hours). Ignoring.", MAX_AGE_HOURS)
            return None

        # Recursively deserialize all custom types
        state = _deserialize_val(raw_state)

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
