import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ingestion.pipeline import IngestionPipeline


@pytest.fixture(scope="module")
def client():
    # Setup test corpus
    pipeline = IngestionPipeline()
    sample_doc = {
        "url": "https://example.com/test-article",
        "title": "Quantum Computing Fundamentals",
        "content": "Quantum computers use qubits to perform calculations at unprecedented speeds compared to classical computers.",
        "snippet": "Quantum computers use qubits to perform calculations at unprecedented speeds.",
        "language": "en",
    }
    pipeline.process_raw_document(sample_doc)

    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "services" in data
    assert "opensearch" in data["services"]
    assert "database" in data["services"]


def test_search_endpoint_success(client):
    response = client.get("/api/v1/search?q=qubits")
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "qubits"
    assert data["total"] >= 1
    assert len(data["results"]) >= 1

    first = data["results"][0]
    assert "id" in first
    assert "url" in first
    assert "title" in first
    assert "snippet" in first
    assert "domain" in first
    assert first["domain"] == "example.com" or bool(first["domain"])


def test_search_empty_index_returns_no_results(client):
    # Non-existent query must return 0 hits, never fabricated results
    response = client.get("/api/v1/search?q=xyznonexistentterm12345")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["results"] == []


def test_search_empty_query_rejected(client):
    response = client.get("/api/v1/search?q=   ")
    assert response.status_code == 422


def test_suggestions_endpoint(client):
    response = client.get("/api/v1/suggestions?q=quan")
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "quan"
    assert isinstance(data["suggestions"], list)


def test_search_stats_endpoint(client):
    response = client.get("/api/v1/search/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_documents" in data
    assert data["total_documents"] >= 1
    assert "top_domains" in data


def test_google_site_verification_endpoint(client):
    response = client.get("/google6ba000893a0dc8c1.html")
    assert response.status_code == 200
    assert "google-site-verification: google6ba000893a0dc8c1.html" in response.text


def test_robots_txt_endpoint(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "User-agent: *" in response.text
    assert "Sitemap: https://omsearch.web.app/sitemap.xml" in response.text


def test_sitemap_xml_endpoint(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers.get("content-type", "")
    assert "<urlset" in response.text
    assert "<loc>https://omsearch.web.app/</loc>" in response.text

