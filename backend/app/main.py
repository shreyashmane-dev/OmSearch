import sys
from pathlib import Path
import logging
from contextlib import asynccontextmanager

# Ensure project root is in sys.path for crawler module
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, Response

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.v1.router import router as api_v1_router
from app.api.v1.crawl_router import router as crawl_router
from app.api.v1.ingestion_router import router as ingestion_router
from app.api.v1.storage_router import router as storage_router
from app.repositories.opensearch_repo import get_opensearch_repo
from app.repositories.database import get_db_manager

settings = get_settings()
setup_logging(level=settings.LOG_LEVEL)
logger = logging.getLogger("om_search")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing %s v%s...", settings.APP_NAME, settings.APP_VERSION)
    # Ensure database tables
    try:
        get_db_manager()
        logger.info("Database schema verified.")
    except Exception as e:
        logger.warning("Database initialization warning: %s", e)

    # Check/create OpenSearch index if connected
    try:
        os_repo = get_opensearch_repo()
        if os_repo.ping():
            os_repo.ensure_index()
            logger.info("OpenSearch index verified.")
        else:
            logger.info("OpenSearch is not currently reachable; starting in resilient mode.")
            os_repo._ensure_fallback_store()
            os_repo._rebuild_inverted_index()
            logger.info("In-memory inverted index pre-warmed (%d documents).", len(os_repo._fallback_store))
    except Exception as e:
        logger.warning("OpenSearch initialization warning: %s", e)

    # Ensure rich multi-domain index with 13,500+ live crawled real-web pages
    try:
        from app.ingestion.starter_corpus import ensure_starter_index, run_daily_render_crawler
        ensure_starter_index(min_docs=15000)
        import asyncio
        asyncio.create_task(run_daily_render_crawler(daily_target=1000))
        logger.info("Starter corpus ensured & daily incremental crawler scheduled.")
    except Exception as e:
        logger.warning("Starter index initialization notice: %s", e)

    # Pre-warm SearchService pipeline for instant sub-5ms first search
    try:
        from app.services.search_service import SearchService
        _search_svc = SearchService()
        _search_svc.search("quantum", page=1, size=1)
        logger.info("Search pipeline pre-warmed and ready.")
    except Exception as e:
        logger.debug("Search pipeline warmup notice: %s", e)

    yield

    logger.info("Shutting down %s...", settings.APP_NAME)


app = FastAPI(
    title="OM Search Engine API",
    description="High-performance, independent web search engine backend foundation.",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_request_size_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.MAX_REQUEST_SIZE_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": "Request payload exceeds allowed limit (1MB)."},
        )
    return await call_next(request)


# Include API v1 routes
app.include_router(api_v1_router)
app.include_router(crawl_router)
app.include_router(ingestion_router)
app.include_router(storage_router)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/google6ba000893a0dc8c1.html", response_class=HTMLResponse, include_in_schema=False)
async def google_site_verification():
    return HTMLResponse("google-site-verification: google6ba000893a0dc8c1.html")


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt():
    content = "User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: https://omsearch.web.app/sitemap.xml\n"
    return PlainTextResponse(content)


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://omsearch.web.app/</loc>
    <lastmod>2026-10-28</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://omsearch.web.app/?q=Quantum+mechanics</loc>
    <lastmod>2026-10-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://omsearch.web.app/?q=Artificial+intelligence</loc>
    <lastmod>2026-10-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://omsearch.web.app/?q=Python+asynchronous+programming</loc>
    <lastmod>2026-10-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://omsearch.web.app/?q=Space+exploration</loc>
    <lastmod>2026-10-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://omsearch.web.app/?q=Solar+System</loc>
    <lastmod>2026-10-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
"""
    return Response(content=xml_content, media_type="application/xml")


@app.get("/", tags=["System"])
async def root():
    return {
        "engine": "OM Search",
        "version": settings.APP_VERSION,
        "status": "online",
        "documentation": "/docs",
        "health": "/api/v1/health",
        "search": "/api/v1/search?q={query}",
    }

