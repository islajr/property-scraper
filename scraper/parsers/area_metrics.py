"""Labelled area widgets inside the primary listing, excluding related cards."""
import re

_LABEL=re.compile(r'^(?:(?:total\s+)?(?:land|plot|site|floor|built[ -]?up|internal|living|covered)\s+(?:area|size|space)|size|area)(?:\s*\((?:sqm|m²|m2|sqft)\))?\s*:?$',re.I)


def extract_area_metrics(soup,source):
    result=[]
    def add(label,value,method):
        if not _LABEL.fullmatch(label.strip()) or not value:return
        role='LAND' if re.search(r'land|plot|site',label,re.I) else 'FLOOR' if re.search(r'floor|built|internal|living|covered',label,re.I) else 'UNSPECIFIED'
        unit=re.search(r'\((sqm|m²|m2|sqft)\)',label,re.I)
        if unit and re.fullmatch(r'[\d,.\s]+',value):value=value+' '+unit[1]
        item=dict(role=role,label=label,value=value,source=method)
        if item not in result:result.append(item)
    selectors={'propertypro':'.property-pricing > .property-pros, .property-contact-block > .property-pros',
               'privateproperty':'.property-info .property-benefit',
               'nigeriapropertycentre':'.product-info .aux-info','jiji':'.b-advert-icon-attribute'}
    scopes=soup.select(selectors.get(source,'[data-no-area-scope]'))
    for scope in scopes:
        for item in scope.select('[itemprop="additionalProperty"]'):
            name=item.select_one('[itemprop="name"]');value=item.select_one('[itemprop="value"]')
            if name and value:add(name.get_text(' ',strip=True),value.get_text(' ',strip=True),'PRIMARY_SCHEMA_PROPERTY')
        for item in scope.select('li'):
            for label in item.select('[data-tooltip], [aria-label]'):
                value=label.select_one('strong')
                if value:add(label.get('data-tooltip') or label.get('aria-label'),value.get_text(' ',strip=True),'PRIMARY_LABEL')
            text=item.get_text(' ',strip=True)
            pair=re.match(r'^(.{2,35}?)\s*:\s*(\d.*)$',text)
            if pair:add(pair[1],pair[2],'PRIMARY_LABEL')
        for label in scope.select('dt'):
            value=label.find_next_sibling('dd')
            if value:add(label.get_text(' ',strip=True),value.get_text(' ',strip=True),'PRIMARY_LABEL')
    if source=='nigeriapropertycentre' and not scopes:
        for section in soup.select('main section'):
            text=section.get_text(' ',strip=True)
            if len(text)>600 or re.search(r'similar|related|recommended',text,re.I) or section.select('a[href*="/for-"]'):continue
            for label in section.find_all('span'):
                if not _LABEL.fullmatch(label.get_text(' ',strip=True)):continue
                siblings=label.parent.find_all('span',recursive=False)
                if len(siblings)==2:
                    other=next(s for s in siblings if s is not label)
                    add(label.get_text(' ',strip=True),other.get_text(' ',strip=True),'PRIMARY_LABEL')
    return result
