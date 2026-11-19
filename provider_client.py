"""PyForge Coding Assistant - Private Provider API client."""

import os
import httpx


class ProviderError(RuntimeError):
    pass


class PyForgeProvider:
    def __init__(self):
        self.base_url = os.getenv(
            "PYFORGE_PROVIDER_URL",
            "http://127.0.0.1:8001"
        ).rstrip("/")

        self.api_key = os.getenv(
            "PYFORGE_CODING_ASSISTANT_API_KEY",
            ""
        ).strip()

        self.timeout = 30.0

    def _headers(self):
        if not self.api_key:
            raise ProviderError(
                "Coding Assistant Provider credential is not configured."
            )

        return {
            "X-PyForge-Key": self.api_key,
            "Content-Type": "application/json"
        }

    def identity(self):
        try:
            response = httpx.get(
                self.base_url + "/provider/v1/identity",
                headers=self._headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            if result.get("client") != "Coding Assistant":
                raise ProviderError(
                    "The configured credential does not belong to "
                    "the Coding Assistant client."
                )

            return result

        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Provider identity verification failed: {exc}"
            ) from exc

    def search(self, query, country="South Africa", max_sources=10):
        try:
            response = httpx.post(
                self.base_url + "/provider/v1/search",
                headers=self._headers(),
                json={
                    "query": query,
                    "country": country,
                    "max_sources": max_sources
                },
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Provider search request failed: {exc}"
            ) from exc


provider = PyForgeProvider()
