def classify_failure(error_str: str) -> str:
    """Map error string to a failure category for the recovery router."""
    e = error_str.lower()
    if any(w in e for w in ["captcha", "recaptcha", "cloudflare", "challenge",
                             "turnstile", "i'm not a robot", "verify you are human"]):
        return "captcha"
    if any(w in e for w in ["location", "geographic", "not available in your", "your country",
                             "your region", "not provide service in"]):
        return "geo_blocked"
    if any(w in e for w in ["403", "forbidden", "unauthorized", "401"]):
        return "auth_blocked"
    if any(w in e for w in ["element not found", "no such element", "selector", "element"]):
        return "element_missing"
    if any(w in e for w in ["404", "page not found", "no such page"]):
        return "url_invalid"
    if any(w in e for w in ["405", "502", "503", "504", "gateway", "unavailable"]):
        return "site_down"
    if any(w in e for w in ["session", "expired", "logged out", "login required"]):
        return "session_expired"
    if any(w in e for w in ["timeout", "timed out"]):
        return "timeout"
    if any(w in e for w in ["429", "rate limit", "too many"]):
        return "rate_limit"
    if any(w in e for w in ["import", "module", "attribute", "nameerror"]):
        return "fatal"
    return "unknown"
