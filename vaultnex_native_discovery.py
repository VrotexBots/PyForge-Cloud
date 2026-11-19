import json
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

from api_provider.vaultnex_crawler import crawl_page, safe_url
from api_provider.vaultnex_source_registry import registry


CANDIDATE_PATH = Path(__file__).with_name(
    "vaultnex_candidate_registry.json"
)

MAX_LINKS_PER_SOURCE = 100
MAX_STORED_URLS_PER_CANDIDATE = 5


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class NativeDiscoveryError(Exception):
    pass


class NativeDiscoveryEngine:

    def __init__(self, candidate_path=CANDIDATE_PATH):
        self.path = Path(candidate_path)

    def _load_candidates(self):
        if not self.path.exists():
            return {
                "registry": "VaultNex Discovered Candidates",
                "version": "1.0.0",
                "updated_at": utc_now(),
                "candidates": []
            }

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise NativeDiscoveryError(
                f"Could not read candidate registry: {error}"
            )

        if not isinstance(data, dict) or not isinstance(
            data.get("candidates"), list
        ):
            raise NativeDiscoveryError(
                "Candidate registry has an invalid structure."
            )

        return data

    def _save_candidates(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".vaultnex-candidates-",
                suffix=".tmp",
                delete=False
            ) as file:
                temporary_path = file.name
                json.dump(data, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_path, self.path)

        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _add_candidate(self, data, url, source):
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()

        if not domain:
            return "rejected"

        candidates = data["candidates"]

        existing = next(
            (
                item for item in candidates
                if item.get("domain") == domain
            ),
            None
        )

        if existing:
            existing["last_seen_at"] = utc_now()
            existing["occurrences"] = (
                int(existing.get("occurrences", 1)) + 1
            )

            if source["id"] not in existing.get("source_ids", []):
                existing.setdefault("source_ids", []).append(
                    source["id"]
                )

            if url not in existing.get("observed_urls", []):
                urls = existing.setdefault("observed_urls", [])
                urls.append(url)
                del urls[:-MAX_STORED_URLS_PER_CANDIDATE]

            return "duplicate"

        candidates.append({
            "id": domain,
            "domain": domain,
            "url": url,
            "observed_urls": [url],
            "source_ids": [source["id"]],
            "source_names": [source["name"]],
            "status": "discovered_unverified",
            "category": None,
            "eligibility": "unknown",
            "payment_verified": False,
            "occurrences": 1,
            "first_seen_at": utc_now(),
            "last_seen_at": utc_now()
        })

        return "new"

    def discover_source(self, source):
        page = crawl_page(source["url"])

        if not page.get("success"):
            registry.record_check(
                source["id"],
                False,
                error=page.get("error", "Crawl failed")
            )

            return {
                "success": False,
                "source_id": source["id"],
                "error": page.get("error", "Crawl failed")
            }

        data = self._load_candidates()
        source_host = (urlparse(page["url"]).hostname or "").lower()

        new_count = 0
        duplicate_count = 0
        rejected_count = 0
        checked_count = 0

        links = page.get("links", [])[:MAX_LINKS_PER_SOURCE]

        for link in links:
            candidate_url = urldefrag(
                urljoin(page["url"], link)
            )[0]

            parsed = urlparse(candidate_url)

            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                rejected_count += 1
                continue

            domain = parsed.hostname.lower()

            if domain == source_host:
                continue

            checked_count += 1

            if not safe_url(candidate_url):
                rejected_count += 1
                continue

            result = self._add_candidate(
                data,
                candidate_url,
                source
            )

            if result == "new":
                new_count += 1
            elif result == "duplicate":
                duplicate_count += 1
            else:
                rejected_count += 1

        data["updated_at"] = utc_now()
        self._save_candidates(data)

        registry.record_check(
            source["id"],
            True,
            pages_checked=1,
            links_found=checked_count
        )

        return {
            "success": True,
            "source_id": source["id"],
            "source_name": source["name"],
            "new_candidates": new_count,
            "duplicates": duplicate_count,
            "rejected": rejected_count,
            "external_links_checked": checked_count
        }

    def run_discovery(self, country="ZA"):
        sources = registry.get_enabled_sources(country)

        report = {
            "success": True,
            "country": country,
            "sources_checked": 0,
            "sources_failed": 0,
            "new_candidates": 0,
            "duplicates": 0,
            "rejected": 0,
            "source_results": []
        }

        for source in sources:
            try:
                result = self.discover_source(source)
            except Exception as error:
                result = {
                    "success": False,
                    "source_id": source["id"],
                    "error": str(error)[:250]
                }

            report["source_results"].append(result)

            if result["success"]:
                report["sources_checked"] += 1
                report["new_candidates"] += result["new_candidates"]
                report["duplicates"] += result["duplicates"]
                report["rejected"] += result["rejected"]
            else:
                report["sources_failed"] += 1

        report["candidate_registry"] = str(self.path)
        report["total_candidates"] = len(
            self._load_candidates()["candidates"]
        )

        return report

    def get_candidates(self):
        data = self._load_candidates()
        return data["candidates"]


engine = NativeDiscoveryEngine()
