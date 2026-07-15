import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest

from scraper import checkpoint
from scraper.models import RawListing


@pytest.fixture(autouse=True)
def cleanup_checkpoints():
    """Ensure any left-over checkpoint file is deleted before and after each test."""
    checkpoint.clear_checkpoint()
    yield
    checkpoint.clear_checkpoint()


def test_discovery_checkpoint_serialization():
    listings = [
        RawListing(
            external_id="123",
            source="nigeriapropertycentre",
            url="http://example.com/123",
            title="3 Bedroom Flat",
            raw_price="₦45,000,000",
            raw_price_type="For Sale",
            raw_bedrooms="3",
            raw_bathrooms="3",
            raw_address="Lekki Phase 1",
            raw_floor_area="200 sqm",
            description="Beautiful flat",
            property_type_raw="Flat",
            agent_name="Agent Joe",
        )
    ]
    
    state = {
        "mode": "discovery",
        "completed_portals": ["propertypro"],
        "partial_portal": "nigeriapropertycentre",
        "completed_feeds": ["http://example.com/sale"],
        "partial_feed": "http://example.com/rent",
        "partial_feed_page": 2,
        "collected_raw_listings": listings,
        "run_stats": {"propertypro": {"status": "SUCCESS", "raw_count": 10}},
    }

    checkpoint.save_checkpoint(state)
    assert os.path.exists(checkpoint.CHECKPOINT_PATH)

    loaded = checkpoint.load_checkpoint("discovery")
    assert loaded is not None
    assert loaded["mode"] == "discovery"
    assert loaded["completed_portals"] == ["propertypro"]
    assert loaded["partial_portal"] == "nigeriapropertycentre"
    assert loaded["completed_feeds"] == ["http://example.com/sale"]
    assert loaded["partial_feed"] == "http://example.com/rent"
    assert loaded["partial_feed_page"] == 2
    assert len(loaded["collected_raw_listings"]) == 1
    
    loaded_listing = loaded["collected_raw_listings"][0]
    assert isinstance(loaded_listing, RawListing)
    assert loaded_listing.external_id == "123"
    assert loaded_listing.title == "3 Bedroom Flat"
    assert loaded_listing.raw_price == "₦45,000,000"


def test_health_check_checkpoint_serialization():
    state = {
        "mode": "health_check",
        "candidates": [
            {"id": 1, "source": "propertypro", "external_id": "a"},
            {"id": 2, "source": "privateproperty", "external_id": "b"},
        ],
        "last_processed_idx": 1,
        "stats": {
            "checked": 1,
            "confirmed_removed": 0,
            "confirmed_active": 1,
            "price_changes": 0,
            "errors": 0,
        },
    }

    checkpoint.save_checkpoint(state)
    assert os.path.exists(checkpoint.CHECKPOINT_PATH)

    loaded = checkpoint.load_checkpoint("health_check")
    assert loaded is not None
    assert loaded["mode"] == "health_check"
    assert len(loaded["candidates"]) == 2
    assert loaded["candidates"][0]["id"] == 1
    assert loaded["last_processed_idx"] == 1
    assert loaded["stats"]["confirmed_active"] == 1


def test_checkpoint_mode_mismatch():
    state = {"mode": "health_check"}
    checkpoint.save_checkpoint(state)

    # Trying to load discovery when it is health_check should return None
    loaded = checkpoint.load_checkpoint("discovery")
    assert loaded is None


def test_checkpoint_expiration():
    state = {"mode": "discovery", "collected_raw_listings": []}
    checkpoint.save_checkpoint(state)

    # Mock timestamp to be older than 24 hours ago
    expired_time = datetime.now(timezone.utc) - timedelta(hours=25)
    with patch("scraper.checkpoint.datetime") as mock_datetime:
        # Mock standard datetime.now calls, returning expired datetime for comparison checks
        mock_datetime.now.return_value = datetime.now(timezone.utc)
        mock_datetime.fromisoformat.return_value = expired_time
        
        loaded = checkpoint.load_checkpoint("discovery")
        assert loaded is None


def test_clear_checkpoint():
    state = {"mode": "discovery"}
    checkpoint.save_checkpoint(state)
    assert os.path.exists(checkpoint.CHECKPOINT_PATH)

    checkpoint.clear_checkpoint()
    assert not os.path.exists(checkpoint.CHECKPOINT_PATH)
