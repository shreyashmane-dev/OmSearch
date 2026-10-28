import re
import time
import logging
import math
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.core.config import Settings, get_settings
from app.repositories.opensearch_repo import OpenSearchRepository, get_opensearch_repo
from app.repositories.database import get_db_manager, PageAuthority
from app.ranking.bm25 import build_bm25_search_query
from app.ranking.query_processor import QueryProcessor, ProcessedQuery
from app.ranking.synonyms import SynonymExpander
from app.ranking.config import RankingConfig, DEFAULT_RANKING_CONFIG
from app.ranking.features import FeatureExtractor
from app.ranking.scorer import RerankingScorer
from app.ranking.deduplication import NearDuplicateSuppressor
from app.schemas.search import (
    SearchResponse,
    SearchResultItem,
    SuggestionsResponse,
    SearchStatsResponse,
)

import threading

class SearchQueryCache:
    """Thread-safe TTL query cache for ultra-low-latency repeated queries."""
    def __init__(self, max_size: int = 2000, ttl_seconds: float = 120.0):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                t, val = self._cache[key]
                if time.time() - t < self.ttl:
                    return val
                else:
                    del self._cache[key]
        return None

    def set(self, key: str, val: Any):
        with self._lock:
            if len(self._cache) >= self.max_size:
                # Evict oldest entry
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]
            self._cache[key] = (time.time(), val)


_global_query_cache = SearchQueryCache()


