from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from config import settings
from user_config import get_user_setting


@dataclass
class WebResult:
    id: str
    title: str
    url: str
    domain: str
    snippet: str
    age: str | None = None

    def public(self) -> dict:
        return asdict(self)


TRUSTED_BONUS = {
    'reuters.com': 20,
    'apnews.com': 20,
    'bbc.com': 17,
    'bbc.co.uk': 17,
    'france24.com': 16,
    'franceinfo.fr': 16,
    'lemonde.fr': 15,
    'theguardian.com': 14,
    'nytimes.com': 14,
    'ft.com': 14,
    'europa.eu': 22,
    'gouv.fr': 22,
    'who.int': 22,
    'un.org': 22,
    'oecd.org': 20,
}


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix('www.')


def _score(item: WebResult, index: int) -> int:
    bonus = max(
        (value for key, value in TRUSTED_BONUS.items() if item.domain == key or item.domain.endswith('.' + key)),
        default=0,
    )
    return 100 - index + bonus


def _brave_key() -> str:
    return str(get_user_setting('brave_search_api_key', '') or settings.brave_search_api_key or '').strip()


async def _search_brave(query: str, freshness: str | None) -> list[WebResult]:
    key = _brave_key()
    params: dict[str, str | int] = {
        'q': query,
        'country': settings.web_search_country,
        'search_lang': settings.web_search_lang,
        'ui_lang': f'{settings.web_search_lang}-{settings.web_search_country}',
        'count': min(max(settings.web_results, 3), 20),
        'safesearch': 'moderate',
    }
    if freshness in {'pd', 'pw', 'pm', 'py'}:
        params['freshness'] = freshness
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
        'X-Subscription-Token': key,
    }
    async with httpx.AsyncClient(timeout=18.0, follow_redirects=True) as client:
        response = await client.get('https://api.search.brave.com/res/v1/web/search', params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
    rows = payload.get('web', {}).get('results', [])
    results: list[WebResult] = []
    for row in rows:
        url = row.get('url') or ''
        if not url.startswith(('https://', 'http://')):
            continue
        results.append(WebResult(
            id='',
            title=(row.get('title') or _domain(url)).strip(),
            url=url,
            domain=_domain(url),
            snippet=re.sub(r'<[^>]+>', '', row.get('description') or '').strip(),
            age=row.get('age'),
        ))
    return results


def _unwrap_ddg_url(value: str) -> str:
    if value.startswith('//'):
        value = 'https:' + value
    parsed = urlparse(value)
    if 'duckduckgo.com' in parsed.netloc:
        target = parse_qs(parsed.query).get('uddg', [''])[0]
        if target:
            return unquote(target)
    return value


async def _search_automatic(query: str) -> list[WebResult]:
    """Keyless fallback for Lino's default user experience.

    It uses DuckDuckGo's HTML result page so users can search the public web without
    creating an API account. Brave remains available as an optional advanced provider.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.7',
    }
    async with httpx.AsyncClient(timeout=18.0, follow_redirects=True, headers=headers) as client:
        response = await client.get('https://html.duckduckgo.com/html/', params={'q': query, 'kl': 'fr-fr'})
        response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    results: list[WebResult] = []
    for block in soup.select('.result'):
        link = block.select_one('.result__a')
        if not link:
            continue
        url = _unwrap_ddg_url(str(link.get('href') or '').strip())
        if not url.startswith(('https://', 'http://')):
            continue
        snippet_el = block.select_one('.result__snippet')
        title = link.get_text(' ', strip=True)
        snippet = snippet_el.get_text(' ', strip=True) if snippet_el else ''
        results.append(WebResult('', title or _domain(url), url, _domain(url), snippet, None))
        if len(results) >= min(max(settings.web_results, 3), 12):
            break
    return results


async def search_web(query: str, freshness: str | None = None) -> list[WebResult]:
    """Search the public web with zero setup by default.

    Brave Search is used when a key is configured; otherwise Lino transparently uses
    the automatic keyless provider.
    """
    query = query.strip()
    if not query:
        return []
    try:
        results = await (_search_brave(query, freshness) if _brave_key() else _search_automatic(query))
    except Exception as exc:
        raise RuntimeError('La recherche Web est momentanément indisponible. Réessaie dans quelques instants.') from exc

    ranked = [(item, _score(item, i)) for i, item in enumerate(results)]
    ordered = [item for item, _ in sorted(ranked, key=lambda pair: pair[1], reverse=True)]
    for i, item in enumerate(ordered, 1):
        item.id = f'S{i}'
    return ordered


def web_mode() -> str:
    return 'brave' if _brave_key() else 'automatic'


def results_for_model(results: list[WebResult]) -> str:
    return '\n\n'.join(
        f'[{r.id}] {r.title}\nSource: {r.domain}\nURL: {r.url}\nExtrait: {r.snippet}'
        for r in results
    )
