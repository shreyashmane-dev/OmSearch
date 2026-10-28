# OM Search — Independent Web Search Engine (Phases 1, 2 & 3)

OM Search is an independent, general-purpose open web search engine foundation. It is **not** a metasearch proxy, an LLM wrapper, or a chatbot. Its objective is to build a controlled crawler, persistent URL frontier, document store, search index, relevance-ranking system, and search interface from the ground up.

- **Phase 1: Engine Foundation**: Search engine core, OpenSearch BM25 ranking, PostgreSQL metadata store, and React frontend.
- **Phase 2: Independent Web Crawler**: Polite, robust crawler with persistent database frontier, anti-SSRF protections, Protego-based robots.txt compliance, Trafilatura HTML content extraction, content deduplication, and operator APIs.
- **Phase 3: Ranking Intelligence & Evaluation**: Two-stage retrieval with multi-feature reranking, offline PageRank authority graph, query intent understanding, synonyms, freshness decay, content quality & anti-spam scoring, near-duplicate suppression, and formal IR evaluation (MRR, MAP, NDCG@10) with an ablation experiment suite.

---

## ⚡ Quickstart (Run in 60 Seconds)

Whether you are on Windows, macOS, or Linux, you can run the entire engine with one command:

```bash
# Windows (Double-click or run):
setup.bat

# Linux / macOS:
chmod +x setup.sh && ./setup.sh

# Or Universal Cross-Platform:
python setup.py
```

To launch both Backend (`http://127.0.0.1:8000`) and Frontend (`http://127.0.0.1:5173`) simultaneously:
```bash
# Windows:
start.bat

# Linux / macOS:
./start.sh
```

