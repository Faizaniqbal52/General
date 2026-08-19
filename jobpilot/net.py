"""Polite HTTP with on-disk caching.

Everything the agent fetches goes through here so there is exactly one place
that sets the user agent, the timeout, the delay between requests and the cache.
Only public, machine-readable endpoints are ever requested: the ATS job-board
APIs that companies publish for exactly this purpose, and pages you point it at.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover
    requests = None

USER_AGENT = (
    "JobPilot/0.1 (personal job-search assistant; contact via the address in the profile)"
)
DEFAULT_TIMEOUT = 20
MIN_DELAY_SECONDS = 1.0


class FetchError(RuntimeError):
    pass


@dataclass
class Response:
    url: str
    status: int
    text: str
    from_cache: bool = False

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise FetchError(f"{self.url}: response was not JSON ({exc})") from exc


class Client:
    def __init__(self, cache_dir: str | Path | None = None, delay: float = MIN_DELAY_SECONDS,
                 timeout: int = DEFAULT_TIMEOUT, offline: bool = False):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.timeout = timeout
        self.offline = offline
        self._last_host_hit: dict[str, float] = {}

    # -- cache -----------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")

    def _read_cache(self, url: str, max_age: float) -> Response | None:
        path = self._cache_path(url)
        if not path or not path.exists():
            return None
        if max_age >= 0 and (time.time() - path.stat().st_mtime) > max_age:
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return Response(url=url, status=int(blob.get("status", 200)),
                        text=blob.get("text", ""), from_cache=True)

    def _write_cache(self, response: Response) -> None:
        path = self._cache_path(response.url)
        if not path:
            return
        path.write_text(json.dumps({"status": response.status, "text": response.text,
                                    "url": response.url}), encoding="utf-8")

    # -- fetch -----------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = url.split("/")[2] if "://" in url else url
        last = self._last_host_hit.get(host)
        if last is not None:
            wait = self.delay - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_host_hit[host] = time.time()

    def get(self, url: str, *, max_age: float = 6 * 3600, headers: dict[str, str] | None = None) -> Response:
        cached = self._read_cache(url, max_age)
        if cached is not None:
            return cached
        if self.offline:
            raise FetchError(f"offline mode and {url} is not cached")
        self._throttle(url)
        hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.8"}
        hdrs.update(headers or {})
        try:
            if requests is not None:
                r = requests.get(url, headers=hdrs, timeout=self.timeout)
                response = Response(url=url, status=r.status_code, text=r.text)
            else:
                req = Request(url, headers=hdrs)
                with urlopen(req, timeout=self.timeout) as handle:  # noqa: S310 - fixed https endpoints
                    body = handle.read().decode("utf-8", "replace")
                    response = Response(url=url, status=handle.status, text=body)
        except HTTPError as exc:
            raise FetchError(f"{url}: HTTP {exc.code}") from exc
        except (URLError, OSError) as exc:
            raise FetchError(f"{url}: {exc}") from exc
        except Exception as exc:  # requests raises its own hierarchy
            raise FetchError(f"{url}: {exc}") from exc
        if response.status >= 400:
            raise FetchError(f"{url}: HTTP {response.status}")
        self._write_cache(response)
        return response

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()
