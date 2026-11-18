"""Compare requested, redirected and canonical identities before using an advert."""
from urllib.parse import urljoin,urlsplit


def primary_identity_matches(parser,requested_url,*,final_url=None,soup=None,expected_id=None):
    def parts(url):
        if not isinstance(url,str):raise ValueError('URL must be text')
        value=urlsplit(url)
        if value.scheme not in {'http','https'} or not value.hostname:raise ValueError('HTTP URL required')
        return value.hostname.lower().removeprefix('www.'),value.path.rstrip('/'),value.query
    def identifier(url):
        if parser is None:return None
        parsed=urlsplit(url)
        result=parser._extract_external_id(parsed._replace(query='',fragment='').geturl())
        return result if isinstance(result,str) and result else None
    try:
        wanted=parts(requested_url);wanted_id=identifier(requested_url)
        if expected_id is not None and wanted_id is not None and wanted_id!=expected_id:return False
        identity=expected_id or wanted_id
        def matches(url):
            actual=parts(url)
            if actual[0]!=wanted[0]:return False
            found=identifier(url)
            if identity is not None and found is not None:return identity==found
            # Opaque URLs without an extractor must keep their path/query.
            return actual[1:]==wanted[1:]
        final_url=final_url or requested_url
        if not matches(final_url):return False
        if soup is not None:
            canonical=soup.select_one('link[rel="canonical"]')
            if canonical is not None:
                if not canonical.get('href'):return False
                if not matches(urljoin(final_url,canonical['href'])):return False
        return True
    except (ValueError,TypeError,AttributeError):return False


def same_portal_host(first,second):
    try:
        hosts=[urlsplit(url).hostname for url in (first,second)]
        return all(hosts) and hosts[0].lower().removeprefix('www.')==hosts[1].lower().removeprefix('www.')
    except (ValueError,TypeError,AttributeError):return False
