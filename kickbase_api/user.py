from kickbase_api.config import BASE_URL, REQUEST_TIMEOUT, get_session

# All functions related to the user itself

def login(username, password):
    """Logs in to Kickbase and returns the authentication token."""

    if not username or not password:
        raise RuntimeError(
            "Missing credentials: set KICK_USER and KICK_PASS "
            "(GitHub secrets in CI, a local .env file otherwise)."
        )

    url = f"{BASE_URL}/user/login"
    payload = {
        "em": username,
        "pass": password,
        "loy": False,
        "rep": {},
    }

    resp = get_session().post(url, json=payload, timeout=REQUEST_TIMEOUT)

    # Never echo the status text or body of a login response, it can contain
    # the submitted email address and these logs are public.
    if not resp.ok:
        raise RuntimeError(f"Kickbase login failed with HTTP {resp.status_code}")

    token = resp.json().get("tkn")
    if not token:
        raise RuntimeError("Kickbase login succeeded but returned no token")

    return token