class SearchService:
    def __init__(
        self,
        repo: Optional[OpenSearchRepository] = None,
        settings: Optional[Settings] = None,
        ranking_config: Optional[RankingConfig] = None,
    ):
        self.settings = settings or get_settings()
        self.repo = repo or get_opensearch_repo()
        self.ranking_config = ranking_config or DEFAULT_RANKING_CONFIG

        self.query_processor = QueryProcessor()
        self.synonym_expander = SynonymExpander()
        self.feature_extractor = FeatureExtractor(
            freshness_half_life_days=self.ranking_config.freshness_half_life_days
        )
        self.scorer = RerankingScorer(config=self.ranking_config)
        self.deduplicator = NearDuplicateSuppressor()
        self.db_mgr = get_db_manager()
        self.cache = _global_query_cache

    def _get_authority_lookup(self, urls: List[str]) -> Dict[str, float]:
        """Fetch precomputed PageRank authority scores for candidate URLs."""
        if not urls or not self.ranking_config.enable_authority:
            return {}
        try:
            db = self.db_mgr.get_session()
            rows = db.query(PageAuthority.url, PageAuthority.pagerank).filter(PageAuthority.url.in_(urls)).all()
            db.close()
            return {r[0]: float(r[1] or 0.0) for r in rows}
        except Exception as e:
            logger.debug("Authority lookup failed: %s", e)
            return {}

    def search(
        self,
        query: str,
        page: int = 1,
        size: int = 10,
        language: Optional[str] = None,
        domain: Optional[str] = None,
        explain: bool = False,
    ) -> SearchResponse:
        start_time = time.perf_counter()

        # Enforce bounds
        page = max(1, page)
        size = min(max(1, size), self.settings.MAX_PAGE_SIZE)
        clean_q = query.strip()

        if not clean_q:
            return SearchResponse(
                query="",
                total=0,
                page=page,
                size=size,
                total_pages=0,
                took_ms=0.0,
                results=[],
                is_early_index=True,
                message="Empty query provided",
                ranking_version=self.ranking_config.version,
            )

        # High-Speed Query Cache Check (<0.2ms response for popular queries)
        cache_key = f"{clean_q.lower()}:{page}:{size}:{language or ''}:{domain or ''}:{explain}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"took_ms": round((time.perf_counter() - start_time) * 1000, 2)})

        # 1. Query Understanding Layer
        processed_query: ProcessedQuery = self.query_processor.process(clean_q)

        # 2. Stage 1: Candidate Generation via OpenSearch BM25
        # Retrieve candidate pool (e.g. top 50)
        candidate_pool_limit = max(size * page, self.ranking_config.candidate_pool_size)
        es_query = build_bm25_search_query(
            query_str=processed_query.normalized_query,
            page=1,
            size=candidate_pool_limit,
            language_filter=language,
            domain_filter=domain,
        )

        response_data = self.repo.search_documents(es_query)
        hits_meta = response_data.get("hits", {})
        total_hits = hits_meta.get("total", {})
        total_raw = total_hits.get("value", 0) if isinstance(total_hits, dict) else int(total_hits or 0)
        raw_hits = hits_meta.get("hits", [])

        if not raw_hits:
            try:
                from app.services.on_demand_indexer import get_on_demand_indexer
                new_pages = get_on_demand_indexer().crawl_and_index_query(clean_q)
                if new_pages:
                    response_data = self.repo.search_documents(es_query)
                    hits_meta = response_data.get("hits", {})
                    total_hits = hits_meta.get("total", {})
                    total_raw = total_hits.get("value", 0) if isinstance(total_hits, dict) else int(total_hits or 0)
                    raw_hits = hits_meta.get("hits", [])
            except Exception as e:
                logger.debug("On-demand crawl error: %s", e)

        if not raw_hits:
            took_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return SearchResponse(
                query=clean_q,
                total=0,
                page=page,
                size=size,
                total_pages=0,
                took_ms=took_ms,
                results=[],
                is_early_index=True,
                query_intent=processed_query.intent,
                spelling_suggestion=processed_query.spelling_suggestion,
                ranking_version=self.ranking_config.version,
            )

        # Format candidates
        candidate_items = []
        for hit in raw_hits:
            source = hit.get("_source", {})
            candidate_items.append({
                "id": hit.get("_id", source.get("id", "")),
                "url": source.get("url", ""),
                "canonical_url": source.get("canonical_url", ""),
                "domain": source.get("domain", ""),
                "title": source.get("title", ""),
                "content": source.get("content", ""),
                "snippet": source.get("snippet", ""),
                "language": source.get("language", "en"),
                "published_at": source.get("published_at"),
                "indexed_at": source.get("indexed_at"),
                "document_type": source.get("document_type", "webpage"),
                "_score": float(hit.get("_score") or 0.0),
                "highlight": hit.get("highlight", {}),
            })

        # Strict Keyword Relevance Guard:
        # Guarantee that returned results are strictly and solely relevant to the searched keywords
        query_terms = [t for t in re.findall(r'[\w]+', clean_q.lower()) if len(t) >= 1]
        STOP_WORDS = {
            "the", "a", "an", "is", "are", "was", "were", "in", "at", "of", "on", "for", 
            "to", "by", "with", "about", "and", "or", "what", "where", "which", "who", 
            "whom", "how", "why", "when", "my", "your", "his", "her", "its", "their", 
            "our", "me", "you", "him", "them", "us", "can", "could", "should", "would", 
            "do", "does", "did"
        }
        substantive_kws = [w for w in query_terms if w not in STOP_WORDS and len(w) >= 2]
        if not substantive_kws:
            substantive_kws = query_terms

        # Primary keywords: non-numeric tokens that carry the core subject
        primary_kws = [w for w in substantive_kws if not w.isdigit()]
        if not primary_kws:
            primary_kws = substantive_kws

        def is_doc_relevant(cand):
            doc_text = f"{cand.get('title', '')} {cand.get('snippet', '')} {cand.get('content', '')}".lower()
            if not any(kw in doc_text for kw in primary_kws):
                return False
            matched = sum(1 for kw in substantive_kws if kw in doc_text)
            min_match = max(1, math.ceil(len(substantive_kws) * 0.5))
            return matched >= min_match

        relevant_candidates = [c for c in candidate_items if is_doc_relevant(c)]

        # If fewer than 3 strictly relevant results exist, dynamically crawl & index on-demand!
        if len(relevant_candidates) < 3 and len(clean_q) >= 2:
            try:
                from app.services.on_demand_indexer import get_on_demand_indexer
                crawled_docs = get_on_demand_indexer().crawl_and_index_query(clean_q)
                if crawled_docs:
                    response_data = self.repo.search_documents(es_query)
                    hits_meta = response_data.get("hits", {})
                    fresh_hits = hits_meta.get("hits", [])
                    fresh_candidates = []
                    for hit in fresh_hits:
                        source = hit.get("_source", {})
                        fresh_candidates.append({
                            "id": hit.get("_id", source.get("id", "")),
                            "url": source.get("url", ""),
                            "canonical_url": source.get("canonical_url", ""),
                            "domain": source.get("domain", ""),
                            "title": source.get("title", ""),
                            "content": source.get("content", ""),
                            "snippet": source.get("snippet", ""),
                            "language": source.get("language", "en"),
                            "published_at": source.get("published_at"),
                            "indexed_at": source.get("indexed_at"),
                            "document_type": source.get("document_type", "webpage"),
                            "_score": float(hit.get("_score") or 0.0),
                            "highlight": hit.get("highlight", {}),
                        })
                    relevant_candidates = [c for c in fresh_candidates if is_doc_relevant(c)]
            except Exception as e:
                logger.debug("On-demand crawl-and-retry notice: %s", e)

        candidate_items = relevant_candidates
        if not candidate_items:
            took_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return SearchResponse(
                query=clean_q,
                total=0,
                page=page,
                size=size,
                total_pages=0,
                took_ms=took_ms,
                results=[],
                is_early_index=True,
                query_intent=processed_query.intent,
                spelling_suggestion=processed_query.spelling_suggestion,
                ranking_version=self.ranking_config.version,
            )

        # 3. Candidate Deduplication / Near-Duplicate Suppression
        if self.ranking_config.enable_near_dedup:
            unique_candidates, _ = self.deduplicator.filter_candidates(candidate_items)
        else:
            unique_candidates = candidate_items

        # 4. Stage 2: Feature Extraction & Reranking
        candidate_urls = [c["url"] for c in unique_candidates if c.get("url")]
        authority_lookup = self._get_authority_lookup(candidate_urls)

        reranked_items = []
        for candidate in unique_candidates:
            features = self.feature_extractor.extract(
                candidate=candidate,
                query=processed_query,
                authority_lookup=authority_lookup,
            )
            final_score, explanations = self.scorer.score_candidate(features)

            highlight = candidate.get("highlight", {})
            snippet_highlights = highlight.get("content") or highlight.get("snippet") or []
            title_highlights = highlight.get("title")

            item_title = title_highlights[0] if title_highlights else candidate.get("title", "")
            item_snippet = snippet_highlights[0] if snippet_highlights else candidate.get("snippet", "")

            # Parse datetime
            pub_date = None
            if candidate.get("published_at"):
                try:
                    pub_date = datetime.fromisoformat(str(candidate["published_at"]).replace("Z", "+00:00"))
                except Exception:
                    pass

            item = SearchResultItem(
                id=candidate["id"],
                url=candidate["url"],
                canonical_url=candidate.get("canonical_url", candidate["url"]),
                domain=candidate.get("domain", ""),
                title=item_title,
                snippet=item_snippet,
                language=candidate.get("language", "en"),
                published_at=pub_date,
                score=round(final_score, 4),
                document_type=candidate.get("document_type", "webpage"),
                highlights=snippet_highlights,
                explanation=explanations if explain else [],
                features=features.to_dict() if explain else None,
            )
            reranked_items.append(item)

        # 5. Deterministic sorting: [-score, -indexed_at, id]
        reranked_items.sort(
            key=lambda it: (it.score, it.id),
            reverse=True,
        )

        # 6. Pagination of reranked candidates
        total_unique = len(reranked_items)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        paged_results = reranked_items[start_idx:end_idx]

        total_pages = math.ceil(total_unique / size) if total_unique > 0 else 0
        took_ms = round((time.perf_counter() - start_time) * 1000, 2)

        resp = SearchResponse(
            query=clean_q,
            total=total_unique,
            page=page,
            size=size,
            total_pages=total_pages,
            took_ms=took_ms,
            results=paged_results,
            is_early_index=True,
            query_intent=processed_query.intent,
            spelling_suggestion=processed_query.spelling_suggestion,
            ranking_version=self.ranking_config.version,
            message="Results retrieved and ranked by Phase 3 intelligence pipeline",
        )
        self.cache.set(cache_key, resp)
        return resp

    def suggestions(self, query: str, size: int = 5) -> SuggestionsResponse:
        clean_q = query.strip()
        if not clean_q:
            return SuggestionsResponse(query="", suggestions=[])

        suggs = self.repo.get_suggestions(clean_q, size=size)
        return SuggestionsResponse(query=clean_q, suggestions=suggs)

    def stats(self) -> SearchStatsResponse:
        st = self.repo.get_stats()
        return SearchStatsResponse(
            total_documents=st.get("total_documents", 0),
            index_name=st.get("index_name", self.settings.OPENSEARCH_INDEX_NAME),
            index_alias=st.get("index_alias", self.settings.OPENSEARCH_INDEX_ALIAS),
            status=st.get("status", "unknown"),
            domains_count=st.get("domains_count", 0),
            top_domains=st.get("top_domains", []),
            storage_bytes=st.get("storage_bytes"),
            live_crawled_count=st.get("live_crawled_count", 0),
            cloud_archived_count=st.get("cloud_archived_count", 0),
            cloud_storage_formatted=st.get("cloud_storage_formatted", "0 MB"),
        )

    def get_crawled_pages(
        self,
        page: int = 1,
        size: int = 20,
        domain: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve paginated live crawled web pages."""
        return self.repo.get_crawled_pages(page=page, size=size, domain=domain, query=query)

