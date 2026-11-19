import json
import os
import re
import time
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from api_provider.vaultnex_crawler import crawl_page, safe_url
from api_provider.vaultnex_platform_identity import (
    PlatformIdentityError,
    identity_engine,
)
from api_provider.vaultnex_evidence_verification import (
    engine as evidence_verification_engine,
)


PLATFORM_PATH = Path(__file__).with_name(
    "vaultnex_platform_registry.json"
)

INVESTIGATION_PATH = Path(__file__).with_name(
    "vaultnex_investigation_registry.json"
)

MAX_PLATFORMS_PER_RUN = 3
MAX_PAGES_PER_PLATFORM = 3
MIN_REQUEST_INTERVAL_SECONDS = 2

APPROVED_CATEGORIES = {
    "survey",
    "market_research",
    "freelance",
    "game_testing",
    "rewards",
    "microtasks",
    "sponsorship",
    "affiliate",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class PlatformInvestigationError(Exception):
    """Raised when platform investigation cannot safely continue."""


class PlatformInvestigationEngine:

    def __init__(
        self,
        platform_path=PLATFORM_PATH,
        investigation_path=INVESTIGATION_PATH,
    ):
        self.platform_path = Path(platform_path)
        self.investigation_path = Path(investigation_path)

    def _load_platforms(self):
        if not self.platform_path.exists():
            raise PlatformInvestigationError(
                "Platform identity registry does not exist."
            )

        try:
            with self.platform_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise PlatformInvestigationError(
                f"Could not read platform registry: {error}"
            )

        if not isinstance(data, dict) or not isinstance(
            data.get("platforms"), list
        ):
            raise PlatformInvestigationError(
                "Platform identity registry has an invalid structure."
            )

        return data["platforms"]

    def get_platform(self, identifier):
        if not isinstance(identifier, str) or not identifier.strip():
            raise PlatformInvestigationError(
                "A platform ID or domain is required."
            )

        identifier = identifier.strip().lower()
        platforms = self._load_platforms()

        matches = [
            platform for platform in platforms
            if isinstance(platform, dict)
            and identifier in (
                str(platform.get("id", "")).lower(),
                str(platform.get("domain", "")).lower(),
            )
        ]

        if len(matches) != 1:
            raise PlatformInvestigationError(
                "Platform was not found or the identifier is ambiguous."
            )

        return matches[0]

    def _load_investigations(self):
        if not self.investigation_path.exists():
            return {
                "registry": "VaultNex Platform Investigation Registry",
                "version": "1.0.0",
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "investigations": [],
            }

        try:
            with self.investigation_path.open(
                "r", encoding="utf-8"
            ) as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise PlatformInvestigationError(
                f"Could not read investigation registry: {error}"
            )

        if not isinstance(data, dict) or not isinstance(
            data.get("investigations"), list
        ):
            raise PlatformInvestigationError(
                "Investigation registry has an invalid structure."
            )

        return data

    def _save_investigations(self, data):
        self.investigation_path.parent.mkdir(
            parents=True, exist_ok=True
        )
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.investigation_path.parent,
                prefix=".vaultnex-investigations-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = file.name
                json.dump(data, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_path, self.investigation_path)

        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def extract_evidence(self, page):
        if not isinstance(page, dict) or not page.get("success"):
            raise PlatformInvestigationError(
                "A successful crawler result is required."
            )

        content = page.get("content", "")
        source_url = page.get("url", "")

        if not isinstance(content, str) or not content.strip():
            raise PlatformInvestigationError(
                "The crawled page contains no usable text."
            )

        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+|\n+", content)
            if item.strip()
        ]

        category_terms = {
            "survey": ("survey", "questionnaire", "online surveys"),
            "market_research": (
                "market research", "focus group", "consumer research",
                "product testing"
            ),
            "freelance": (
                "freelance", "freelancer", "freelancing",
                "independent contractor"
            ),
            "game_testing": (
                "game testing", "game tester", "video game testing",
                "playtest", "play testing"
            ),
            "rewards": (
                "rewards", "reward points", "loyalty points",
                "redeem points"
            ),
            "microtasks": (
                "microtask", "micro task", "small tasks",
                "data labelling", "data labeling"
            ),
            "sponsorship": (
                "sponsorship", "sponsored content", "brand ambassador"
            ),
            "affiliate": (
                "affiliate", "referral commission", "affiliate commission",
                "partner commission"
            ),
        }

        payment_terms = (
            "paypal", "payoneer", "bank transfer", "wise",
            "skrill", "airtm", "gift card", "payout",
            "withdrawal", "payment method"
        )

        reward_terms = (
            "payment", "paid", "payout", "earn", "earning",
            "reward", "compensation", "per task", "hourly rate",
            "minimum withdrawal", "cash out"
        )

        country_terms = (
            "south africa", "south african", "republic of south africa"
        )

        eligibility_terms = (
            "eligible", "eligibility", "accept participants",
            "participants from", "participant requirements",
            "country requirements", "residents", "available in",
            "supported countries", "restricted countries",
            "not available", "cannot participate",
            "can participate", "open to participants",
            "country availability"
        )

        payment_method_terms = (
            "paypal", "payoneer", "bank transfer", "wise",
            "skrill", "airtm", "gift card", "direct deposit"
        )

        payout_terms = (
            "payout", "withdrawal", "withdraw", "minimum withdrawal",
            "cash out", "cashout", "payment threshold",
            "minimum payout", "payment schedule", "processing time"
        )

        def collect_matches(terms):
            matches = []
            seen = set()

            for sentence in sentences:
                lowered = sentence.lower()

                if any(term in lowered for term in terms):
                    excerpt = sentence[:500]

                    if excerpt not in seen:
                        seen.add(excerpt)
                        matches.append({
                            "source_url": source_url,
                            "excerpt": excerpt,
                            "verification_status": "unverified_observation",
                        })

                if len(matches) >= 10:
                    break

            return matches

        def collect_eligibility_claims():
            matches = []
            for sentence in sentences:
                lowered = sentence.lower()
                has_country = any(term in lowered for term in country_terms)
                has_eligibility_context = any(
                    term in lowered for term in eligibility_terms
                )
                if has_country and has_eligibility_context:
                    matches.append({
                        "source_url": source_url,
                        "excerpt": sentence[:500],
                        "evidence_type": "south_africa_eligibility_claim",
                        "verification_status": "unverified_observation"
                    })
                if len(matches) >= 10:
                    break
            return matches

        def collect_typed_matches(terms, evidence_type):
            matches = collect_matches(terms)
            for match in matches:
                match["evidence_type"] = evidence_type
            return matches

        category_signals = {}

        for category, terms in category_terms.items():
            matches = collect_matches(terms)

            if matches:
                category_signals[category] = matches

        return {
            "source_url": source_url,
            "observed_at": utc_now(),
            "category_signals": category_signals,
            "south_africa_mentions": collect_matches(country_terms),
            "eligibility_claims": collect_eligibility_claims(),
            "payment_mentions": collect_matches(payment_terms),
            "payment_method_claims": collect_typed_matches(
                payment_method_terms, "payment_method_claim"
            ),
            "payout_claims": collect_typed_matches(
                payout_terms, "payout_claim"
            ),
            "reward_mentions": collect_matches(reward_terms),
            "evidence_status": "unverified_observations",
        }




    def investigate_platform(self, identifier):
        platform = self.get_platform(identifier)
        urls = platform.get("observed_urls", [])

        if not isinstance(urls, list):
            raise PlatformInvestigationError(
                "Platform observed URLs have an invalid structure."
            )

        pages = []
        evidence = []

        for url in urls[:MAX_PAGES_PER_PLATFORM]:
            page_record = {
                "requested_url": url,
                "status": "not_attempted",
            }

            if not self.is_registered_url(platform, url):
                page_record["status"] = "rejected_domain"
                pages.append(page_record)
                continue

            if not safe_url(url):
                page_record["status"] = "rejected_unsafe_url"
                pages.append(page_record)
                continue

            if pages:
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS)

            try:
                result = crawl_page(url)
            except Exception as error:
                result = {
                    "success": False,
                    "error": str(error)[:300],
                }

            if not isinstance(result, dict) or not result.get("success"):
                page_record["status"] = "crawl_failed"
                page_record["error"] = (
                    str(result.get("error", "Invalid crawler response"))[:300]
                    if isinstance(result, dict)
                    else "Invalid crawler response"
                )
                pages.append(page_record)
                continue

            final_url = result.get("url")
            if not self.is_registered_url(platform, final_url):
                page_record["status"] = "rejected_unregistered_redirect"
                page_record["error"] = (
                    "Final URL is outside the registered platform domain"
                )
                page_record["source_url"] = (
                    str(final_url)[:1000] if final_url else ""
                )
                pages.append(page_record)
                continue

            try:
                extracted = self.extract_evidence(result)
            except PlatformInvestigationError as error:
                page_record["status"] = "extraction_failed"
                page_record["error"] = str(error)[:300]
                pages.append(page_record)
                continue

            page_record["status"] = "observed"
            page_record["title"] = result.get("title", "")[:300]
            page_record["source_url"] = extracted["source_url"]
            pages.append(page_record)
            evidence.append(extracted)

        suggested_categories = sorted({
            category
            for item in evidence
            for category in item["category_signals"]
            if category in APPROVED_CATEGORIES
        })

        successful_pages = sum(
            1 for page in pages if page["status"] == "observed"
        )

        try:
            source_authority_assessments = [
                evidence_verification_engine.assess_source_authority(
                    item.get("source_url", ""),
                    platform.get("domain", ""),
                )
                for item in evidence
            ]

            eligibility_assessment = (
                evidence_verification_engine.assess_south_africa_eligibility(
                    evidence,
                    registered_domain=platform.get("domain", "")
                )
            )

            payment_assessment = (
                evidence_verification_engine.assess_payment_evidence(
                    evidence
                )
            )

            freshness_assessment = (
                evidence_verification_engine.assess_evidence_freshness(
                    evidence
                )
            )

            verification_assessment = {
                "status": "assessed" if evidence else "insufficient_evidence",
                "verification_status": "not_verified",
                "automatic_approval": False,
                "source_authority": source_authority_assessments,
                "south_africa_eligibility": eligibility_assessment,
                "payment": payment_assessment,
                "freshness": freshness_assessment,
            }

        except Exception as error:
            verification_assessment = {
                "status": "assessment_error",
                "verification_status": "not_verified",
                "automatic_approval": False,
                "error": str(error)[:300],
            }

        report = {
            "investigation_id": (
                str(platform.get("id", "unknown"))
                + "-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            ),
            "platform_id": platform.get("id"),
            "domain": platform.get("domain"),
            "investigated_at": utc_now(),
            "status": (
                "completed" if successful_pages == len(pages) and pages
                else "partial" if successful_pages
                else "failed"
            ),
            "pages_checked": successful_pages,
            "pages": pages,
            "evidence": evidence,
            "verification_assessment": verification_assessment,
            "suggested_categories": suggested_categories,
            "category_status": "suggested_unverified",
            "south_africa_eligibility": (
                verification_assessment.get(
                    "south_africa_eligibility", {}
                ).get("status", "unknown")
            ),
            "payment_verified": False,
            "evidence_status": "unverified_observations",
        }

        registry = self._load_investigations()
        registry["investigations"].append(report)
        registry["updated_at"] = utc_now()
        self._save_investigations(registry)

        try:
            sync_result = identity_engine.sync_investigation(report)
            report["registry_sync"] = {
                "status": "success",
                "result": sync_result,
            }
        except Exception as error:
            report["registry_sync"] = {
                "status": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
            }

        registry["investigations"][-1] = report
        registry["updated_at"] = utc_now()
        self._save_investigations(registry)

        return report

    def run_investigation(
        self,
        identifiers,
        limit=MAX_PLATFORMS_PER_RUN,
    ):
        if not isinstance(identifiers, (list, tuple)):
            raise PlatformInvestigationError(
                "Platform identifiers must be a list or tuple."
            )

        if not isinstance(limit, int) or isinstance(limit, bool):
            raise PlatformInvestigationError(
                "Batch limit must be an integer."
            )

        if limit < 1 or limit > MAX_PLATFORMS_PER_RUN:
            raise PlatformInvestigationError(
                f"Batch limit must be between 1 and {MAX_PLATFORMS_PER_RUN}."
            )

        if not identifiers:
            raise PlatformInvestigationError(
                "At least one platform identifier is required."
            )

        if len(identifiers) > limit:
            raise PlatformInvestigationError(
                "Requested batch exceeds the permitted limit."
            )

        if len(set(identifiers)) != len(identifiers):
            raise PlatformInvestigationError(
                "Duplicate platform identifiers are not allowed."
            )

        reports = []

        for identifier in identifiers:
            try:
                reports.append(self.investigate_platform(identifier))
            except PlatformInvestigationError as error:
                reports.append({
                    "platform_identifier": str(identifier)[:200],
                    "status": "rejected",
                    "error": str(error)[:300],
                })

        return {
            "requested": len(identifiers),
            "processed": len(reports),
            "reports": reports,
        }

    def get_investigations(self, identifier=None):
        registry = self._load_investigations()
        reports = registry["investigations"]

        if identifier is None:
            return reports

        if not isinstance(identifier, str) or not identifier.strip():
            raise PlatformInvestigationError(
                "A valid platform ID or domain is required."
            )

        target = identifier.strip().lower()

        return [
            report for report in reports
            if target in (
                str(report.get("platform_id", "")).lower(),
                str(report.get("domain", "")).lower(),
            )
        ]

    def is_registered_url(self, platform, url):
        if not isinstance(platform, dict) or not isinstance(url, str):
            return False

        try:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
            domain = str(platform.get("domain", "")).lower().strip()

            if parsed.scheme != "https" or not hostname or not domain:
                return False

            return hostname == domain or hostname.endswith("." + domain)

        except Exception:
            return False


engine = PlatformInvestigationEngine()
