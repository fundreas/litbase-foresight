from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests
import os

# The current production API. Override with KICK_API or --api-base.
DEFAULT_BASE_URL = "https://api.kickbase.com/v4"

REQUEST_TIMEOUT = 30
MAX_WORKERS = 12

_session = None

def get_base_url():
    """Base URL of the Kickbase API.

    Read lazily rather than captured at import time, so a .env file or a command
    line override still applies no matter when this module was first imported.
    """

    return os.getenv("KICK_API", DEFAULT_BASE_URL).rstrip("/")

def get_session():
    """Return a shared requests session with retries for transient API failures."""

    global _session

    if _session is None:
        retry = Retry(
            total=4,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=MAX_WORKERS * 2,
            pool_maxsize=MAX_WORKERS * 2,
        )

        session = requests.Session()
        session.mount("https://", adapter)
        _session = session

    return _session

def get_json_with_token(url, token):
    """Fetch JSON data from a given URL using token for authorization."""

    resp = get_session().get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
    )

    # A JWT has a limited lifetime, so say what a rejection most likely means
    # instead of reporting a bare status code.
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Kickbase API rejected the token with HTTP {resp.status_code}. "
            "If KICK_TOKEN is set it has most likely expired; unset it to log in "
            "with KICK_USER / KICK_PASS instead."
        )

    # Only the status and URL are surfaced -- response bodies never reach the log,
    # because CI logs of this repo are public.
    if not resp.ok:
        raise RuntimeError(f"Kickbase API returned HTTP {resp.status_code} for {url}")

    return resp.json()
