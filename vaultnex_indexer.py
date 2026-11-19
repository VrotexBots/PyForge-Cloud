from api_provider.vaultnex_crawler import crawl_page
from api_provider.vaultnex_search_engine import engine


def crawl_and_index(url, source_name="", country="", search_engine=None):
    target_engine = search_engine or engine
    page = crawl_page(url)

    if not page.get("success"):
        return {
            "success": False,
            "indexed": False,
            "error": page.get("error", "Crawling failed")
        }

    document = {
        "url": page["url"],
        "title": page["title"],
        "description": page["description"],
        "content": page["content"],
        "source_name": source_name,
        "country": country
    }

    indexed = target_engine.index_document(document)

    return {
        "success": True,
        "indexed": indexed,
        "title": page["title"],
        "url": page["url"],
        "content_length": len(page["content"]),
        "links_found": len(page["links"])
    }
