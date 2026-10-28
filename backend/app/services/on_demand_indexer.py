import re
import time
import json
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

from app.repositories.sqlite_fts_repo import get_sqlite_fts_repo

logger = logging.getLogger("om_on_demand_indexer")

_project_root = Path(__file__).resolve().parents[2]
_keywords_queue_file = _project_root / "data" / "searched_keywords_queue.json"


class OnDemandIndexer:
    """
    Dynamically crawls and indexes authoritative web documents based on user-searched keywords.
    Ensures that search results strictly and accurately reflect the words asked in the search box.
    """

    def __init__(self):
        self.fts_repo = get_sqlite_fts_repo()
        self._crawled_queries_cache: Dict[str, float] = {}
        self._cache_ttl = 120.0  # Avoid re-crawling identical queries within 2 minutes

    def record_searched_keyword(self, query: str):
        """Append user-searched keyword to the continuous daemon queue."""
        clean_q = query.strip()
        if not clean_q or len(clean_q) < 2:
            return

        try:
            _keywords_queue_file.parent.mkdir(parents=True, exist_ok=True)
            existing: List[str] = []
            if _keywords_queue_file.exists():
                try:
                    with open(_keywords_queue_file, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                except Exception:
                    existing = []

            if clean_q not in existing:
                existing.append(clean_q)
                # Keep last 500 searched keywords
                existing = existing[-500:]
                with open(_keywords_queue_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
        except Exception as e:
            logger.debug("Could not record searched keyword to queue: %s", e)

    def crawl_and_index_query(self, query: str, max_pages: int = 6) -> List[Dict[str, Any]]:
        """
        Fetch and index high-authority real-web pages specifically matching the searched keywords.
        Uses Wikipedia real-time search API and web authority discovery.
        """
        clean_q = query.strip()
        if not clean_q or len(clean_q) < 2:
            return []

        # Check in-memory crawl debounce cache
        q_key = clean_q.lower()
        now = time.time()
        if q_key in self._crawled_queries_cache:
            if now - self._crawled_queries_cache[q_key] < self._cache_ttl:
                return []

        self._crawled_queries_cache[q_key] = now
        self.record_searched_keyword(clean_q)

        indexed_docs: List[Dict[str, Any]] = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/json,application/xhtml+xml",
        }

        with httpx.Client(timeout=4.5, follow_redirects=True, headers=headers) as client:
            # 1. Authoritative Web Discovery (DuckDuckGo HTML search)
            try:
                resp = client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": clean_q},
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for row in soup.select(".result"):
                        if len(indexed_docs) >= max_pages:
                            break
                        t_el = row.select_one(".result__title a")
                        s_el = row.select_one(".result__snippet")
                        if not t_el or not s_el:
                            continue

                        raw_href = t_el.get("href", "")
                        # DuckDuckGo wraps URLs in /l/?kh=-1&uddg=...
                        actual_url = raw_href
                        if "uddg=" in raw_href:
                            import urllib.parse
                            parsed_uddg = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query).get("uddg")
                            if parsed_uddg:
                                actual_url = parsed_uddg[0]

                        if not actual_url.startswith("http"):
                            continue

                        dom = urlparse(actual_url).hostname or ""
                        if not dom or "duckduckgo.com" in dom:
                            continue

                        title_text = t_el.get_text(strip=True)
                        snippet_text = s_el.get_text(strip=True)

                        doc_id = hashlib.sha256(actual_url.encode()).hexdigest()[:16]
                        doc = {
                            "id": doc_id,
                            "url": actual_url,
                            "canonical_url": actual_url,
                            "domain": dom,
                            "title": title_text,
                            "snippet": snippet_text,
                            "content": f"{title_text}\n\n{snippet_text}",
                            "language": "en",
                            "document_type": "webpage",
                            "published_at": datetime.now(timezone.utc).isoformat(),
                            "indexed_at": datetime.now(timezone.utc).isoformat(),
                            "pagerank": 0.88,
                        }
                        self.fts_repo.index_document(doc)
                        indexed_docs.append(doc)
            except Exception as e:
                logger.debug("Web discovery search failed for '%s': %s", clean_q, e)

            # 2. Wikipedia High-Fidelity Encyclopedia API
            try:
                wiki_headers = {
                    "User-Agent": "OMSearchBot/1.0 (https://omsearch.web.app; contact@omsearch.com)"
                }
                wiki_resp = client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": clean_q,
                        "format": "json",
                    },
                    headers=wiki_headers,
                )
                if wiki_resp.status_code == 200:
                    search_hits = wiki_resp.json().get("query", {}).get("search", [])[:4]
                    page_ids = [str(hit["pageid"]) for hit in search_hits if hit.get("pageid")]
                    if page_ids:
                        extract_resp = client.get(
                            "https://en.wikipedia.org/w/api.php",
                            params={
                                "action": "query",
                                "prop": "extracts|info",
                                "inprop": "url",
                                "exintro": "1",
                                "explaintext": "1",
                                "pageids": "|".join(page_ids),
                                "format": "json",
                            },
                            headers=wiki_headers,
                        )
                        if extract_resp.status_code == 200:
                            pages_dict = extract_resp.json().get("query", {}).get("pages", {})
                            for pid, pdata in pages_dict.items():
                                if len(indexed_docs) >= max_pages * 2:
                                    break
                                full_url = pdata.get("fullurl") or f"https://en.wikipedia.org/?curid={pid}"
                                p_title = pdata.get("title", "")
                                p_extract = pdata.get("extract", "")
                                if not p_title or len(p_extract) < 50:
                                    continue

                                doc_id = hashlib.sha256(full_url.encode()).hexdigest()[:16]
                                doc = {
                                    "id": doc_id,
                                    "url": full_url,
                                    "canonical_url": full_url,
                                    "domain": "en.wikipedia.org",
                                    "title": f"{p_title} — Wikipedia",
                                    "snippet": p_extract[:240] + ("..." if len(p_extract) > 240 else ""),
                                    "content": p_extract,
                                    "language": "en",
                                    "document_type": "encyclopedia",
                                    "published_at": datetime.now(timezone.utc).isoformat(),
                                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                                    "pagerank": 0.95,
                                }
                                self.fts_repo.index_document(doc)
                                indexed_docs.append(doc)
            except Exception as e:
                logger.debug("Wikipedia on-demand crawl failed for '%s': %s", clean_q, e)

        logger.info(
            "On-demand indexed %d web pages for searched keyword '%s'",
            len(indexed_docs),
            clean_q,
        )
        return indexed_docs


_global_on_demand_indexer: Optional[OnDemandIndexer] = None


def get_on_demand_indexer() -> OnDemandIndexer:
    global _global_on_demand_indexer
    if _global_on_demand_indexer is None:
        _global_on_demand_indexer = OnDemandIndexer()
    return _global_on_demand_indexer
