import json
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from api_provider.vaultnex_native_discovery import engine as discovery_engine


PLATFORM_PATH = Path(__file__).with_name(
    "vaultnex_platform_registry.json"
)

COMMON_SECOND_LEVEL_SUFFIXES = {
    "co.za", "org.za", "net.za", "com.au", "net.au",
    "org.au", "co.uk", "org.uk", "ac.uk", "com.br",
    "com.cn", "com.sg", "co.nz", "co.in", "com.mx",
    "com.tr", "co.jp", "co.kr", "com.ar", "com.tw"
}

SERVICE_SUBDOMAINS = {
    "www", "help", "support", "account", "accounts",
    "participant-help", "helpdesk", "blog", "community",
    "members", "member", "app", "login", "auth",
    "docs", "documentation", "status", "api"
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_domain(host):
    host = str(host or "").lower().strip().rstrip(".")

    if not host:
        return ""

    labels = host.split(".")

    if len(labels) < 2:
        return host

    last_two = ".".join(labels[-2:])

    if last_two in COMMON_SECOND_LEVEL_SUFFIXES and len(labels) >= 3:
        root = ".".join(labels[-3:])
    else:
        root = last_two

    while "." in host:
        prefix = host[:-(len(root) + 1)]

        if not prefix:
            break

        first_label = prefix.split(".")[-1]

        if first_label not in SERVICE_SUBDOMAINS:
            break

        host = host[:-(len(first_label) + 1)]

    return root


def platform_id(domain):
    return domain.replace(".", "_").replace("-", "_")


class PlatformIdentityError(Exception):
    pass


class PlatformIdentityEngine:

    def __init__(self, path=PLATFORM_PATH):
        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            return {
                "registry": "VaultNex Platform Identity Registry",
                "version": "1.0.0",
                "updated_at": utc_now(),
                "platforms": []
            }

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise PlatformIdentityError(
                f"Could not read platform registry: {error}"
            )

        if not isinstance(data, dict) or not isinstance(
            data.get("platforms"), list
        ):
            raise PlatformIdentityError(
                "Platform registry has an invalid structure."
            )

        return data

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".vaultnex-platforms-",
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

    def build_registry(self):
        candidates = discovery_engine.get_candidates()
        data = self._load()

        existing = {
            item.get("domain"): item
            for item in data["platforms"]
            if isinstance(item, dict) and item.get("domain")
        }

        grouped = {}

        for candidate in candidates:
            url = candidate.get("url", "")
            host = urlparse(url).hostname or candidate.get("domain", "")
            root = normalize_domain(host)

            if not root:
                continue

            platform = grouped.setdefault(root, {
                "id": platform_id(root),
                "domain": root,
                "display_name": root,
                "candidate_ids": [],
                "observed_hosts": [],
                "observed_urls": [],
                "source_ids": [],
                "status": "identity_grouped_unverified",
                "category": None,
                "south_africa_eligibility": "unknown",
                "payment_verified": False,
                "first_seen_at": utc_now(),
                "last_seen_at": utc_now()
            })

            candidate_id = candidate.get("id")

            if candidate_id and candidate_id not in platform["candidate_ids"]:
                platform["candidate_ids"].append(candidate_id)

            if host and host not in platform["observed_hosts"]:
                platform["observed_hosts"].append(host)

            if url and url not in platform["observed_urls"]:
                platform["observed_urls"].append(url)

            for source_id in candidate.get("source_ids", []):
                if source_id not in platform["source_ids"]:
                    platform["source_ids"].append(source_id)

        for domain, platform in grouped.items():
            previous = existing.get(domain)

            if previous:
                platform["first_seen_at"] = previous.get(
                    "first_seen_at", platform["first_seen_at"]
                )
                platform["last_seen_at"] = utc_now()

                # Preserve any future human verification and review data.
                for key in (
                    "status",
                    "category",
                    "south_africa_eligibility",
                    "payment_verified",
                    "verification_evidence",
                    "review_notes"
                ):
                    if key in previous:
                        platform[key] = previous[key]

                # Preserve every additional field, including future
                # investigation, evidence, and audit information.
                for key, value in previous.items():
                    if key not in platform:
                        platform[key] = value

        # Retain identities temporarily absent from current discovery.
        for domain, previous in existing.items():
            if domain not in grouped:
                grouped[domain] = previous

        data["platforms"] = sorted(
            grouped.values(),
            key=lambda item: item["domain"]
        )
        data["updated_at"] = utc_now()
        self._save(data)

        return {
            "success": True,
            "candidates_processed": len(candidates),
            "unique_platform_identities": len(grouped),
            "previous_identities": len(existing),
            "registry_path": str(self.path)
        }

    def sync_investigation(self, report):
        if not isinstance(report, dict):
            raise PlatformIdentityError("Investigation report must be a dictionary.")

        domain = str(report.get("domain") or "").strip().lower()
        identifier = str(report.get("platform_id") or "").strip()
        assessment = report.get("verification_assessment")

        if not domain or not identifier:
            raise PlatformIdentityError("Investigation report is missing its platform identity.")

        if not isinstance(assessment, dict):
            raise PlatformIdentityError("Investigation report has no valid verification assessment.")

        data = self._load()
        matches = [
            platform for platform in data["platforms"]
            if isinstance(platform, dict)
            and platform.get("domain") == domain
            and platform.get("id") == identifier
        ]

        if len(matches) != 1:
            raise PlatformIdentityError(
                f"Expected exactly one matching platform identity; found {len(matches)}."
            )

        platform = matches[0]
        eligibility = assessment.get("south_africa_eligibility", {})
        payment = assessment.get("payment", {})

        if not isinstance(eligibility, dict):
            eligibility = {}
        if not isinstance(payment, dict):
            payment = {}

        evidence_summary = []
        for page in report.get("evidence", []):
            if not isinstance(page, dict):
                continue

            evidence_summary.append({
                key: page.get(key)
                for key in (
                    "source_url",
                    "observed_at",
                    "evidence_status",
                    "category_signals",
                    "south_africa_mentions",
                    "eligibility_claims",
                    "payment_mentions",
                    "payment_method_claims",
                    "payout_claims",
                    "reward_mentions",
                )
                if key in page
            })

        summary = {
            "investigation_id": report.get("investigation_id"),
            "investigated_at": report.get("investigated_at"),
            "status": report.get("status"),
            "pages_checked": report.get("pages_checked", 0),
            "category_status": report.get("category_status"),
            "suggested_categories": report.get("suggested_categories", []),
            "south_africa_eligibility": {
                "status": eligibility.get("status", "unknown"),
                "verification_status": eligibility.get("verification_status", "not_verified"),
                "automatic_approval": False,
            },
            "payment": {
                "status": payment.get("status", "unknown"),
                "verification_status": payment.get("verification_status", "not_verified"),
                "payment_verified": False,
                "automatic_approval": False,
            },
            "evidence_status": report.get("evidence_status", "unverified_observations"),
        }

        platform["latest_investigation"] = {
            **summary,
            "verification_assessment": assessment,
            "evidence": evidence_summary,
        }

        history = platform.setdefault("investigation_history", [])
        if not isinstance(history, list):
            raise PlatformIdentityError("Platform investigation history has an invalid structure.")

        investigation_id = summary.get("investigation_id")
        if investigation_id and not any(
            isinstance(item, dict) and item.get("investigation_id") == investigation_id
            for item in history
        ):
            history.append(summary)

        platform["investigation_history"] = history[-20:]
        platform["last_investigated_at"] = summary.get("investigated_at")
        data["updated_at"] = utc_now()
        self._save(data)

        return {
            "success": True,
            "platform_id": identifier,
            "domain": domain,
            "investigation_id": investigation_id,
            "history_count": len(platform["investigation_history"]),
            "registry_path": str(self.path),
        }

    def get_platforms(self):
        return self._load()["platforms"]


identity_engine = PlatformIdentityEngine()
