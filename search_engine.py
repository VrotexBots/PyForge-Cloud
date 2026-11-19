"""
PyForge Native Search Intelligence API.

Uses PyForge's own indexed search infrastructure.
No Google Gemini or external AI provider is required.
"""

from api_provider.vaultnex_search_engine import (
    engine,
    ENGINE_NAME,
    VERSION,
)


MAX_QUERY_LENGTH = 1000
DEFAULT_MAX_SOURCES = 10


class SearchProviderError(Exception):
    """Safe, user-facing native search error."""


def search_pyforge(query, country="South Africa", max_sources=10, scope="local"):
    """
    Search PyForge's locally indexed research documents.

    Returns a response compatible with the existing VaultNex
    discovery client.
    """

    if not isinstance(query, str):
        raise SearchProviderError("Search query must be text.")

    query = " ".join(query.split()).strip()

    if len(query) < 2:
        raise SearchProviderError("Search query is too short.")

    if len(query) > MAX_QUERY_LENGTH:
        raise SearchProviderError("Search query is too long.")

    country = str(country or "South Africa").strip()[:80]
    scope = str(scope or "local").strip().lower()

    if scope not in ("local", "external"):
        raise SearchProviderError("Search scope must be 'local' or 'external'.")

    try:
        max_sources = int(max_sources)
    except (TypeError, ValueError):
        max_sources = DEFAULT_MAX_SOURCES

    max_sources = max(1, min(max_sources, 50))

    try:
        if scope == "external":
            from api_provider.external_web_engine import engine_external

            external_result = engine_external.search(query, max_sources)
            results = external_result.get("results", [])
            engine_status = engine.health()
            search_scope = "external_crawled_index"
        else:
            results = engine.search(query, max_sources)
            engine_status = engine.health()
            search_scope = "local_index_only"

    except Exception as error:
        raise SearchProviderError(
            f"PyForge native search failed: {str(error)[:200]}"
        ) from error

    sources = []

    for result in results:
        sources.append({
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "description": result.get("description", ""),
            "source_name": result.get("source_name", ""),
            "country": result.get("country", ""),
        })

    return {
        "provider": "PyForge Native Search",
        "service": ENGINE_NAME,
        "version": VERSION,
        "model": "native-retrieval-v1",
        "grounded": bool(sources),
        "query": query,
        "country": country,
        "answer": "",
        "results": sources,
        "sources": sources,
        "source_count": len(sources),
        "search_queries": [query],
        "search_scope": search_scope,
        "index_documents": engine_status.get(
            "index_documents", 0
        ),
        "external_ai_required": False,
    }


def health():
    """Return the native search engine health information."""
    return engine.health()
