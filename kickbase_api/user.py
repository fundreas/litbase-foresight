from kickbase_api.config import REQUEST_TIMEOUT, get_base_url, get_session
from datetime import datetime, timezone
import base64
import json
import time
import os

# All functions related to the user itself

def login(username, password):
    """Logs in to Kickbase and returns the authentication token."""

    url = f"{get_base_url()}/user/login"
    payload = {
        "em": username,
        "pass": password,
        "loy": False,
        "rep": {},
    }

    resp = get_session().post(url, json=payload, timeout=REQUEST_TIMEOUT)

    # Never echo the status text or body of a login response, it can contain
    # the submitted email address and these logs are public.
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Kickbase rejected the login with HTTP {resp.status_code}. "
            "Check KICK_USER and KICK_PASS."
        )

    if not resp.ok:
        raise RuntimeError(f"Kickbase login failed with HTTP {resp.status_code}")

    token = resp.json().get("tkn")
    if not token:
        raise RuntimeError("Kickbase login succeeded but returned no token")

    return token

def _token_expiry(token):
    """The exp claim of a JWT, or None if it cannot be read.

    The signature is deliberately not verified: this only decides whether the
    token is worth sending. The API stays the authority on whether it is valid.
    """

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None

def get_token():
    """Obtain a Kickbase JWT, by preferring KICK_TOKEN and logging in otherwise.

    A Kickbase token lives seven days, which is fine for a local run but means a
    scheduled one has to be able to mint its own -- hence the credentials. An
    expired KICK_TOKEN is stepped over rather than allowed to shadow them.
    """

    token = os.getenv("KICK_TOKEN")
    username = os.getenv("KICK_USER")
    password = os.getenv("KICK_PASS")

    if token:
        expiry = _token_expiry(token)

        # A minute of slack, so a token cannot expire mid-run
        if expiry is None or expiry > time.time() + 60:
            valid_until = (
                f", valid until {datetime.fromtimestamp(expiry, timezone.utc):%Y-%m-%d %H:%M UTC}"
                if expiry else ""
            )
            print(f"Using the token from KICK_TOKEN{valid_until}.")
            return token

        expired_at = datetime.fromtimestamp(expiry, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if not (username and password):
            raise RuntimeError(
                f"KICK_TOKEN expired at {expired_at} and there are no KICK_USER / "
                "KICK_PASS credentials to log in with instead."
            )

        print(f"KICK_TOKEN expired at {expired_at}, logging in instead.")

    if not (username and password):
        raise RuntimeError(
            "Missing credentials: set KICK_USER and KICK_PASS "
            "(GitHub secrets in CI, a local .env file otherwise), "
            "or KICK_TOKEN to use a token you already have."
        )

    token = login(username, password)
    print("Logged in to Kickbase.")

    return token
