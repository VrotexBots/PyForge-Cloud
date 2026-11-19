import ipaddress
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque
from html.parser import HTMLParser
from datetime import datetime, timezone

from api_provider.vaultnex_search_engine import engine

ENGINE_NAME = "PyForge External Web Crawler"
VERSION = "1.0.0"
USER_AGENT = "VaultNexGenesisResearch/1.0 (+public-web-research)"
REQUEST_TIMEOUT = 12
MAX_BYTES = 750_000
MAX_TEXT = 12_000
MAX_PAGES = 24
MAX_DEPTH = 1
MAX_LINKS_PER_PAGE = 80
MIN_TEXT_LENGTH = 100
DEFAULT_DELAY = 2.0

# Initial seeds are the existing official sources already configured
# in VaultNex. A seed is a discovery source, not proof that its tasks
# permit automated execution.
SEED_SOURCES = [
    {"url": "https://www.clickworker.com/clickworker-job/", "name": "Clickworker"},
    {"url": "https://www.triaba.com/za/join", "name": "Triaba South Africa"},
    {"url": "https://participant-help.prolific.com/en/articles/445007-who-can-participate-in-studies-on-prolific", "name": "Prolific"},
    {"url": "https://www.userinterviews.com/our-research-panel", "name": "User Interviews"},
    {"url": "https://www.upwork.com/resources/upwork-for-beginners", "name": "Upwork"},
    {"url": "https://players.playtestcloud.com/article/138-can-i-become-a-playtester-if-im-not-from-the-usa-uk-or-canada", "name": "PlaytestCloud"},
    {"url": "https://www.oneforma.com/projects/", "name": "OneForma"},
    {"url": "https://toloka.ai/get-started", "name": "Toloka"},
    {"url": "https://newsroom.tiktok.com/unlocking-new-ways-for-south-african-creators-to-earn-through-tiktok-one?lang=en-ZA", "name": "TikTok One"},
    {"url": "https://www.awin.com/gb/faqs", "name": "Awin"},
]

def _now():
    return datetime.now(timezone.utc).isoformat()

def _host(url):
    return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")

def _safe_public_host(host):
    try:
        if not host or host in ("localhost",):
            return False
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses:
            return False
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                return False
        return True
    except (ValueError, OSError, socket.gaierror):
        return False

def _normalise_url(url):
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.lower() != "https":
            return None
        if not parts.hostname or parts.username or parts.password:
            return None
        if parts.port not in (None, 443):
            return None
        if not _safe_public_host(parts.hostname.lower()):
            return None
        path = parts.path or "/"
        return urllib.parse.urlunsplit((
            "https", parts.netloc.lower(), path, parts.query, ""
        ))
    except (ValueError, TypeError):
        return None

class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_host):
        super().__init__()
        self.allowed_host = allowed_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        normal = _normalise_url(newurl)
        if not normal or _host(normal) != self.allowed_host:
            raise urllib.error.HTTPError(
                newurl, code, "Crawler redirect outside approved seed host",
                headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, normal)

class _PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer",
            "header", "aside", "form", "iframe", "button"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.text = []
        self.links = []
        self.skip_depth = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag in self.SKIP:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "a" and attrs.get("href") and len(self.links) < MAX_LINKS_PER_PAGE:
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self.in_title:
            self.title.append(value)
        if not self.skip_depth:
            self.text.append(value)

