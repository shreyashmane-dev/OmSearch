# 🚀 OM Search Engine — Quickstart & Setup Guide

Welcome to **OM Search**! This guide helps anyone who clones or downloads this repository to install, configure, and launch the full search engine in under 2 minutes.

---

## ⚡ 1-Minute Quickstart

### On Windows
Simply double-click:
```cmd
setup.bat
```
Or run in Command Prompt / PowerShell:
```powershell
python setup.py
```
To launch both Backend & Frontend together:
```cmd
start.bat
```

---

### On Linux / macOS / WSL
Open a terminal in the project directory:
```bash
chmod +x setup.sh start.sh
./setup.sh
```
To launch both Backend & Frontend together:
```bash
./start.sh
```

---

## 📋 What the Setup Script Automates
When you run `setup.py`, `setup.bat`, or `./setup.sh`, it automatically:
1. **Checks Prerequisites**: Validates Python 3.10+ and Node.js 18+ (npm).
2. **Creates Virtual Environment**: Initializes `.venv/` isolated from system packages.
3. **Installs Backend Dependencies**: Installs FastAPI, Uvicorn, SQLite FTS5, Google API Client, Cryptography, Scrapy, BeautifulSoup4, and all required packages.
4. **Initializes Configuration**: Automatically copies `.env.example` to `.env` and `backend/.env`.
5. **Installs Frontend Dependencies**: Installs React 19, Vite, Lucide Icons, and dependencies in `frontend/`.
6. **Verifies SQLite FTS5 Index**: Confirms that the high-speed local search index is ready to accept queries.
7. **Launches App**: Offers to immediately launch both Frontend and Backend.

---

## 🌐 Default Ports & Access Points

| Service | URL | Description |
| :--- | :--- | :--- |
| **Frontend UI** | `http://127.0.0.1:5173` | Modern glassmorphic search interface, live counter, dual-tab telemetry modal |
| **Backend API** | `http://127.0.0.1:8000` | FastAPI high-throughput ranking and retrieval engine |
| **Interactive Docs** | `http://127.0.0.1:8000/docs` | Swagger / OpenAPI interactive API explorer |
| **Health & Stats** | `http://127.0.0.1:8000/api/v1/search/stats` | Real-time documents, domains, and storage telemetry |

---

## 🛠️ Manual Step-by-Step Setup (Alternative)

If you prefer to configure components manually:

### 1. Python Virtual Environment & Backend
```bash
# 1. Create virtual environment
python -m venv .venv

# 2. Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Install requirements
pip install --upgrade pip
pip install -r backend/requirements.txt

# 4. Copy configuration
cp .env.example .env
cp .env.example backend/.env

# 5. Start Backend server
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Frontend (React 19 + Vite)
In a new terminal window:
```bash
cd frontend
npm install
npm run dev
```

---

## 🔍 How Search & On-Demand Indexing Works

OM Search features **On-Demand Search-Driven Indexing**:
1. When you search for any query (e.g., `mumbai metro aqua line`, `chandrayaan 3`), the engine first queries the ultra-fast SQLite FTS5 index.
2. If relevant documents do not exist or are sparse (< 3 results), the engine **dynamically crawls and indexes authoritative web pages in real-time** (Wikipedia API, DuckDuckGo web discovery).
3. The results are passed through a **Strict Keyword Relevance Guard** requiring substantive query keywords to match (zero irrelevant/spam matches).
4. The searched keywords are automatically enqueued into `data/searched_keywords_queue.json` so the continuous Google Drive daemon also archives extensive pages for those exact topics.

---

## ☁️ Google Drive Continuous Cloud Archiving (Optional)

OM Search can durably archive millions of compressed micro-batches directly to Google Drive (Google One 5 TB storage pool) with **0 MB permanent local disk overhead**.

### Running the Ingestion Daemon Locally
```bash
# Windows
.venv\Scripts\python scripts\run_continuous_drive_ingestion.py --batch-size 5000 --crawl-threads 8

# Linux/macOS
.venv/bin/python scripts/run_continuous_drive_ingestion.py --batch-size 5000 --crawl-threads 8
```

### Running 24/7 in GitHub Actions (Cloud Indexer)
1. Go to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Add these Repository Secrets:
   - `GOOGLE_REFRESH_TOKEN`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_DRIVE_ROOT_FOLDER_ID` *(optional, defaults to `1HSmEYSlw57hQkW4FBLft_-11e6sR72Qk`)*
3. Trigger the workflow manually from the **Actions** tab -> **Cloud Continuous Google Drive Indexer**.

---

## ❓ Troubleshooting

### `Python is not recognized as an internal or external command`
- Ensure Python 3.10+ is installed from [python.org](https://www.python.org/).
- Ensure **"Add Python to PATH"** was checked during installation.

### `Node.js or npm is not recognized`
- Install Node.js LTS (18+) from [nodejs.org](https://nodejs.org/).
- Reopen your terminal after installation.

### Port 8000 or 5173 is already in use
- Change the port in `backend/.env` (`PORT=8001`) or in `frontend/vite.config.ts`.
