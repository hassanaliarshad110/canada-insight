"""Reading a Socrata (SODA 2.1) open data portal: paged queries, retries and the publisher's metadata.

Most Canadian municipal portals that publish row-level data use Socrata, ArcGIS Hub or CKAN. A city on another
platform gets its own connector with the same two methods (rows, metadata); nothing else in the core changes.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USER_AGENT = 'canada-insight/0.1 (+https://github.com/hassanaliarshad110/canada-insight)'


class SocrataClient:
    def __init__(self, base_url, app_token=None, retries=4, wait=5.0, page_size=50000, timeout=180):
        self.base = base_url.rstrip('/')
        self.token = app_token if app_token is not None else os.environ.get('SOCRATA_APP_TOKEN')
        self.retries, self.wait, self.page_size, self.timeout = retries, wait, page_size, timeout

    def _get(self, url):
        headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
        if self.token:
            headers['X-App-Token'] = self.token
        last = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                    return json.loads(r.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            time.sleep(self.wait * (attempt + 1))
        raise last

    def query_url(self, dataset, **params):
        q = {f'${k}': v for k, v in params.items() if v is not None}
        return f'{self.base}/resource/{dataset}.json?' + urllib.parse.urlencode(q)

    def pages(self, dataset, select=None, where=None, order=':id'):
        """Every row matching the query, one page at a time (stable order by row id so pages never overlap).
        Large layers (hundreds of thousands of parcels) are processed page by page to keep memory low."""
        offset = 0
        while True:
            page = self._get(self.query_url(dataset, select=select, where=where, order=order,
                                            limit=self.page_size, offset=offset))
            if page:
                yield page
            if len(page) < self.page_size:
                break
            offset += len(page)

    def rows(self, dataset, select=None, where=None, order=':id'):
        out = []
        for page in self.pages(dataset, select=select, where=where, order=order):
            out.extend(page)
        return out

    def metadata(self, dataset):
        """The publisher's own title, last-update time and licence."""
        m = self._get(f'{self.base}/api/views/{dataset}.json')
        upd = m.get('rowsUpdatedAt') or m.get('viewLastModified')
        return {
            'title': m.get('name'),
            'publisher_updated': datetime.fromtimestamp(upd, timezone.utc).strftime('%Y-%m-%d') if upd else None,
            'licence': (m.get('license') or {}).get('name') or m.get('licenseId'),
            'page': f'{self.base}/d/{dataset}',
        }


def rows_hash(rows):
    """A stable hash of the rows as read: the same rows always give the same hash."""
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    return h.hexdigest()
