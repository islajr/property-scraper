"""Read bedroom/bathroom widgets only inside the primary listing's metrics.

No positional assignments, page-wide number search or toilet-to-bathroom mapping.
Unknown icon shapes deliberately return no metric rather than guessing a role.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit

_ICONS = {
    '6aae5d27c41e0304a9b756f9ed3aecd208dea59c572e4b2b3015a94ceb7b5e49': 'bedrooms',
    'b01290126d78dc92ba66d147fd74bc8c0c861d57340177f3645d32f796d21bdc': 'bathrooms',
}
_LABELS = {'bedrooms': re.compile(r'\b(?:bedrooms?|beds?)\b',re.I),
           'bathrooms': re.compile(r'\b(?:bathrooms?|baths?)\b',re.I)}


def extract_room_metrics(soup, source):
    values={'bedrooms':[],'bathrooms':[]};sources={}
    def add(role,text,basis):
        if text and text not in values[role]:values[role].append(text)
        sources[role]=basis
    if source in ('propertypro','privateproperty'):
        scopes=soup.select('.property-pricing > .property-pros, .property-contact-block > .property-pros') if source=='propertypro' else soup.select('.property-info .property-benefit')[:1]
        for scope in scopes:
            for item in (scope.select('ul > li') or scope.find_all('li',recursive=False)):
                text=item.get_text(' ',strip=True)
                roles=[role for role,pattern in _LABELS.items() if pattern.search(text)]
                if not roles:
                    icon_text=' '.join(str(e.get(a,'')) for e in item.select('img,svg') for a in ('alt','title','aria-label'))
                    roles=[role for role,pattern in _LABELS.items() if pattern.search(icon_text)]
                if len(roles)==1:add(roles[0],text,'PRIMARY_LABEL')
                elif not roles and source=='privateproperty':
                    paths='|'.join(p.get('d','') for p in item.select('svg path'))
                    role=_ICONS.get(hashlib.sha256(paths.encode()).hexdigest())
                    if role:add(role,text,'PRIMARY_ICON')
    elif source=='nigeriapropertycentre':
        scope=soup.select_one('.product-info .aux-info')
        if scope:
            for item in scope.select('[itemprop="additionalProperty"]'):
                name=item.select_one('[itemprop="name"]');value=item.select_one('[itemprop="value"]')
                if name and value:
                    for role,pattern in _LABELS.items():
                        if pattern.fullmatch(name.get_text(' ',strip=True)):
                            add(role,value.get_text(' ',strip=True),'PRIMARY_SCHEMA_PROPERTY')
        else:
            # The modern site has one compact primary metrics section. Related
            # listings and the longer details/description sections are excluded.
            for section in soup.select('main section'):
                text=section.get_text(' ',strip=True)
                if len(text)>500 or re.search(r'similar|related|recommended',text,re.I):continue
                labels=[e for e in section.find_all('span') if any(p.fullmatch(e.get_text(' ',strip=True)) for p in _LABELS.values())]
                if not labels:continue
                for label in labels:
                    spans=label.parent.find_all('span',recursive=False)
                    if len(spans)!=2:continue
                    other=next((s for s in spans if s is not label),None)
                    if other:
                        for role,pattern in _LABELS.items():
                            if pattern.fullmatch(label.get_text(' ',strip=True)):
                                add(role,other.get_text(' ',strip=True),'PRIMARY_LABEL')
                break
    elif source=='jiji':
        for item in soup.select('.b-advert-icon-attribute'):
            text=item.get_text(' ',strip=True)
            roles=[role for role,pattern in _LABELS.items() if pattern.search(text)]
            if len(roles)==1:add(roles[0],text,'PRIMARY_LABEL')
    if source=='propertypro':
        for role,text in _primary_schema_rooms(soup):add(role,text,'PRIMARY_SCHEMA_PROPERTY')
    return {role:' | '.join(items) if items else None for role,items in values.items()},sources


def _primary_schema_rooms(soup):
    """PropertyPro's widget-free pages retain primary residence JSON-LD.

    Require a canonical-URL-matched RealEstateListing and an exactly matching
    residence name. Ignore zero defaults, related residences and malformed JSON.
    JSON-LD's broad residence type is not property-classification evidence.
    """
    canonical=soup.select_one('link[rel="canonical"][href]')
    if canonical is None:return []
    def identity(url):
        try:
            parsed=urlsplit(url)
            if parsed.scheme not in {'http','https'} or parsed.hostname not in {'propertypro.ng','www.propertypro.ng'}:return None
            if not parsed.path.startswith('/property/'):return None
            return parsed.hostname.removeprefix('www.'),parsed.path.rstrip('/')
        except (ValueError,TypeError):return None
    target=identity(canonical['href'])
    if target is None:return []
    nodes=[]
    def collect(value):
        if isinstance(value,list):
            for item in value:collect(item)
        elif isinstance(value,dict):
            nodes.append(value)
            if '@graph' in value:collect(value['@graph'])
    for tag in soup.select('script[type="application/ld+json"]'):
        try:collect(json.loads(tag.string or tag.get_text()))
        except (ValueError,TypeError,RecursionError):continue
    def types(node):
        value=node.get('@type');return [t for t in (value if isinstance(value,list) else [value]) if isinstance(t,str)]
    names={n['name'] for n in nodes if 'RealEstateListing' in types(n) and
           identity(n.get('url'))==target and isinstance(n.get('name'),str) and n['name'].strip()}
    result=[]
    for node in nodes:
        if not any(t in {'SingleFamilyResidence','Apartment','House','Residence'} for t in types(node)):continue
        if not isinstance(node.get('name'),str) or node['name'] not in names:continue
        for role,key in (('bedrooms','numberOfBedrooms'),('bathrooms','numberOfBathroomsTotal')):
            value=node.get(key)
            if type(value) is int and value>0:result.append((role,str(value)))
            elif isinstance(value,str) and re.fullmatch(r'[1-9]\d*',value.strip()):result.append((role,value.strip()))
    return result
