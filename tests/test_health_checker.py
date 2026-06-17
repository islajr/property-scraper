import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone
import config
from scraper.health_checker import HealthChecker, _CheckResult


class TestHealthCheckerMicroBatching:

    @patch("scraper.health_checker.config")
    def test_run_slices_into_batches_and_commits_immediately(self, mock_config):
        # 1. Set batch size to 3
        mock_config.HEALTH_CHECK_BATCH_SIZE = 3
        mock_config.HEALTH_CHECK_DELAY_MIN = 0.01
        mock_config.HEALTH_CHECK_DELAY_MAX = 0.02

        # 2. Mock database writer
        db = MagicMock()
        candidates = [
            {"id": i, "source": "propertypro", "external_id": f"EXT0{i}", "url": f"http://test.com/{i}", "first_seen_at": datetime.now(timezone.utc), "price_kobo": 1000}
            for i in range(1, 8)  # 7 candidates total -> should produce 3 batches (3, 3, 1)
        ]
        db.fetch_listings_for_health_check.return_value = candidates
        db.confirm_listing_active.return_value = False  # no price change

        # 3. Mock the async run results for each batch
        results_batch_1 = [
            _CheckResult(listing_id=1, source="propertypro", external_id="EXT01", first_seen=None, is_removed=False, observed_price=1000),
            _CheckResult(listing_id=2, source="propertypro", external_id="EXT02", first_seen=None, is_removed=True, observed_price=None),
            _CheckResult(listing_id=3, source="propertypro", external_id="EXT03", first_seen=None, is_removed=False, observed_price=1000),
        ]
        results_batch_2 = [
            _CheckResult(listing_id=4, source="propertypro", external_id="EXT04", first_seen=None, is_removed=False, observed_price=1000),
            _CheckResult(listing_id=5, source="propertypro", external_id="EXT05", first_seen=None, is_removed=True, observed_price=None),
            _CheckResult(listing_id=6, source="propertypro", external_id="EXT06", first_seen=None, is_removed=False, observed_price=1000),
        ]
        results_batch_3 = [
            _CheckResult(listing_id=7, source="propertypro", external_id="EXT07", first_seen=None, is_removed=False, observed_price=1000),
        ]

        # 4. Instantiate HealthChecker and run
        checker = HealthChecker(db)
        checker._parsers = {} 
        
        # Patch _run_async as an AsyncMock
        checker._run_async = AsyncMock()
        checker._run_async.side_effect = [results_batch_1, results_batch_2, results_batch_3]

        stats = checker.run(force_all=False)

        # 5. Verify stats
        assert stats["checked"] == 7
        assert stats["confirmed_removed"] == 2  # ids 2 and 5
        assert stats["confirmed_active"] == 5   # ids 1, 3, 4, 6, 7
        assert stats["errors"] == 0

        # 6. Verify db was updated incrementally
        # confirm_listing_removed should have been called twice (for EXT02 and EXT05)
        assert db.confirm_listing_removed.call_count == 2
        db.confirm_listing_removed.assert_any_call(2, None)
        db.confirm_listing_removed.assert_any_call(5, None)

        # confirm_listing_active should have been called 5 times
        assert db.confirm_listing_active.call_count == 5
        db.confirm_listing_active.assert_any_call(1, 1000)
        db.confirm_listing_active.assert_any_call(7, 1000)

        # 7. Check calls to checker._run_async (were candidates sliced correctly?)
        assert checker._run_async.call_count == 3

