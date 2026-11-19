"""
VaultNex Evidence Verification Engine
Independent, conservative assessment of platform evidence.
"""

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse


ENGINE_NAME = "VaultNex Evidence Verification Engine"
ENGINE_VERSION = "1.0.0"

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

SOUTH_AFRICA_TERMS = (
    "south africa",
    "south african",
    "republic of south africa",
)

MAX_EVIDENCE_AGE_DAYS = 90


class EvidenceVerificationError(Exception):
    pass


class EvidenceVerificationEngine:

    def __init__(self):
        self.engine_name = ENGINE_NAME
        self.version = ENGINE_VERSION

    @staticmethod
    def utc_now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def normalize_domain(url):
        try:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                return None
            return parsed.hostname.lower().rstrip(".")
        except Exception:
            return None

    def assess_source_authority(self, source_url, registered_domain):
        source_host = self.normalize_domain(source_url)

        if not source_host:
            return {
                "status": "invalid_source",
                "authority": "unknown",
                "source_domain": None,
                "registered_domain": registered_domain,
                "is_first_party": False,
                "claim_verification": "not_assessed",
            }

        if not isinstance(registered_domain, str) or not registered_domain.strip():
            raise EvidenceVerificationError(
                "A registered platform domain is required."
            )

        registered_host = self.normalize_domain(
            "https://" + registered_domain.strip().strip("/")
            if "://" not in registered_domain
            else registered_domain.strip()
        )

        if not registered_host:
            raise EvidenceVerificationError(
                "The registered platform domain is invalid."
            )

        is_first_party = (
            source_host == registered_host
            or source_host.endswith("." + registered_host)
        )

        return {
            "status": "assessed",
            "authority": (
                "first_party_domain"
                if is_first_party
                else "third_party_domain"
            ),
            "source_domain": source_host,
            "registered_domain": registered_host,
            "is_first_party": is_first_party,
            "claim_verification": "not_assessed",
            "note": "Domain ownership classification does not prove the page claims are true.",
        }

    def assess_south_africa_eligibility(self, evidence_pages, registered_domain=None):
        if not isinstance(evidence_pages, list):
            raise EvidenceVerificationError(
                "Evidence pages must be supplied as a list."
            )

        positive_patterns = (
            "participants from south africa can participate",
            "south african residents can participate",
            "residents of south africa are eligible",
            "south africa is an eligible country",
            "south africa is supported",
            "we accept participants from south africa",
            "open to participants from south africa",
            "available to residents of south africa",
        )

        negative_patterns = (
            "participants from south africa cannot participate",
            "south african residents are not eligible",
            "residents of south africa are not eligible",
            "south africa is not an eligible country",
            "south africa is not supported",
            "we do not accept participants from south africa",
            "not available to residents of south africa",
            "south africa is excluded",
        )

        positive = []
        negative = []
        ignored = []

        for page in evidence_pages:
            if not isinstance(page, dict):
                continue

            source_url = page.get("source_url")
            claims = page.get("eligibility_claims", [])

            if not isinstance(claims, list):
                continue

            for claim in claims:
                if not isinstance(claim, dict):
                    continue

                excerpt = claim.get("excerpt", "")
                if not isinstance(excerpt, str):
                    continue

                lowered = " ".join(excerpt.lower().split())

                if not any(term in lowered for term in SOUTH_AFRICA_TERMS):
                    continue

                observation = {
                    "source_url": source_url,
                    "excerpt": excerpt[:500],
                    "verification_status": "unverified_observation",
                }

                # A country appearing in an explicit eligibility list
                # is recognised only when the source is first-party.
                authority = (
                    self.assess_source_authority(
                        source_url or "", registered_domain
                    )
                    if registered_domain
                    else {"is_first_party": False}
                )

                has_supported_country_list = (
                    (
                        "full list" in lowered
                        and "eligibility" in lowered
                    )
                    or "eligible countries" in lowered
                    or "supported countries" in lowered
                    or "countries we support" in lowered
                )

                has_positive = (
                    any(
                        pattern in lowered
                        for pattern in positive_patterns
                    )
                    or (
                        authority.get("is_first_party", False)
                        and has_supported_country_list
                    )
                )
                has_negative = any(
                    pattern in lowered for pattern in negative_patterns
                )

                if has_positive and has_negative:
                    positive.append(observation)
                    negative.append(observation)
                elif has_positive:
                    positive.append(observation)
                elif has_negative:
                    negative.append(observation)
                else:
                    ignored.append(observation)

        if positive and negative:
            status = "conflicting"
        elif positive:
            status = "supported_claim"
        elif negative:
            status = "supported_exclusion_claim"
        else:
            status = "insufficient_evidence"

        return {
            "country": "South Africa",
            "status": status,
            "verification_status": "not_verified",
            "accepted_claims": positive,
            "excluded_claims": negative,
            "ambiguous_claims": ignored,
            "automatic_approval": False,
        }

    def assess_payment_evidence(self, evidence_pages):
        if not isinstance(evidence_pages, list):
            raise EvidenceVerificationError(
                "Evidence pages must be supplied as a list."
            )

        payment_methods = {
            "paypal": ("paypal",),
            "payoneer": ("payoneer",),
            "bank_transfer": ("bank transfer", "bank transfers"),
            "wise": ("wise",),
            "skrill": ("skrill",),
            "airtm": ("airtm",),
            "gift_card": ("gift card", "gift cards"),
            "direct_deposit": ("direct deposit",),
        }

        payout_terms = (
            "minimum withdrawal",
            "minimum payout",
            "withdrawal threshold",
            "payment threshold",
            "cash out",
            "cashout",
            "payout schedule",
            "processing time",
            "withdrawal fee",
            "payout fee",
        )

        country_terms = SOUTH_AFRICA_TERMS

        methods_found = []
        methods_rejected = []
        payout_claims = []
        country_claims = []
        seen_methods = set()
        seen_rejected = set()
        seen_claims = set()

        for page in evidence_pages:
            if not isinstance(page, dict):
                continue

            source_url = page.get("source_url")
            method_claims = page.get("payment_method_claims", [])
            payout_page_claims = page.get("payout_claims", [])

            if not isinstance(method_claims, list):
                method_claims = []
            if not isinstance(payout_page_claims, list):
                payout_page_claims = []

            for claim in method_claims:
                if not isinstance(claim, dict):
                    continue

                excerpt = claim.get("excerpt", "")
                if not isinstance(excerpt, str):
                    continue

                lowered = " ".join(excerpt.lower().split())

                for method, terms in payment_methods.items():
                    matched_terms = [
                        term for term in terms
                        if re.search(
                            r"(?<!\w)" + re.escape(term) + r"(?!\w)",
                            lowered
                        )
                    ]

                    if not matched_terms:
                        continue

                    rejected = False
                    for term in matched_terms:
                        escaped = re.escape(term)
                        negative_patterns = (
                            rf"\b(?:no|never|not|without)\s+(?:any\s+)?{escaped}\b",
                            rf"\b{escaped}\b(?:\s+\w+){{0,3}}\s+\b(?:not accepted|not available|not offered|not supported|not provided)\b",
                            rf"\b(?:do not|don't|does not|doesn't|cannot|can't)\s+(?:accept|offer|provide|support|use)\s+(?:any\s+)?{escaped}\b",
                        )
                        if any(
                            re.search(pattern, lowered)
                            for pattern in negative_patterns
                        ):
                            rejected = True
                            break

                    fingerprint = (method, source_url, lowered)

                    if rejected:
                        if fingerprint not in seen_rejected:
                            seen_rejected.add(fingerprint)
                            methods_rejected.append({
                                "method": method,
                                "source_url": source_url,
                                "excerpt": excerpt[:500],
                                "verification_status": "unverified_rejection_observation",
                            })
                    elif fingerprint not in seen_methods:
                        seen_methods.add(fingerprint)
                        methods_found.append({
                            "method": method,
                            "source_url": source_url,
                            "excerpt": excerpt[:500],
                            "verification_status": "unverified_observation",
                        })
                if any(term in lowered for term in country_terms):
                    country_claims.append({
                        "source_url": source_url,
                        "excerpt": excerpt[:500],
                        "verification_status": "unverified_observation",
                    })

            for claim in payout_page_claims:
                if not isinstance(claim, dict):
                    continue

                excerpt = claim.get("excerpt", "")
                if not isinstance(excerpt, str):
                    continue

                lowered = " ".join(excerpt.lower().split())

                if any(term in lowered for term in payout_terms):
                    fingerprint = (source_url, lowered)
                    if fingerprint not in seen_claims:
                        seen_claims.add(fingerprint)
                        payout_claims.append({
                            "source_url": source_url,
                            "excerpt": excerpt[:500],
                            "verification_status": "unverified_observation",
                        })

                if any(term in lowered for term in country_terms):
                    country_claims.append({
                        "source_url": source_url,
                        "excerpt": excerpt[:500],
                        "verification_status": "unverified_observation",
                    })

        return {
            "status": (
                "payment_information_observed"
                if methods_found or payout_claims
                else "insufficient_evidence"
            ),
            "verification_status": "not_verified",
            "payment_methods_observed": methods_found,
            "payment_methods_rejected": methods_rejected,
            "payout_conditions_observed": payout_claims,
            "south_africa_payment_claims": country_claims,
            "payment_verified": False,
            "automatic_approval": False,
        }

    def assess_evidence_freshness(self, evidence_pages, reference_time=None):
        if not isinstance(evidence_pages, list):
            raise EvidenceVerificationError(
                "Evidence pages must be supplied as a list."
            )

        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        if not isinstance(reference_time, datetime):
            raise EvidenceVerificationError(
                "Reference time must be a datetime value."
            )

        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise EvidenceVerificationError(
                "Reference time must include a timezone."
            )

        reference_time = reference_time.astimezone(timezone.utc)
        assessed_pages = []

        for page in evidence_pages:
            if not isinstance(page, dict):
                continue

            observed_at = page.get("observed_at")
            status = "unknown"
            age_days = None

            if isinstance(observed_at, str) and observed_at.strip():
                try:
                    parsed_time = datetime.fromisoformat(
                        observed_at.strip().replace("Z", "+00:00")
                    )

                    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                        status = "unknown"
                    else:
                        parsed_time = parsed_time.astimezone(timezone.utc)
                        age_seconds = (
                            reference_time - parsed_time
                        ).total_seconds()

                        if age_seconds < 0:
                            status = "future_timestamp"
                        else:
                            age_days = age_seconds / 86400
                            status = (
                                "fresh"
                                if age_days <= MAX_EVIDENCE_AGE_DAYS
                                else "stale"
                            )
                except (ValueError, OverflowError):
                    status = "unknown"

            assessed_pages.append({
                "source_url": page.get("source_url"),
                "observed_at": observed_at,
                "age_days": round(age_days, 2) if age_days is not None else None,
                "freshness_status": status,
                "verification_status": "not_verified",
            })

        statuses = [
            item["freshness_status"] for item in assessed_pages
        ]

        if not statuses:
            overall_status = "insufficient_evidence"
        elif "future_timestamp" in statuses:
            overall_status = "invalid_timestamp"
        elif "stale" in statuses and "fresh" in statuses:
            overall_status = "mixed"
        elif "stale" in statuses:
            overall_status = "stale"
        elif "fresh" in statuses and "unknown" in statuses:
            overall_status = "partially_assessed"
        elif "fresh" in statuses:
            overall_status = "fresh"
        else:
            overall_status = "unknown"

        return {
            "status": overall_status,
            "maximum_age_days": MAX_EVIDENCE_AGE_DAYS,
            "pages_assessed": len(assessed_pages),
            "pages": assessed_pages,
            "verification_status": "not_verified",
            "automatic_approval": False,
        }

    @staticmethod
    def content_fingerprint(text):
        if not isinstance(text, str):
            raise EvidenceVerificationError(
                "Evidence content must be text."
            )
        return hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

    def health(self):
        return {
            "engine": self.engine_name,
            "version": self.version,
            "status": "ready",
            "verification_mode": "conservative",
            "automatic_approval": False,
            "timestamp": self.utc_now(),
        }


engine = EvidenceVerificationEngine()
