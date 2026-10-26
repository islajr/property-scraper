from dataclasses import asdict
from tests.conftest import make_raw, make_normalised
from scraper.models import RawListing, NormalisedListing


def test_legacy_checkpoint_listing_shapes_remain_readable():
    raw = asdict(make_raw())
    raw.pop('raw_price_text')
    assert RawListing(**raw).raw_price_text is None
    normalised = asdict(make_normalised())
    for name in ('price_period', 'price_period_count', 'price_period_status',
                 'price_period_source', 'raw_price_text', 'price_period_evidence',
                 'price_currency', 'price_basis', 'pricing_observed_at'):
        normalised.pop(name)
    listing = NormalisedListing(**normalised)
    assert listing.price_period is None
    assert listing.price_period_status == 'UNKNOWN'
    assert listing.price_currency is None


def test_legacy_snapshot_command_cannot_overwrite_mixed_price_history():
    import subprocess
    import sys
    from pathlib import Path
    script=Path(__file__).resolve().parents[1]/'rebuild_snapshots.py'
    result=subprocess.run([sys.executable,str(script)],text=True,capture_output=True)
    assert result.returncode != 0
    assert 'Existing snapshots are not modified' in result.stderr
