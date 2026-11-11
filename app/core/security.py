import hashlib
import hmac
import time


def constant_time_equals(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _derive_signing_key(api_key: str) -> bytes:
    return hashlib.sha256(f"duck-to-api-signing:{api_key}".encode("utf-8")).digest()


def sign_file_token(api_key: str, resource_path: str, ttl_seconds: int = 86400) -> str:
    """Create an expiry-bound HMAC token scoped to a single stored file path."""
    exp = int(time.time()) + ttl_seconds
    payload = f"{resource_path}:{exp}".encode("utf-8")
    sig = hmac.new(_derive_signing_key(api_key), payload, hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_file_token(api_key: str, resource_path: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp_str, sig = token.split(".", 1)
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    payload = f"{resource_path}:{exp}".encode("utf-8")
    expected_sig = hmac.new(_derive_signing_key(api_key), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


def create_session_cookie_value(api_key: str, ttl_seconds: int = 604800) -> str:
    return sign_file_token(api_key, "dashboard-session", ttl_seconds=ttl_seconds)


def verify_session_cookie_value(api_key: str, cookie_val: str | None) -> bool:
    return verify_file_token(api_key, "dashboard-session", cookie_val)
