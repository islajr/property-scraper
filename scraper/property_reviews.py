"""Human decisions apply only to the same portal identity and saved evidence."""
import hashlib
import json
from pathlib import Path

REGISTRY = Path(__file__).with_suffix('.json')
_REVIEWS = {(r['source'], r['external_id']): r for r in json.loads(REGISTRY.read_text())}


def matching_review(source, external_id, raw_type, title, description):
    review = _REVIEWS.get((source, external_id))
    values = [raw_type, title, description]
    digest = hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return review if review and review['evidence_sha256'] == digest else None


def review_fingerprint():
    return Path(__file__).read_bytes() + REGISTRY.read_bytes()