👉 See [SETUP.md](file:///d:/Projects/Om%20Search%20Engine/SETUP.md) for full setup options, environment variables, and cloud continuous indexing instructions.

---

## Architecture Overview

```
om-search/
├── backend/                  # FastAPI Search Engine API & Services
│   ├── app/
│   │   ├── api/v1/           # API routes (/health, /search, /suggestions, /stats)
│   │   ├── core/             # Configuration, logging, bounds
│   │   ├── schemas/          # Pydantic v2 validation models
│   │   ├── services/         # SearchService, HealthService
│   │   ├── repositories/     # OpenSearchRepository, DatabaseManager (Postgres/SQLite)
│   │   ├── ranking/          # BM25 query construction, analyzers, tie-breaking
│   │   └── ingestion/        # Normalizer, deduplication, pipeline
│   ├── tests/                # Pytest unit & integration test suite (25 tests)
│   ├── pyproject.toml        # Python 3.12 dependencies
│   └── Dockerfile
├── frontend/                 # React 19 + TypeScript + Vite Search Interface
│   ├── src/
│   │   ├── components/       # SearchBar, SearchResultCard, StatsModal
│   │   ├── App.tsx           # Search home, results layout, pagination
│   │   └── index.css         # Dark theme tokens, accessible layouts
│   ├── package.json          # Node dependencies & Vitest suite
│   ├── Dockerfile
│   └── nginx.conf
├── crawler/                  # Crawling abstractions for Phase 2
│   └── om_crawler/           # Interfaces (ICrawler, IFrontier, IRobotsParser)
├── infrastructure/           # Local container orchestration
│   ├── docker-compose.yml    # OpenSearch, PostgreSQL, Backend, Frontend
│   ├── opensearch/           # Cluster config & analyzer settings
│   └── postgres/             # Database schema & indexes (init.sql)
├── scripts/
│   ├── sample_corpus.json    # Traceable, legally usable sample documentation corpus
│   ├── ingest_corpus.py      # Reproducible ingestion script
│   └── manage_index.py       # OpenSearch index migration & lifecycle CLI
├── docs/
│   ├── ARCHITECTURE.md       # Detailed system design & pipeline lifecycle
│   └── ROADMAP.md            # Crawling, ranking, evaluation, and scaling roadmap
├── .env.example              # Environment variables template
├── .gitignore
├── LICENSE                   # Apache 2.0
└── README.md
```

---

## Hardware & Memory Requirements

- **Target Machine**: Standard laptop (Windows / macOS / Linux) with 16 GB RAM.
- **OpenSearch Heap**: Configured strictly to `-Xms512m -Xmx512m` in `docker-compose.yml` to prevent high memory usage.
- **PostgreSQL**: Lightweight Alpine image (~30 MB RAM).
- **Backend & Frontend**: ~100 MB RAM each.
- **Total Local Footprint**: < 1.2 GB RAM total.

---

## Prerequisites

1. **Python**: Python 3.12 (`Python 3.12.10` or higher)
2. **Node.js**: Node.js 20+ and npm
3. **Docker & Docker Compose**: (Optional for container stack; native execution supported)
   - On Windows, Docker Desktop requires WSL 2 (`wsl.exe --install`).

---

## Quickstart: Native Local Development (No Docker Required)

OM Search includes resilient storage fallbacks (local SQLite and in-memory cache) so developers can run, test, and index immediately without waiting for Docker:

### 1. Backend Setup

```bash
# In project root:
py -3.12 -m venv .venv
.\.venv\Scripts\activate

# Install backend dependencies:
pip install -e backend/.[dev]

# Ingest the verified sample corpus:
python scripts/ingest_corpus.py

# Start the FastAPI backend:
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

The API will be available at `http://127.0.0.1:8000` (Interactive docs: `http://127.0.0.1:8000/docs`).

### 2. Frontend Setup

In a new terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Quickstart: Docker Compose Stack

To run the complete production-like stack with OpenSearch 2.18 and PostgreSQL 16:

```bash
# Ensure Docker Desktop is running, then in infrastructure/:
cd infrastructure
docker compose up -d

# Verify services:
docker compose ps

# Ingest sample corpus into OpenSearch:
python ../scripts/ingest_corpus.py

# Access:
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# OpenSearch: http://localhost:9200
```

To stop the stack and preserve index data:
```bash
docker compose down
```

To stop and remove volumes:
```bash
docker compose down -v
```

---

## Search API Specification

### 1. Service Health Check
```bash
curl -s http://127.0.0.1:8000/api/v1/health
```
Response:
```json
{
  "status": "healthy",
  "app_version": "0.1.0",
  "timestamp": "2026-10-10T08:45:00Z",
  "services": {
    "opensearch": { "status": "healthy", "latency_ms": 1.2 },
    "database": { "status": "healthy", "latency_ms": 0.8 }
  }
}
```

### 2. Search Query
```bash
curl -s "http://127.0.0.1:8000/api/v1/search?q=python&page=1&size=5"
```
Response:
```json
{
  "query": "python",
  "total": 1,
  "page": 1,
  "size": 5,
  "total_pages": 1,
  "took_ms": 1.8,
  "is_early_index": true,
  "results": [
    {
      "id": "e6a4b123...",
      "url": "https://docs.python.org/3/tutorial/introduction.html",
      "canonical_url": "https://docs.python.org/3/tutorial/introduction.html",
      "domain": "docs.python.org",
      "title": "An Informal Introduction to Python - Python 3 Documentation",
      "snippet": "Python is an easy to learn, powerful programming language...",
      "score": 3.42,
      "language": "en"
    }
  ]
}
```
*Note: If no indexed documents match, the engine returns `"total": 0, "results": []`. It never fabricates results.*

### 3. Autocomplete Suggestions
```bash
curl -s "http://127.0.0.1:8000/api/v1/suggestions?q=py"
```

### 4. Index Telemetry & Statistics
```bash
curl -s http://127.0.0.1:8000/api/v1/search/stats
```

---

## Index Management CLI

Manage the OpenSearch mapping without the dashboard:

```bash
# Check index status:
python scripts/manage_index.py status

# Inspect full OpenSearch mapping:
python scripts/manage_index.py mapping

# Re-create fresh index:
python scripts/manage_index.py recreate
```

---

## Phase 2: Crawler Operations & CLI

The Phase 2 crawler operates independently from the search request path. It enforces strict politeness (per-host delays, robots.txt, concurrency caps) and SSRF defense (blocking private/loopback/cloud metadata ranges).

### 1. Running a Controlled Crawl via CLI

```bash
# Start a polite crawl from approved seed URLs:
python scripts/run_crawler.py start --seeds https://docs.python.org/3/ --max-pages 20 --max-depth 2 --delay 1.5

# Inspect aggregate frontier metrics:
python scripts/run_crawler.py stats

# Inspect recent crawl failures or blocked URLs:
python scripts/run_crawler.py failures --limit 10

# Reclaim leases from interrupted or dead workers:
python scripts/run_crawler.py reset-leases
```

### 2. Operator REST API Endpoints

The FastAPI backend exposes dedicated operator endpoints under `/api/v1/crawl/`:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/crawl/jobs` | `POST` | Spawn a controlled web crawl job from approved seed URLs |
| `/api/v1/crawl/jobs/{job_id}` | `GET` | Get real-time job progress (processed, indexed, failed) |
| `/api/v1/crawl/jobs/{job_id}/pause` | `POST` | Safely pause an active crawl job |
| `/api/v1/crawl/jobs/{job_id}/resume` | `POST` | Resume a paused crawl job |
| `/api/v1/crawl/jobs/{job_id}/cancel` | `POST` | Cancel an active crawl job |
| `/api/v1/crawl/stats` | `GET` | Retrieve aggregate frontier statistics by state |
| `/api/v1/crawl/failures` | `GET` | List recent crawl failures and diagnostic errors |

---

## Running the Automated Test Suites & Evaluation

### Backend Tests (Pytest)
Runs 74 automated tests covering query validation, BM25 scoring, URL normalization, anti-SSRF defenses, robots.txt directives, HTML extraction, frontier lifecycle, API endpoints, link graph PageRank, freshness, content quality & anti-spam, near-duplicate suppression, query understanding, and mathematical IR metrics:
```bash
.\.venv\Scripts\pytest.exe backend/tests/ -v
```

### Ranking Evaluation & Ablation Benchmarks (CLI)
Run offline Information Retrieval evaluation across the benchmark dataset:
```bash
# Evaluate active production ranking
python scripts/evaluate_ranking.py eval --out docs/experiments/evaluation_report.json

# Run side-by-side ablation experiment comparing all ranking variants
python scripts/evaluate_ranking.py ablation --out docs/experiments/ablation_report.json
```

### Frontend Tests (Vitest)
Runs UI interaction and rendering tests:
```bash
cd frontend
npm test
```

### Production Build Validation
```bash
cd frontend
npm run build
```

---

## Phase 4: Google Drive Cloud Archive & Cloud-First Architecture

OM Search integrates a personal Google One 5 TB plan as a durable, long-term cloud archive for web page data and manifests, completely eliminating permanent reliance on local ephemeral disk space.

### Architectural Separation Guarantee
1. **Search Query Path (Zero-Latency Guarantee)**:
   - User → Firebase Frontend → Render FastAPI → OpenSearch / SQLite FTS5 → Ranked Results → User.
   - **Google Drive is NEVER touched during user searches.** Sub-10ms query execution is strictly preserved.
2. **Durable Cloud Archiving (Background Asynchronous)**:
   - Live Crawler + Common Crawl Importer → Unified Ingestion Coordinator → Normalization & Identity → Compressed `.jsonl.gz` batches with SHA-256 checksums → Google Drive Storage Adapter (`OM-Search-Data/page-records/`) → Temporary local spool pruned immediately upon verified upload.
   - Metadata, upload manifests, and checkpoints remain durably in PostgreSQL (`drive_upload_batches`).

### Google Drive Target Folder Structure
```text
OM-Search-Data/
├── page-records/         # Cleaned, normalized page records in .jsonl.gz batches
├── archive-manifests/    # Batch manifests with checksums and record counts
├── index-exports/        # Versioned search index exports
└── ingestion-reports/    # Crawler and ingestion summary reports
```

### Cloud Deployment Setup (Firebase + Render)

#### 1. Google Cloud Console Configuration
1. Create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Drive API**.
3. Configure the OAuth Consent Screen (User Type: External, Scope: `https://www.googleapis.com/auth/drive.file`).
4. Create an **OAuth 2.0 Web Application Client ID**:
   - **Authorized Redirect URIs**:
     - Local Dev: `http://127.0.0.1:8000/api/v1/storage/google-drive/callback`
     - Render Production: `https://om-search-backend.onrender.com/api/v1/storage/google-drive/callback`
5. Note your `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

#### 2. Backend on Render (`render.yaml`)
- Runtime: Python 3.12 (`fastapi`, `uvicorn`, `sqlalchemy`, `google-api-python-client`)
- Configure environment variables in Render dashboard:
  - `GOOGLE_CLIENT_ID`: `<your-client-id>`
  - `GOOGLE_CLIENT_SECRET`: `<your-client-secret>`
  - `GOOGLE_REDIRECT_URI`: `https://om-search-backend.onrender.com/api/v1/storage/google-drive/callback`
  - `DATABASE_URL`: Connection string to Render PostgreSQL
  - `OPERATOR_API_KEY`: Strong random secret for operator authorization

#### 3. Frontend on Firebase Hosting (`firebase.json`)
```bash
# In frontend directory:
npm run build
firebase deploy --only hosting
```

#### 4. Connecting and Testing Google Drive
1. Open OM Search and click the **"Drive 5 TB"** button in the header.
2. Click **"Connect Account"** to initiate Google OAuth consent.
3. Upon approval, OM Search automatically creates the `OM-Search-Data/` folder hierarchy.
4. Run manual verification upload:
```bash
python scripts/test_drive_upload_batch.py
```
5. Run the reproducible latency benchmark:
```bash
python scripts/benchmark_search_latency.py
```

---

## Current Limitations & Disclaimers

1. **Early Index & Politeness**: The crawler is intentionally rate-limited (default ~1.5s delay per host, 1 concurrent request per domain) to respect target servers. It does not attempt full-web crawling or aggressive spidering.
2. **Network Defenses**: The crawler rejects private network IP ranges, loopback addresses, cloud metadata endpoints (`169.254.169.254`), and non-HTML assets. For production environments, routing through an egress proxy with an isolated network namespace is recommended.
3. **Phase 4 Cloud Architecture**: Google Drive is utilized as a durable cold archive and recovery source. Live search queries are strictly served by OpenSearch / SQLite FTS5 for low-latency retrieval.
4. **License**: Apache 2.0. Third-party dependencies: Protego (BSD-3-Clause), Trafilatura (GPL-3.0-or-later / Apache-2.0 compatible library usage), BeautifulSoup4 (MIT), httpx (BSD-3-Clause), google-api-python-client (Apache-2.0).
