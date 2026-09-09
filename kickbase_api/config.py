from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests

BASE_URL = "https://api.kickbase.com/v4"
REQUEST_TIMEOUT = 30
MAX_WORKERS = 12

_session = None

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
    # Only the status and URL are surfaced -- response bodies never reach the log,
    # because CI logs of this repo are public.
    if not resp.ok:
        raise RuntimeError(f"Kickbase API returned HTTP {resp.status_code} for {url}")

    return resp.json()
