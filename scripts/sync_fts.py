import sqlite3

conn = sqlite3.connect("backend/om_search_fts.db")
cur = conn.cursor()

cur.execute("DELETE FROM documents_fts;")
cur.execute("""
INSERT INTO documents_fts (rowid, title, snippet, content)
SELECT rowid, title, snippet, content FROM documents;
""")
conn.commit()

cur.execute("SELECT COUNT(*) FROM documents_fts;")
fts_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM documents;")
doc_count = cur.fetchone()[0]

print(f"Index synchronized: {doc_count} documents in base table, {fts_count} documents in FTS5.")
conn.close()
