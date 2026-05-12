import re
import time
import requests
from typing import Optional

# You can switch between these if one fails
BASE_URL = "https://mempool.space/api"
# BASE_URL = "https://blockstream.info/api"

# ─── Simple in-memory cache ───────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 120  # seconds


def _cache_get(key: str) -> Optional[object]:
    entry = _cache.get(key)

    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]

    return None


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (time.time(), value)


# ─── Address validation ───────────────────────────────────────────────────────

_P2PKH_RE = re.compile(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$")
_P2SH_RE = re.compile(r"^3[a-km-zA-HJ-NP-Z1-9]{25,34}$")
_BECH32_RE = re.compile(r"^(bc1|tb1)[a-z0-9]{6,87}$", re.IGNORECASE)


def validate_address(address: str) -> bool:
    """
    Validate common Bitcoin address formats.
    """

    if not address or not isinstance(address, str):
        return False

    a = address.strip()

    return bool(
        _P2PKH_RE.match(a)
        or _P2SH_RE.match(a)
        or _BECH32_RE.match(a)
    )


def detect_address_type(address: str) -> str:
    """
    Detect human-readable BTC address type.
    """

    a = address.strip()

    if a.startswith("bc1p") or a.startswith("tb1p"):
        return "P2TR (Taproot)"

    if _BECH32_RE.match(a):
        return "P2WPKH (SegWit)"

    if _P2SH_RE.match(a):
        return "P2SH"

    if _P2PKH_RE.match(a):
        return "P2PKH (Legacy)"

    return "Unknown"


# ─── API helpers ─────────────────────────────────────────────────────────────


def _get(url: str, timeout: int = 15) -> Optional[requests.Response]:
    """
    Safe HTTP GET wrapper with logging + headers.
    """

    try:
        headers = {
            "User-Agent": "Chainlink-OSINT/2.1",
            "Accept": "application/json",
        }

        r = requests.get(
            url,
            headers=headers,
            timeout=timeout,
        )

        print(f"[HTTP] {r.status_code} -> {url}")

        if r.status_code != 200:
            print("[API ERROR]")
            print(r.text[:500])
            return None

        return r

    except requests.Timeout:
        print(f"[TIMEOUT] {url}")
        return None

    except requests.RequestException as e:
        print(f"[REQUEST ERROR] {e}")
        return None

    except Exception as e:
        print(f"[UNKNOWN ERROR] {e}")
        return None


# ─── Public interface ─────────────────────────────────────────────────────────


def get_wallet_info(address: str) -> Optional[dict]:
    """
    Fetch wallet statistics and balances.
    """

    key = f"info:{address}"

    cached = _cache_get(key)
    if cached is not None:
        return cached

    print(f"[INFO] Fetching wallet info for: {address}")

    r = _get(f"{BASE_URL}/address/{address}")

    if r is None:
        return None

    try:
        data = r.json()

        print("[SUCCESS] Wallet info fetched")
        print(data)

        _cache_set(key, data)

        return data

    except Exception as e:
        print(f"[JSON ERROR] {e}")
        return None


def get_wallet_transactions(
    address: str,
    max_txs: int = 100,
) -> list[dict]:
    """
    Fetch wallet transactions with auto pagination.
    """

    key = f"txs:{address}:{max_txs}"

    cached = _cache_get(key)
    if cached is not None:
        return cached

    print(f"[INFO] Fetching transactions for: {address}")

    all_txs: list[dict] = []

    # ── mempool txs ─────────────────────────────────────────────────────────

    r = _get(f"{BASE_URL}/address/{address}/txs/mempool")

    if r:
        try:
            mempool_txs = r.json()
            all_txs.extend(mempool_txs)
        except Exception as e:
            print(f"[MEMPOOL JSON ERROR] {e}")

    # ── confirmed txs ──────────────────────────────────────────────────────

    last_txid: Optional[str] = None

    while len(all_txs) < max_txs:

        url = f"{BASE_URL}/address/{address}/txs/chain"

        if last_txid:
            url += f"/{last_txid}"

        r = _get(url)

        if r is None:
            break

        try:
            page = r.json()
        except Exception as e:
            print(f"[CHAIN JSON ERROR] {e}")
            break

        if not page:
            break

        all_txs.extend(page)

        if len(page) < 25:
            break

        last_txid = page[-1].get("txid")

        if not last_txid:
            break

        if len(all_txs) >= max_txs:
            break

    result = all_txs[:max_txs]

    print(f"[SUCCESS] Loaded {len(result)} transactions")

    _cache_set(key, result)

    return result


def get_wallet_utxos(address: str) -> list[dict]:
    """
    Fetch all wallet UTXOs.
    """

    key = f"utxos:{address}"

    cached = _cache_get(key)
    if cached is not None:
        return cached

    print(f"[INFO] Fetching UTXOs for: {address}")

    r = _get(f"{BASE_URL}/address/{address}/utxo")

    if r is None:
        return []

    try:
        utxos = r.json()

        print(f"[SUCCESS] Loaded {len(utxos)} UTXOs")

        _cache_set(key, utxos)

        return utxos

    except Exception as e:
        print(f"[UTXO JSON ERROR] {e}")
        return []


def get_transaction(txid: str) -> Optional[dict]:
    """
    Fetch single transaction by txid.
    """

    key = f"tx:{txid}"

    cached = _cache_get(key)
    if cached is not None:
        return cached

    print(f"[INFO] Fetching tx: {txid}")

    r = _get(f"{BASE_URL}/tx/{txid}")

    if r is None:
        return None

    try:
        data = r.json()

        _cache_set(key, data)

        return data

    except Exception as e:
        print(f"[TX JSON ERROR] {e}")
        return None


def get_address_info_bulk(
    addresses: list[str]
) -> dict[str, Optional[dict]]:
    """
    Fetch multiple wallet infos.
    """

    results: dict[str, Optional[dict]] = {}

    for addr in addresses:
        results[addr] = get_wallet_info(addr)

    return results


def clear_cache() -> None:
    """
    Clear in-memory cache.
    """

    _cache.clear()

    print("[CACHE] Cleared")
