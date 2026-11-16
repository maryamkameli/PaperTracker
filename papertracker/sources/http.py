"""Small GET helper with retries. Only the standard library, plus certifi when it's there."""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request

USER_AGENT = "PaperTracker/0.1 (personal reading list; github.com/maryamkameli/PaperTracker)"
RETRY_CODES = {429, 500, 502, 503, 504}


class DailyLimit(RuntimeError):
    """The service's free daily allowance is used up. Retrying today won't help."""

    def __init__(self, url: str, reset_seconds: str | None):
        hours = ""
        try:
            hours = f" It resets in about {max(1, round(int(reset_seconds) / 3600))} h."
        except (TypeError, ValueError):
            pass
        super().__init__(f"daily request limit reached for {url.split('?')[0]}.{hours}")

try:
    import certifi

    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # fall back to the system store
    _SSL = ssl.create_default_context()


def _retry_after(err: urllib.error.HTTPError) -> float:
    value = err.headers.get("Retry-After") if err.headers else None
    try:
        return min(float(value), 120.0) if value else 0.0
    except ValueError:
        return 0.0


def get(url: str, *, timeout: float = 60, retries: int = 4, accept: str | None = None, sleep=time.sleep) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    delay = 5.0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 429 and err.headers and err.headers.get("x-ratelimit-remaining") == "0":
                raise DailyLimit(url, err.headers.get("x-ratelimit-reset")) from None
            if err.code in RETRY_CODES and attempt < retries:
                sleep(_retry_after(err) or delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries:
                sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def get_json(url: str, **kwargs) -> dict:
    return json.loads(get(url, accept="application/json", **kwargs))
