import sqlite3
import httpx

conn = sqlite3.connect("backend/om_search_fts.db")
cur = conn.cursor()

print("--- TESTING LIVE CRAWLED URLS ---")
cur.execute("SELECT url FROM documents WHERE document_type = 'live_web_page' LIMIT 20;")
urls = [r[0] for r in cur.fetchall()]

client = httpx.Client(timeout=8.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
for u in urls:
    try:
        r = client.get(u)
        print(f"[{r.status_code}] {u}")
    except Exception as e:
        print(f"[ERR] {u} ({type(e).__name__})")

print("\n--- TESTING FAKE SYNTHETIC URLS ---")
cur.execute("SELECT url FROM documents WHERE url LIKE '%/guide/%' OR url LIKE '%/articles/%' OR url LIKE '%/daily/%' LIMIT 10;")
fake_urls = [r[0] for r in cur.fetchall()]
for u in fake_urls:
    try:
        r = client.get(u)
        print(f"[{r.status_code}] {u}")
    except Exception as e:
        print(f"[ERR] {u} ({type(e).__name__})")
