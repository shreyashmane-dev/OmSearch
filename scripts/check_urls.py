import urllib.request
import json

try:
    with urllib.request.urlopen("https://omsearch.onrender.com/api/v1/search?q=react", timeout=10) as r:
        data = json.loads(r.read().decode())
        results = data.get("results", [])
        print(f"Results count: {len(results)}")
        for item in results[:3]:
            print("Title:", item.get("title"))
            print("URL  :", item.get("url"))
except Exception as e:
    print("Error:", e)
