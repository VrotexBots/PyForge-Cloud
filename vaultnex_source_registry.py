import json
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


REGISTRY_PATH = Path(__file__).with_name(
    "vaultnex_source_registry.json"
)


class SourceRegistryError(Exception):
    pass


class SourceRegistry:
    def __init__(self, path=REGISTRY_PATH):
        self.path = Path(path)

    def _read(self):
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            raise SourceRegistryError("Source registry file is missing.")
        except json.JSONDecodeError:
            raise SourceRegistryError("Source registry contains invalid JSON.")

        if not isinstance(data, dict):
            raise SourceRegistryError("Registry root must be an object.")

        sources = data.get("sources")

        if not isinstance(sources, list):
            raise SourceRegistryError("Registry sources must be a list.")

        seen_ids = set()

        for source in sources:
            if not isinstance(source, dict):
                raise SourceRegistryError("Invalid source entry.")

            source_id = source.get("id")
            url = source.get("url")
            parsed = urlparse(url or "")

            if not isinstance(source_id, str) or not source_id.strip():
                raise SourceRegistryError("Source ID is missing.")

            if source_id in seen_ids:
                raise SourceRegistryError("Duplicate source ID.")

            seen_ids.add(source_id)

            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise SourceRegistryError(
                    f"Source {source_id} has an invalid HTTPS URL."
                )

            if not isinstance(source.get("country_scope"), list):
                raise SourceRegistryError(
                    f"Source {source_id} has invalid country scope."
                )

            if not isinstance(source.get("discovery_enabled"), bool):
                raise SourceRegistryError(
                    f"Source {source_id} has invalid enabled setting."
                )

        return data

    def load(self):
        data = self._read()

        return {
            "success": True,
            "registry": data.get("registry"),
            "version": data.get("version"),
            "source_count": len(data["sources"]),
            "sources": data["sources"]
        }

    def get_enabled_sources(self, country="ZA"):
        data = self._read()
        country = str(country or "ZA").upper()

        return [
            source.copy()
            for source in data["sources"]
            if source["discovery_enabled"]
            and (
                "GLOBAL" in source["country_scope"]
                or country in source["country_scope"]
            )
        ]

    def record_check(
        self,
        source_id,
        success,
        pages_checked=0,
        links_found=0,
        error=""
    ):
        data = self._read()

        source = next(
            (
                item for item in data["sources"]
                if item["id"] == source_id
            ),
            None
        )

        if source is None:
            raise SourceRegistryError("Unknown source ID.")

        source["last_checked_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        source["last_check_success"] = bool(success)
        source["last_pages_checked"] = max(0, int(pages_checked))
        source["last_links_found"] = max(0, int(links_found))
        source["last_error"] = str(error or "")[:300]

        data["updated_at"] = datetime.now(
            timezone.utc
        ).date().isoformat()

        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".source-registry-",
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

        return {
            "success": True,
            "source_id": source_id,
            "check_recorded": True
        }


registry = SourceRegistry()
