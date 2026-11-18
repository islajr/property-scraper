"""Evidence-bearing advertised features. Missing claims mean unknown, not false."""
import hashlib
from pathlib import Path
import re
from scraper.property_reviews import matching_review, review_fingerprint
from scraper import property_count_profile

VERSION = 'property-facts-v1'
PATTERNS = {
    'HOME_OFFICE': r'\b(?:home|dedicated)\s+office(?:\s+space)?\b',
    'CINEMA': r'\b(?:private\s+|home\s+)?cinema\b',
    'SWIMMING_POOL': r'\b(?:swimming\s+)?pool\b',
    'GYM': r'\b(?:gym|gymnasium)\b',
    'BOYS_QUARTERS': r'\b(?:\d+\s*)?bq\b|\bboys?[’\x27]?\s+quarters?\b',
    'FITTED_KITCHEN': r'\b(?:fully\s+)?fitted\s+kitchen\b',
    'FURNISHED': r'\b(?:fully\s+)?furnished\b',
    'PARKING': r'\b(?:car\s+park|parking\s+space|parking)\b',
    'BALCONY': r'\bbalcon(?:y|ies)\b',
}


def extractor_hash():
    return hashlib.sha256(Path(__file__).read_bytes()+review_fingerprint()+Path(property_count_profile.__file__).read_bytes()).hexdigest()


def assess_facts(title, description, *, source=None, external_id=None, raw_type=None):
    features=[]
    for name,text in (('TITLE',(title or '')[:2000]),('DESCRIPTION',(description or '')[:20000])):
        for key,pattern in PATTERNS.items():
            for m in re.finditer(pattern,text,re.I):
                prefix=re.split(r'[.;\n]',text[:m.start()])[-1]
                # Location, hypothetical uses, and later agent inventories are not amenities.
                if re.search(r'\b(?:near|nearby|proximity|opposite|beside|close\s+to|landmarks?|suitable\s+for|ideal\s+for|potential|other\s+properties|contact)\b',prefix,re.I):continue
                if key=='HOME_OFFICE' and m.group().lower().startswith('dedicated') and not re.search(r'\b(?:bed(?:rooms?)?|duplex|flat|apartment|house|bungalow|villa)\b',(title or '')+' '+prefix,re.I):continue
                # A commercial cinema or gym is an asset, not automatically a home feature.
                if key in ('CINEMA','GYM') and not re.search(r'\b(?:bed(?:rooms?)?|duplex|flat|apartment|house|bungalow|villa|features?|amenities|facilities|private|home)\b',(title or '')+' '+prefix,re.I):continue
                if re.search(r'\b(?:no|without|not)\b',prefix,re.I) and not re.search(r'\b(?:no|without|not)\s+(?:a\s+|any\s+|private\s+|swimming\s+)?$',prefix,re.I):continue
                negative=bool(re.search(r'\b(?:no|without|not)\s+(?:a\s+|any\s+|private\s+|swimming\s+)?$',prefix,re.I))
                scope='SHARED' if re.search(r'\b(?:shared|communal)\s*$',prefix,re.I) else 'PRIVATE' if (re.search(r'\bprivate\s*$',prefix,re.I) or re.match(r'private\b',m.group(),re.I)) else 'UNKNOWN'
                start,end=max(0,m.start()-50),min(len(text),m.end()+70)
                features.append(dict(feature=key,claimed=not negative,scope=scope,source=name,start=m.start(),end=m.end(),text=m.group(),context=text[start:end],basis='ADVERTISER_CLAIM'))
    review=matching_review(source,external_id,raw_type,title,description)
    questions=list(review['questions']) if review else []
    alternatives=property_count_profile.profile_text(title,description)['offer_alternative_hint'] or bool(review and review.get('multiple_offers')) or bool(re.search(r'\bper\s+unit\b[\s\S]{0,200}\ball\s+units\b|\bindividually\s+or\s+together\b',description or '',re.I))
    # Never turn one listing into multiple properties or certify its headline price.
    if alternatives and not questions:questions.append('Resolve separate offers and their price/period/basis before price comparison.')
    return dict(features=features,offers=review.get('offers',[]) if review else [],
                multiple_offers=alternatives,questions=questions,
                review_case=review['case_id'] if review else None,
                feature_semantics='Advertiser claims; absence is unknown; amenities are not counted rooms.')
