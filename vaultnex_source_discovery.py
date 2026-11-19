from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

from api_provider.vaultnex_crawler import crawl_page, safe_url
from api_provider.vaultnex_search_engine import engine


def discover_source(seed_url, source_name="", country="ZA",
                    max_pages=5, search_engine=None):

    if not safe_url(seed_url):
        return {"success": False, "error": "Unsafe or invalid HTTPS seed"}

    target = search_engine or engine
    seed = urldefrag(seed_url)[0]
    allowed_host = urlparse(seed).hostname.lower()

    max_pages = max(1, min(int(max_pages), 10))
    queue = deque([seed])
    visited = set()
    indexed = []
    errors = []

    while queue and len(visited) < max_pages:
        url = queue.popleft()

        if url in visited:
            continue

        visited.add(url)
        page = crawl_page(url)

        if not page.get("success"):
            errors.append({
                "url": url,
                "error": page.get("error", "Crawl failed")
            })
            continue

        document = {
            "url": page["url"],
            "title": page["title"],
            "description": page["description"],
            "content": page["content"],
            "source_name": source_name,
            "country": country
        }

        try:
            was_indexed = target.index_document(document)

            if was_indexed:
                indexed.append({
                    "url": page["url"],
                    "title": page["title"]
                })
        except Exception as error:
            errors.append({"url": url, "error": str(error)[:200]})
            continue

        for link in page.get("links", []):
            candidate = urldefrag(urljoin(page["url"], link))[0]
            parsed = urlparse(candidate)

            if parsed.scheme != "https" or not parsed.hostname:
                continue

            if parsed.hostname.lower() != allowed_host:
                continue

            if candidate not in visited and candidate not in queue:
                queue.append(candidate)

    return {
        "success": True,
        "seed_url": seed,
        "domain": allowed_host,
        "pages_checked": len(visited),
        "pages_indexed": len(indexed),
        "errors": errors,
        "indexed_pages": indexed
    }
