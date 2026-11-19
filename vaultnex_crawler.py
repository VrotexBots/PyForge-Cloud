import ipaddress
import socket
import http.client
import urllib.request
import urllib.error
import urllib.robotparser

from urllib.parse import urlparse, urljoin
from html.parser import HTMLParser

USER_AGENT = "VaultNexResearchBot/1.0"
TIMEOUT = 12
MAX_BYTES = 1_000_000


def resolve_public_addresses(host, port=443):
    addresses = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )

    if not addresses:
        raise OSError("Hostname did not resolve")

    public_addresses = []

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0].split("%")[0])

        if not ip.is_global:
            raise OSError("Hostname resolves to a non-public IP address")

        numeric_ip = address[4][0]

        if numeric_ip not in public_addresses:
            public_addresses.append(numeric_ip)

    return public_addresses


def safe_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme != "https" or not parsed.hostname:
            return False

        if parsed.username or parsed.password:
            return False

        if parsed.hostname.lower() == "localhost":
            return False

        resolve_public_addresses(parsed.hostname, parsed.port or 443)
        return True

    except Exception:
        return False


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if self._tunnel_host:
            raise OSError(
                "Proxy tunnels are not supported by the DNS-pinned crawler"
            )

        addresses = resolve_public_addresses(
            self.host, self.port or 443
        )

        last_error = None

        for numeric_ip in addresses:
            raw_socket = None

            try:
                raw_socket = socket.create_connection(
                    (numeric_ip, self.port or 443),
                    timeout=self.timeout,
                    source_address=self.source_address
                )

                self.sock = self._context.wrap_socket(
                    raw_socket,
                    server_hostname=self.host
                )
                return

            except Exception as error:
                last_error = error

                if raw_socket is not None:
                    raw_socket.close()

        raise OSError(
            "Could not connect to a validated public IP address"
        ) from last_error


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(
            PinnedHTTPSConnection,
            request,
            context=self._context
        )


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        destination = urljoin(request.full_url, new_url)

        if not safe_url(destination):
            raise urllib.error.HTTPError(
                destination, code, "Unsafe redirect destination",
                headers, None
            )

        return super().redirect_request(
            request, response, code, message, headers, destination
        )


OPENER = urllib.request.build_opener(
    PinnedHTTPSHandler(),
    SafeRedirectHandler()
)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = []
        self.description = ""
        self.text = []
        self.links = []
        self.in_title = False
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "title":
            self.in_title = True

        if tag in ("script", "style", "noscript", "svg"):
            self.skip_depth += 1

        if tag == "meta":
            name = attrs.get("name", "").lower()
            if name == "description":
                self.description = attrs.get("content", "")

        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

        if tag in ("script", "style", "noscript", "svg"):
            self.skip_depth = max(0, self.skip_depth - 1)

    def handle_data(self, data):
        value = " ".join(data.split())

        if not value or self.skip_depth:
            return

        if self.in_title:
            self.title.append(value)
        else:
            self.text.append(value)


def robots_allowed(url):
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if not safe_url(robots_url):
        return False

    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)

    try:
        request = urllib.request.Request(
            robots_url,
            headers={"User-Agent": USER_AGENT}
        )

        with OPENER.open(request, timeout=TIMEOUT) as response:
            content = response.read(100_000).decode(
                "utf-8", errors="replace"
            )

        parser.parse(content.splitlines())
        return parser.can_fetch(USER_AGENT, url)

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return True
        return False

    except Exception:
        return False


def crawl_page(url):
    if not safe_url(url):
        return {"success": False, "error": "Unsafe or invalid HTTPS URL"}

    if not robots_allowed(url):
        return {"success": False, "error": "Robots policy disallows crawling or could not be checked"}

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml"
        }
    )

    try:
        with OPENER.open(request, timeout=TIMEOUT) as response:
            content_type = response.headers.get_content_type()

            if content_type not in ("text/html", "application/xhtml+xml"):
                return {"success": False, "error": "Unsupported page content type"}

            data = response.read(MAX_BYTES + 1)

            if len(data) > MAX_BYTES:
                return {"success": False, "error": "Page exceeds size limit"}

            final_url = response.geturl()

            if not safe_url(final_url):
                return {"success": False, "error": "Unsafe final URL"}

            charset = response.headers.get_content_charset() or "utf-8"

        parser = PageParser()
        parser.feed(data.decode(charset, errors="replace"))

        return {
            "success": True,
            "url": final_url,
            "title": " ".join(parser.title).strip()[:300],
            "description": parser.description[:1000],
            "content": " ".join(parser.text)[:20000],
            "links": parser.links[:100]
        }

    except Exception as error:
        return {"success": False, "error": str(error)[:300]}
