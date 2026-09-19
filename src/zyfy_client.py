import httpx

from config import ZYFY_API_KEY, ZYFY_BASE_URL


class ZyfyError(Exception):
    """Raised when the Zyfy Vehicle Intelligence API can't satisfy a lookup."""


def normalise_registration(registration: str) -> str:
    return registration.replace(" ", "").upper()


def lookup_vehicle(registration: str) -> dict:
    """Look up a UK vehicle by registration via the Zyfy Vehicle Intelligence API.

    Docs: https://zyfy.uk/docs/vehicle
    """
    if not ZYFY_API_KEY or ZYFY_API_KEY == "ea_live_your_key_here":
        raise ZyfyError(
            "ZYFY_API_KEY is not set. Add your real key to .env (see .env.example)."
        )

    reg = normalise_registration(registration)
    url = f"{ZYFY_BASE_URL.rstrip('/')}/vehicle/{reg}"
    headers = {"X-Api-Key": ZYFY_API_KEY}

    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
    except httpx.RequestError as exc:
        raise ZyfyError(f"Could not reach Zyfy API: {exc}") from exc

    if response.status_code == 404:
        raise ZyfyError(f"No vehicle found for registration {reg}")
    if response.status_code == 401:
        raise ZyfyError("Zyfy API rejected the request: invalid API key")
    if response.status_code == 429:
        raise ZyfyError("Zyfy API rate limit hit; retry later")

    response.raise_for_status()
    return response.json()
