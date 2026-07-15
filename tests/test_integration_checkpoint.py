import sys
from unittest.mock import MagicMock, patch
import pytest

from scraper import checkpoint
from scraper import orchestrator


@pytest.fixture(autouse=True)
def clean_checkpoints():
    checkpoint.clear_checkpoint()
    yield
    checkpoint.clear_checkpoint()


@patch("scraper.orchestrator.DatabaseWriter")
@patch("scraper.orchestrator.Geocoder")
def test_discovery_orchestrator_resume_from_checkpoint(mock_geocoder, mock_db_writer):
    # Set up mocks
    mock_db = MagicMock()
    mock_db_writer.return_value = mock_db
    mock_db.fetch_active_listings.return_value = {}
    mock_db.count_total_listings.return_value = 1000
    mock_db.upsert.return_value = {
        "new": 5,
        "updated": 2,
        "price_changes": 1,
        "suspected_sold": 0,
        "duplicates_dropped": 0,
        "per_source": {"nigeriapropertycentre": {"new": 5, "updated": 2, "price_changes": 1}},
    }
    
    # Save a mock checkpoint for discovery mode
    mock_state = {
        "mode": "discovery",
        "completed_portals": ["propertypro", "privateproperty"],
        "partial_portal": "nigeriapropertycentre",
        "completed_feeds": [],
        "partial_feed": None,
        "partial_feed_page": 1,
        "collected_raw_listings": [],
        "run_stats": {},
    }
    checkpoint.save_checkpoint(mock_state)

    # Patch the actual parsing calls to prevent real network requests
    with patch("scraper.parsers.nigeriapropertycentre.NigeriaPropertyCentreParser.scrape") as mock_scrape:
        mock_scrape.return_value = []
        
        # Run orchestrator discovery
        orchestrator.run()
        
        # Verify that Nigeria Property Centre scraper was called, but others were not
        mock_scrape.assert_called_once()
        
    # Check that checkpoint is deleted on successful run completion
    loaded = checkpoint.load_checkpoint("discovery")
    assert loaded is None


@patch("scraper.orchestrator.DatabaseWriter")
@patch("scraper.orchestrator.notifier")
def test_health_check_orchestrator_resume_from_checkpoint(mock_notifier, mock_db_writer):
    # Set up mocks
    mock_db = MagicMock()
    mock_db_writer.return_value = mock_db
    mock_db.fetch_last_successful_run.return_value = None
    
    # Save a mock checkpoint for health check mode
    mock_state = {
        "mode": "health_check",
        "candidates": [
            {"id": 1, "source": "propertypro", "external_id": "a", "url": "http://a", "first_seen_at": None, "price_kobo": 100},
            {"id": 2, "source": "propertypro", "external_id": "b", "url": "http://b", "first_seen_at": None, "price_kobo": 200},
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
    checkpoint.save_checkpoint(mock_state)

    # Patch the health checker run logic
    with patch("scraper.health_checker.HealthChecker.run") as mock_run:
        mock_run.return_value = {"checked": 2, "confirmed_active": 2, "confirmed_removed": 0, "price_changes": 0, "errors": 0}
        
        orchestrator.run_health_checks(force_all=True)
        
        # Verify that checker was called with the checkpoint_state loaded
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert kwargs["checkpoint_state"] is not None
        assert kwargs["checkpoint_state"]["mode"] == "health_check"
        assert kwargs["checkpoint_state"]["last_processed_idx"] == 1

    # Check that checkpoint is deleted on successful completion
    loaded = checkpoint.load_checkpoint("health_check")
    assert loaded is None
