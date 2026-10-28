"""
OM Search - High-Performance SQLite FTS5 Search Repository (Phase 4 Massive Scale)
Enables sub-10ms BM25 ranking across 100k, 1M, and 10M+ documents with zero RAM bloat.
Disk-backed B-Tree storage + inverted index with native snippet highlighting and WAL mode.
"""
import os
import re
import time
import sqlite3
import logging
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
import math
from datetime import datetime, timezone

from app.core.config import get_settings

logger = logging.getLogger("om_repositories.sqlite_fts")


class SQLiteFTSRepository:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        self.settings = get_settings()
        if db_path:
            self.db_path = Path(db_path)
        else:
            backend_dir = Path(__file__).resolve().parents[2]
            root_dir = Path(__file__).resolve().parents[3]
            candidates = [
                backend_dir / "om_search_local.db",
                Path("backend/om_search_local.db"),
                Path("om_search_local.db"),
                root_dir / "backend" / "om_search_local.db",
                root_dir / "om_search_local.db",
                backend_dir / "om_search_fts.db",
                Path("backend/om_search_fts.db"),
                Path("om_search_fts.db"),
            ]
            self.db_path = (backend_dir / "om_search_local.db").resolve()
            for c in candidates:
                if c.exists() and c.stat().st_size > 1000:
                    self.db_path = c.resolve()
                    break

        self._local = threading.local()
        self._init_db()

    @classmethod
    def get_instance(cls, db_path: Optional[str] = None) -> "SQLiteFTSRepository":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = SQLiteFTSRepository(db_path)
        return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Maximize read/write throughput on SSD/NVMe
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA cache_size = -64000;")  # 64 MB RAM cache
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA mmap_size = 268435456;")  # 256 MB memory-mapped I/O
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        """Idempotently initialize documents table, FTS5 virtual table, and triggers."""
        conn = self._get_connection()
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE,
                url TEXT UNIQUE,
                canonical_url TEXT,
                domain TEXT,
                title TEXT,
                snippet TEXT,
                content TEXT,
                language TEXT DEFAULT 'en',
                document_type TEXT DEFAULT 'webpage',
                published_at TEXT,
                indexed_at TEXT,
                pagerank REAL DEFAULT 0.0
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_domain ON documents(domain);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_title ON documents(title);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_id ON documents(id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_url ON documents(url);")

            # Check if FTS5 virtual table exists
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents_fts';")
            if not cur.fetchone():
                conn.execute("""
                CREATE VIRTUAL TABLE documents_fts USING fts5(
                    title,
                    snippet,
                    content,
                    content='documents',
                    content_rowid='rowid',
                    tokenize = 'porter unicode61 remove_diacritics 1'
                );
                """)
                # Populate FTS5 table from existing documents if any exist
                conn.execute("""
                INSERT INTO documents_fts(rowid, title, snippet, content)
                SELECT rowid, title, snippet, content FROM documents;
                """)

            # Triggers to keep FTS in sync with documents table
            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
              INSERT INTO documents_fts(rowid, title, snippet, content)
              VALUES (new.rowid, new.title, new.snippet, new.content);
            END;
            """)

            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
              INSERT INTO documents_fts(documents_fts, rowid, title, snippet, content)
              VALUES('delete', old.rowid, old.title, old.snippet, old.content);
            END;
            """)

            conn.execute("""
            CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
              INSERT INTO documents_fts(documents_fts, rowid, title, snippet, content)
              VALUES('delete', old.rowid, old.title, old.snippet, old.content);
              INSERT INTO documents_fts(rowid, title, snippet, content)
              VALUES (new.rowid, new.title, new.snippet, new.content);
            END;
            """)

            # Reconcile counts if needed (ensure FTS5 has all documents indexed)
            try:
                cur = conn.execute("SELECT COUNT(*) FROM documents_fts;")
                fts_c = cur.fetchone()[0]
                cur = conn.execute("SELECT COUNT(*) FROM documents;")
                doc_c = cur.fetchone()[0]
                if fts_c == 0 and doc_c > 0:
                    conn.execute("INSERT INTO documents_fts(rowid, title, snippet, content) SELECT rowid, title, snippet, content FROM documents;")
            except Exception:
                pass

    def _build_fts_query(self, query_text: str, mode: str = "and") -> str:
        """
        Build safe, precision-focused FTS5 query strings.
        - 'and': Requires ALL keywords to match (near-100% precision for specific search terms).
        - 'phrase': Matches exact continuous multi-word phrase.
        - 'or': Fallback matching any keyword when strict AND yields 0 documents.
        """
        tokens = [t for t in re.findall(r'[\w]+', query_text.lower()) if len(t) >= 1]
        if not tokens:
            return ""
        if len(tokens) == 1:
            return f'"{tokens[0]}"*'
        if mode == "phrase":
            return f'"{ " ".join(tokens) }"'
        elif mode == "and":
            return " AND ".join(f'"{t}"*' for t in tokens)
        else:
            return " OR ".join(f'"{t}"*' for t in tokens)

    def _sanitize_fts_query(self, query_text: str) -> str:
        """Backward-compatible helper returning AND query for strict keyword precision."""
        return self._build_fts_query(query_text, mode="and")

    def index_document(self, doc_dict: Dict[str, Any]) -> bool:
        """Index or update a single document."""
        conn = self._get_connection()
        doc_id = doc_dict.get("id") or doc_dict.get("url")
        url = doc_dict.get("url") or doc_id
        canon = doc_dict.get("canonical_url") or url
        dom = doc_dict.get("domain") or ""
        title = doc_dict.get("title") or ""
        snippet = doc_dict.get("snippet") or ""
        content = doc_dict.get("content") or ""
        lang = doc_dict.get("language") or "en"
        doc_type = doc_dict.get("document_type") or "webpage"
        pub = str(doc_dict.get("published_at") or "")
        idx_at = str(doc_dict.get("indexed_at") or datetime.now(timezone.utc).isoformat())
        pr = float(doc_dict.get("pagerank") or 0.0)

        with conn:
            # Check existing row
            cur = conn.execute("SELECT rowid FROM documents WHERE id = ? OR url = ?", (doc_id, url))
            row = cur.fetchone()
            if row:
                rowid = row[0]
                conn.execute("""
                UPDATE documents SET
                    id = ?, url = ?, canonical_url = ?, domain = ?, title = ?,
                    snippet = ?, content = ?, language = ?, document_type = ?,
                    published_at = ?, indexed_at = ?, pagerank = ?
                WHERE rowid = ?
                """, (doc_id, url, canon, dom, title, snippet, content, lang, doc_type, pub, idx_at, pr, rowid))
            else:
                conn.execute("""
                INSERT INTO documents (
                    id, url, canonical_url, domain, title, snippet, content,
                    language, document_type, published_at, indexed_at, pagerank
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (doc_id, url, canon, dom, title, snippet, content, lang, doc_type, pub, idx_at, pr))
        return True

    def index_documents_bulk(self, docs: List[Dict[str, Any]]) -> int:
        """Bulk index documents inside a single high-speed transaction."""
        if not docs:
            return 0
        conn = self._get_connection()
        records_to_insert = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for d in docs:
            doc_id = d.get("id") or d.get("url")
            url = d.get("url") or doc_id
            canon = d.get("canonical_url") or url
            dom = d.get("domain") or ""
            title = d.get("title") or ""
            snippet = d.get("snippet") or ""
            content = d.get("content") or ""
            lang = d.get("language") or "en"
            doc_type = d.get("document_type") or "webpage"
            pub = str(d.get("published_at") or "")
            idx_at = str(d.get("indexed_at") or now_iso)
            pr = float(d.get("pagerank") or 0.0)

            records_to_insert.append((
                doc_id, url, canon, dom, title, snippet, content,
                lang, doc_type, pub, idx_at, pr
            ))

        with conn:
            conn.executemany("""
            INSERT OR REPLACE INTO documents (
                id, url, canonical_url, domain, title, snippet, content,
                language, document_type, published_at, indexed_at, pagerank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records_to_insert)

        return len(records_to_insert)

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve document by ID."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM documents WHERE id = ? OR url = ? LIMIT 1", (doc_id, doc_id))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def search_documents(self, query_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute BM25 search across SQLite FTS5 index.
        Matches OpenSearch response schema with sub-10ms execution.
        """
        t0 = time.perf_counter()
        from_offset = query_body.get("from", 0)
        size = query_body.get("size", 10)

        # Extract search terms and filters from Elasticsearch/OpenSearch query body
        query_text = ""
        domain_filter = None
        lang_filter = None

        try:
            must_clauses = query_body.get("query", {}).get("bool", {}).get("must", [])
            for m in must_clauses:
                for should in m.get("bool", {}).get("should", []):
                    if "multi_match" in should:
                        query_text = should["multi_match"].get("query", "")
                        break
            filters = query_body.get("query", {}).get("bool", {}).get("filter", [])
            for f in filters:
                if "term" in f:
                    if "domain" in f["term"]:
                        domain_filter = f["term"]["domain"]
                    if "language" in f["term"]:
                        lang_filter = f["term"]["language"]
        except Exception:
            pass

        if not query_text and isinstance(query_body.get("query"), str):
            query_text = query_body["query"]
        elif not query_text and isinstance(query_body.get("q"), str):
            query_text = query_body["q"]

        clean_q = query_text.strip()
<<<<<<< HEAD
        tokens = [t for t in re.findall(r'[\w]+', clean_q.lower()) if len(t) >= 1]
=======
        fts_query = self._sanitize_fts_query(clean_q, strict=True)
>>>>>>> 87191bf (feat(seo): add Google Search Console verification, sitemap.xml, robots.txt, and SEO metadata)

        conn = self._get_connection()
        hits: List[Dict[str, Any]] = []
        total_count = 0

<<<<<<< HEAD
        if tokens:
            # 1. Build strict AND query first to ensure all specific keywords are in matched docs
            fts_query_and = self._build_fts_query(clean_q, mode="and")
            fts_query_or = self._build_fts_query(clean_q, mode="or")

            # Check if strict AND produces results
            try:
                cur = conn.execute("SELECT COUNT(*) FROM documents_fts WHERE documents_fts MATCH ?", [fts_query_and])
                count_and = cur.fetchone()[0]
            except Exception:
                count_and = 0

            fts_query = fts_query_and if count_and > 0 else fts_query_or

            # Prepare parameters for exact title and phrase match boost
            phrase_pattern = f"%{clean_q.lower()}%"
            primary_token_pattern = f"%{tokens[0]}%"

=======
        if fts_query:
            if not domain_filter and not lang_filter:
                try:
                    cur = conn.execute("SELECT COUNT(*) FROM documents_fts WHERE documents_fts MATCH ?", [fts_query])
                    total_count = cur.fetchone()[0]
                except Exception:
                    total_count = 0

                # If fewer than 3 strict results exist, dynamically crawl & index pages for the searched words
                if total_count < 3 and len(clean_q) >= 2:
                    try:
                        from app.services.on_demand_indexer import get_on_demand_indexer
                        get_on_demand_indexer().crawl_and_index_query(clean_q)
                        cur = conn.execute("SELECT COUNT(*) FROM documents_fts WHERE documents_fts MATCH ?", [fts_query])
                        total_count = cur.fetchone()[0]
                    except Exception as e:
                        logger.debug("On-demand keyword indexing notice: %s", e)

                if total_count == 0 and len(clean_q.split()) > 1:
                    fts_query = self._sanitize_fts_query(clean_q, strict=False)
            # Full-text BM25 search with ranking weights (5.0 title, 2.0 snippet, 1.0 content)
>>>>>>> 87191bf (feat(seo): add Google Search Console verification, sitemap.xml, robots.txt, and SEO metadata)
            base_where = "WHERE documents_fts MATCH ?"
            params: List[Any] = [fts_query]

            if domain_filter:
                base_where += " AND d.domain = ?"
                params.append(domain_filter.strip().lower())
            if lang_filter:
                base_where += " AND d.language = ?"
                params.append(lang_filter.strip().lower())

            # Count total matching results
            count_sql = f"""
            SELECT COUNT(*) FROM documents_fts
            JOIN documents d ON documents_fts.rowid = d.rowid
            {base_where}
            """
            cur = conn.execute(count_sql, params)
            total_count = cur.fetchone()[0]

            # Candidate pool limit for reranking: fetch sufficient candidates to sort by accuracy
            sub_limit = min(500, max(size * 5, 50))

            select_sql = f"""
            SELECT 
                d.id, d.url, d.canonical_url, d.domain, d.title, d.snippet, d.content,
                d.language, d.document_type, d.published_at, d.indexed_at, d.pagerank,
                COALESCE(
                    snippet(documents_fts, 1, '<mark>', '</mark>', '...', 25),
                    snippet(documents_fts, 0, '<mark>', '</mark>', '...', 20),
                    d.snippet
                ) AS highlighted_snippet,
                -ranked.score AS bm25_score,
                (
                    CASE 
                        WHEN LOWER(d.title) = LOWER(?) THEN 100.0
                        WHEN LOWER(d.title) LIKE ? THEN 60.0
                        WHEN LOWER(d.title) LIKE ? THEN 30.0
                        ELSE 0.0 
                    END +
                    (-ranked.score * 2.0) +
                    (COALESCE(d.pagerank, 0.0) * 10.0)
                ) AS accuracy_score
            FROM (
                SELECT rowid, bm25(documents_fts, 15.0, 4.0, 1.0) AS score
                FROM documents_fts
                WHERE documents_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
            ) ranked
            JOIN documents_fts ON documents_fts.rowid = ranked.rowid
            JOIN documents d ON d.rowid = ranked.rowid
            {base_where.replace("documents_fts MATCH ?", "1=1")}
            ORDER BY accuracy_score DESC
            LIMIT ? OFFSET ?
            """
            cur = conn.execute(
                select_sql,
                [clean_q, phrase_pattern, primary_token_pattern, fts_query, sub_limit] + params[1:] + [size, from_offset]
            )
            rows = cur.fetchall()

            for r in rows:
                doc_dict = {
                    "id": r["id"],
                    "url": r["url"],
                    "canonical_url": r["canonical_url"],
                    "domain": r["domain"],
                    "title": r["title"],
                    "snippet": r["snippet"],
                    "content": r["content"],
                    "language": r["language"],
                    "document_type": r["document_type"],
                    "published_at": r["published_at"],
                    "indexed_at": r["indexed_at"],
                    "pagerank": float(r["pagerank"] or 0.0),
                }
                hl = r["highlighted_snippet"]
                highlight_dict = {"content": [hl]} if hl else {}
                score = round(float(r["accuracy_score"] if "accuracy_score" in r.keys() else (r["bm25_score"] or 1.0)), 4)

                hits.append({
                    "_id": r["id"],
                    "_score": max(0.01, score),
                    "_source": doc_dict,
                    "highlight": highlight_dict,
                })
        else:
            # Empty query or wildcard fallback: return most recent / highest authority docs
            base_where = "WHERE 1=1"
            params = []
            if domain_filter:
                base_where += " AND domain = ?"
                params.append(domain_filter)
            if lang_filter:
                base_where += " AND language = ?"
                params.append(lang_filter)

            cur = conn.execute(f"SELECT COUNT(*) FROM documents {base_where}", params)
            total_count = cur.fetchone()[0]

            cur = conn.execute(
                f"SELECT * FROM documents {base_where} ORDER BY pagerank DESC, rowid DESC LIMIT ? OFFSET ?",
                params + [size, from_offset],
            )
            for r in cur.fetchall():
                doc_dict = dict(r)
                hits.append({
                    "_id": r["id"],
                    "_score": 1.0 + float(r["pagerank"] or 0.0),
                    "_source": doc_dict,
                    "highlight": {},
                })

        took_ms = round((time.perf_counter() - t0) * 1000, 2)
        max_score = hits[0]["_score"] if hits else 0.0

        return {
            "took": int(took_ms),
            "timed_out": False,
            "hits": {
                "total": {"value": total_count, "relation": "eq"},
                "max_score": max_score,
                "hits": hits,
            },
        }

    def get_suggestions(self, prefix: str, size: int = 5) -> List[str]:
        """Fetch title prefix autocompletions using B-Tree index."""
        clean = prefix.strip().lower()
        if not clean:
            return []
        conn = self._get_connection()
        cur = conn.execute(
            "SELECT DISTINCT title FROM documents WHERE lower(title) LIKE ? ORDER BY length(title) ASC LIMIT ?",
            (f"{clean}%", size),
        )
        suggestions = [r[0] for r in cur.fetchall() if r[0]]

        if len(suggestions) < size:
            needed = size - len(suggestions)
            cur = conn.execute(
                "SELECT DISTINCT title FROM documents WHERE lower(title) LIKE ? AND lower(title) NOT LIKE ? LIMIT ?",
                (f"%{clean}%", f"{clean}%", needed),
            )
            for r in cur.fetchall():
                if r[0] and r[0] not in suggestions:
                    suggestions.append(r[0])

        return suggestions[:size]

    def get_stats(self) -> Dict[str, Any]:
        """Fetch index document totals and top domain aggregations."""
        conn = self._get_connection()
        cur = conn.execute("SELECT COUNT(*) FROM documents;")
        total_docs = cur.fetchone()[0]

        cur = conn.execute("SELECT COUNT(DISTINCT domain) FROM documents WHERE domain IS NOT NULL AND domain != '';")
        domains_count = cur.fetchone()[0]

        cur = conn.execute("SELECT COUNT(*) FROM documents WHERE document_type = 'live_web_page';")
        live_crawled_count = cur.fetchone()[0]

        cur = conn.execute("""
        SELECT domain, COUNT(*) as cnt 
        FROM documents 
        WHERE domain IS NOT NULL AND domain != ''
        GROUP BY domain 
        ORDER BY cnt DESC 
        LIMIT 10;
        """)
        top_domains = [{"domain": r["domain"], "doc_count": r["cnt"]} for r in cur.fetchall()]

        # Read live ingestion telemetry if present
        cloud_archived_count = 0
        cloud_storage_formatted = "0 MB"
        try:
            import json
            from pathlib import Path
            status_candidates = [
                Path(__file__).resolve().parent.parent / "ingestion" / "drive_ingestion_live_status.json",
                Path(__file__).resolve().parents[2] / "data" / "drive_ingestion_live_status.json",
                Path("data/drive_ingestion_live_status.json"),
                Path("../data/drive_ingestion_live_status.json"),
            ]
            for status_p in status_candidates:
                if status_p.exists():
                    with open(status_p, "r", encoding="utf-8") as f:
                        s_data = json.load(f)
                        cloud_archived_count = s_data.get("total_documents_archived", 0)
                        cloud_storage_formatted = s_data.get("formatted_cloud_storage", "0 MB")
                        live_crawled_count = max(live_crawled_count, s_data.get("live_crawled_pages_count", 0))
                    break
        except Exception:
            pass
        try:
            from app.repositories.database import get_db_manager, DriveUploadBatch
            from sqlalchemy import func
            db = get_db_manager().get_session()
            db_docs = db.query(func.sum(DriveUploadBatch.record_count)).filter(DriveUploadBatch.upload_status == "verified").scalar()
            db_bytes = db.query(func.sum(DriveUploadBatch.compressed_bytes)).filter(DriveUploadBatch.upload_status == "verified").scalar()
            db.close()
            if db_docs and int(db_docs) > cloud_archived_count:
                cloud_archived_count = int(db_docs)
                if db_bytes:
                    if db_bytes >= 1024**3:
                        cloud_storage_formatted = f"{db_bytes / (1024**3):.2f} GB"
                    else:
                        cloud_storage_formatted = f"{db_bytes / (1024**2):.2f} MB"
        except Exception:
            pass

        return {
            "total_documents": max(total_docs, cloud_archived_count) if cloud_archived_count else total_docs,
            "live_crawled_count": live_crawled_count,
            "cloud_archived_count": cloud_archived_count,
            "cloud_storage_formatted": cloud_storage_formatted,
            "index_name": "sqlite_fts5_om_index",
            "index_alias": "om_documents",
            "status": "online_fts5",
            "domains_count": domains_count,
            "top_domains": top_domains,
        }

    def get_crawled_pages(
        self,
        page: int = 1,
        size: int = 20,
        domain: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch real crawled web pages from SQLite index with pagination and domain filter."""
        conn = self._get_connection()
        where_clauses = ["document_type = 'live_web_page'"]
        params = []
        if domain:
            where_clauses.append("domain = ?")
            params.append(domain.strip().lower())
        if query:
            where_clauses.append("(title LIKE ? OR snippet LIKE ? OR url LIKE ?)")
            clean_q = f"%{query.strip()}%"
            params.extend([clean_q, clean_q, clean_q])

        where_sql = " AND ".join(where_clauses)
        cur = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where_sql}", params)
        total = cur.fetchone()[0]

        offset = max(0, (page - 1) * size)
        cur = conn.execute(
            f"SELECT id, url, domain, title, snippet, indexed_at, pagerank FROM documents WHERE {where_sql} ORDER BY pagerank DESC, rowid DESC LIMIT ? OFFSET ?",
            params + [size, offset],
        )
        items = [dict(r) for r in cur.fetchall()]

        # Top crawled domains breakdown
        cur = conn.execute(
            "SELECT domain, COUNT(*) as cnt FROM documents WHERE document_type = 'live_web_page' GROUP BY domain ORDER BY cnt DESC LIMIT 20;"
        )
        top_domains = [{"domain": r["domain"], "count": r["cnt"]} for r in cur.fetchall()]

        if not items:
            try:
                import json
                from pathlib import Path
                json_candidates = [
                    Path(__file__).resolve().parents[2] / "data" / "crawled_batch_live.json",
                    Path("data/crawled_batch_live.json"),
                ]
                for j_path in json_candidates:
                    if j_path.exists():
                        with open(j_path, "r", encoding="utf-8") as f:
                            raw_pages = json.load(f)
                            if domain:
                                raw_pages = [p for p in raw_pages if p.get("domain") == domain]
                            if query:
                                q_lower = query.lower()
                                raw_pages = [p for p in raw_pages if q_lower in f"{p.get('title','')} {p.get('snippet','')} {p.get('url','')}".lower()]
                            total = len(raw_pages)
                            items = raw_pages[offset : offset + size]
                            break
            except Exception:
                pass

        return {
            "total": total,
            "page": page,
            "size": size,
            "total_pages": math.ceil(total / size) if total > 0 else 0,
            "items": items,
            "top_domains": top_domains,
        }

    def count(self) -> int:
        conn = self._get_connection()
        cur = conn.execute("SELECT COUNT(*) FROM documents;")
        return cur.fetchone()[0]


def get_sqlite_fts_repo() -> SQLiteFTSRepository:
    return SQLiteFTSRepository.get_instance()