def _request(url, host):
    normal = _normalise_url(url)
    if not normal or _host(normal) != host:
        raise ValueError("URL failed HTTPS, public-host, or same-host validation.")
    opener = urllib.request.build_opener(_SameHostRedirect(host))
    request = urllib.request.Request(
        normal,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
        final_url = _normalise_url(response.geturl())
        if not final_url or _host(final_url) != host:
            raise ValueError("Final URL failed same-host validation.")
        if response.headers.get_content_type() not in (
            "text/html", "application/xhtml+xml"
        ):
            raise ValueError("URL did not return an HTML page.")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("Page exceeded crawler download limit.")
        charset = response.headers.get_content_charset() or "utf-8"
        html = body.decode(charset, errors="replace")
        return final_url, html

def _robots_policy(host):
    robots_url = "https://" + host + "/robots.txt"
    normal = _normalise_url(robots_url)
    if not normal:
        return None, DEFAULT_DELAY, "robots_url_rejected"

    opener = urllib.request.build_opener(_SameHostRedirect(host))
    request = urllib.request.Request(
        normal, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"}
    )
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(normal)

    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            if _host(response.geturl()) != host:
                return None, DEFAULT_DELAY, "robots_redirect_rejected"
            data = response.read(100_000).decode("utf-8", errors="replace")
            parser.parse(data.splitlines())
    except urllib.error.HTTPError as exc:
        # A missing robots.txt is treated as no published restrictions.
        # Authentication/forbidden/server errors fail closed.
        if exc.code == 404:
            parser.parse([])
        else:
            return None, DEFAULT_DELAY, "robots_unavailable_fail_closed"
    except Exception:
        return None, DEFAULT_DELAY, "robots_unavailable_fail_closed"

    delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*")
    try:
        delay = max(DEFAULT_DELAY, min(float(delay or DEFAULT_DELAY), 30.0))
    except (TypeError, ValueError):
        delay = DEFAULT_DELAY
    return parser, delay, "robots_checked"

def _extract(url, html):
    parser = _PageParser()
    parser.feed(html)
    title = " ".join(parser.title).strip()[:300]
    text = " ".join(parser.text)
    text = " ".join(text.split())[:MAX_TEXT]
    links = []
    for href in parser.links:
        absolute = urllib.parse.urljoin(url, href)
        normal = _normalise_url(absolute)
        if normal and _host(normal) == _host(url):
            links.append(normal)
    return title, text, list(dict.fromkeys(links))

class ExternalWebEngine:
    def __init__(self):
        self.last_report = {
            "status": "idle", "pages_fetched": 0, "pages_indexed": 0,
            "pages_skipped": 0, "errors": [], "updated_at": None,
        }
        self._host_last_request = {}

    def _respect_delay(self, host, delay):
        previous = self._host_last_request.get(host, 0.0)
        wait = delay - (time.monotonic() - previous)
        if wait > 0:
            time.sleep(wait)
        self._host_last_request[host] = time.monotonic()

    def crawl(self, max_pages=MAX_PAGES):
        try:
            max_pages = max(1, min(int(max_pages), MAX_PAGES))
        except (TypeError, ValueError):
            max_pages = MAX_PAGES

        report = {
            "status": "running", "started_at": _now(),
            "pages_fetched": 0, "pages_indexed": 0,
            "pages_skipped": 0, "robots_blocked": 0,
            "errors": [], "seed_count": len(SEED_SOURCES),
            "max_pages": max_pages,
        }
        visited = set()
        queue = deque()

        for seed in SEED_SOURCES:
            normal = _normalise_url(seed["url"])
            if normal:
                queue.append((normal, seed["name"], 0))
            else:
                report["pages_skipped"] += 1

        robots_cache = {}

        while queue and report["pages_fetched"] < max_pages:
            url, source_name, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            host = _host(url)

            if host not in robots_cache:
                robots_cache[host] = _robots_policy(host)
            robots, delay, robots_status = robots_cache[host]

            if robots is None:
                report["pages_skipped"] += 1
                report["errors"].append({
                    "url": url, "reason": robots_status
                })
                continue
            if not robots.can_fetch(USER_AGENT, url):
                report["robots_blocked"] += 1
                report["pages_skipped"] += 1
                continue

            try:
                self._respect_delay(host, delay)
                final_url, html = _request(url, host)
                report["pages_fetched"] += 1
                title, text, links = _extract(final_url, html)

                if len(text) < MIN_TEXT_LENGTH or not title:
                    report["pages_skipped"] += 1
                else:
                    indexed = engine.index_document({
                        "url": final_url,
                        "title": title,
                        "description": text[:2000],
                        "content": text,
                        "source_name": source_name,
                        "country": "South Africa",
                    })
                    if indexed:
                        report["pages_indexed"] += 1

                if depth < MAX_DEPTH:
                    for link in links:
                        if link not in visited:
                            queue.append((link, source_name, depth + 1))

            except Exception as exc:
                report["pages_skipped"] += 1
                report["errors"].append({
                    "url": url, "reason": str(exc)[:240]
                })

        report["status"] = (
            "completed_with_errors" if report["errors"] else "completed"
        )
        report["completed_at"] = _now()
        report["index_health"] = engine.health()
        self.last_report = report
        return dict(report)

    def search(self, query, limit=10):
        results = engine.search(query, limit)
        return {
            "query": query,
            "search_scope": "external_crawled_index",
            "grounded": bool(results),
            "results": results,
            "source_count": len(results),
            "crawl_status": self.last_report.get("status", "not_run"),
            "index_health": engine.health(),
        }

    def health(self):
        return {
            "engine": ENGINE_NAME,
            "version": VERSION,
            "status": "ready",
            "index": engine.health(),
            "last_crawl": dict(self.last_report),
            "seed_sources": len(SEED_SOURCES),
        }

engine_external = ExternalWebEngine()
