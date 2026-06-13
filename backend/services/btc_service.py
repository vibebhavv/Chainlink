import re
import time
import requests
from typing import Optional

# --- Chain configuration ----------------------------------------------------
#
#  Each chain entry defines:
#    esplora  – Esplora-compatible REST base URL (BTC / LTC use this path)
#    blockscout – Blockscout v2 REST base URL   (ETH uses this path)
#    xrpscan  – XRPScan REST base URL           (XRP uses this path)
#    solana   – Solana RPC + Helius REST         (SOL uses this path)
#
#  BTC  → blockstream.info  (same Esplora API shape as mempool.space, zero key)
#  ETH  → eth.blockscout.com (free public REST, no key required)
#  LTC  → litecoinspace.org  (mempool.space fork, identical Esplora paths)
#  SOL  → mainnet-beta RPC  (official Solana Foundation public RPC)
#  XRP  → xrpscan.com       (free public REST, no key required)
#

CHAIN_CONFIG = {
    "BTC": {
        "type":    "esplora",
        "base":    "https://blockstream.info/api",
        # Fallback if blockstream is down:
        # "base": "https://mempool.space/api",
    },
    "ETH": {
        "type":    "blockscout",
        "base":    "https://eth.blockscout.com/api/v2",
    },
    "LTC": {
        "type":    "esplora",
        "base":    "https://litecoinspace.org/api",
    },
    "SOL": {
        "type":    "solana_rpc",
        "rpc":     "https://api.mainnet-beta.solana.com",
        # Helius free-tier RPC (faster, same JSON-RPC shape).
        # Sign up at helius.dev for a free key, then replace the line below:
        # "rpc": "https://mainnet.helius-rpc.com/?api-key=YOUR_FREE_KEY",
    },
    "XRP": {
        "type":    "xrpscan",
        "base":    "https://api.xrpscan.com/api/v1",
    },
}

# Default chain used by legacy helpers that don't pass chain= explicitly
DEFAULT_CHAIN = "BTC"


_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 120  # seconds


def _cache_get(key: str) -> Optional[object]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (time.time(), value)


_P2PKH_RE  = re.compile(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$")
_P2SH_RE   = re.compile(r"^3[a-km-zA-HJ-NP-Z1-9]{25,34}$")
_BECH32_RE = re.compile(r"^(bc1|tb1)[a-z0-9]{6,87}$", re.IGNORECASE)

_ETH_RE    = re.compile(r"^0x[0-9a-fA-F]{40}$")
_LTC_RE    = re.compile(r"^[LMltc][a-km-zA-HJ-NP-Z1-9]{26,33}$")
_SOL_RE    = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_XRP_RE    = re.compile(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$")


def validate_address(address: str, chain: str = DEFAULT_CHAIN) -> bool:
    if not address or not isinstance(address, str):
        return False
    a = address.strip()
    if chain == "BTC":
        return bool(_P2PKH_RE.match(a) or _P2SH_RE.match(a) or _BECH32_RE.match(a))
    if chain == "ETH":
        return bool(_ETH_RE.match(a))
    if chain == "LTC":
        return bool(_LTC_RE.match(a) or re.match(r"^ltc1[a-z0-9]{6,87}$", a, re.I))
    if chain == "SOL":
        return bool(_SOL_RE.match(a))
    if chain == "XRP":
        return bool(_XRP_RE.match(a))
    return False


def detect_address_type(address: str, chain: str = DEFAULT_CHAIN) -> str:
    a = address.strip()
    if chain == "BTC":
        if a.startswith("bc1p") or a.startswith("tb1p"):
            return "P2TR (Taproot)"
        if _BECH32_RE.match(a):
            return "P2WPKH (SegWit)"
        if _P2SH_RE.match(a):
            return "P2SH"
        if _P2PKH_RE.match(a):
            return "P2PKH (Legacy)"
    if chain == "ETH":
        return "EVM (Ethereum)"
    if chain == "LTC":
        if re.match(r"^ltc1", a, re.I):
            return "LTC SegWit (Bech32)"
        if a.startswith("M"):
            return "LTC P2SH"
        return "LTC P2PKH (Legacy)"
    if chain == "SOL":
        return "Solana Account"
    if chain == "XRP":
        return "XRP Ledger Account"
    return "Unknown"

def _get(url: str, timeout: int = 15) -> Optional[requests.Response]:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Chainlink-OSINT/2.1", "Accept": "application/json"},
            timeout=timeout,
        )
        print(f"[HTTP] {r.status_code} -> {url}")
        if r.status_code != 200:
            print("[API ERROR]", r.text[:500])
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


def _post(url: str, payload: dict, timeout: int = 15) -> Optional[requests.Response]:
    try:
        r = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=timeout,
        )
        print(f"[HTTP POST] {r.status_code} -> {url}")
        if r.status_code != 200:
            print("[API ERROR]", r.text[:500])
            return None
        return r
    except requests.Timeout:
        print(f"[TIMEOUT] {url}")
        return None
    except Exception as e:
        print(f"[POST ERROR] {e}")
        return None

def _esplora_wallet_info(address: str, base: str) -> Optional[dict]:
    r = _get(f"{base}/address/{address}")
    if r is None:
        return None
    try:
        return r.json()
    except Exception as e:
        print(f"[JSON ERROR] {e}")
        return None


def _esplora_transactions(address: str, base: str, max_txs: int) -> list[dict]:
    all_txs: list[dict] = []

    # mempool (unconfirmed) txs
    r = _get(f"{base}/address/{address}/txs/mempool")
    if r:
        try:
            all_txs.extend(r.json())
        except Exception as e:
            print(f"[MEMPOOL JSON ERROR] {e}")

    # confirmed txs (paginated, 25 per page)
    last_txid: Optional[str] = None
    while len(all_txs) < max_txs:
        url = f"{base}/address/{address}/txs/chain"
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

    return all_txs[:max_txs]


def _esplora_utxos(address: str, base: str) -> list[dict]:
    r = _get(f"{base}/address/{address}/utxo")
    if r is None:
        return []
    try:
        return r.json()
    except Exception as e:
        print(f"[UTXO JSON ERROR] {e}")
        return []

def _blockscout_wallet_info(address: str, base: str) -> Optional[dict]:
    r = _get(f"{base}/addresses/{address}")
    if r is None:
        return None
    try:
        d = r.json()
        # coin_balance is in wei (string)
        balance_wei  = int(d.get("coin_balance") or 0)
        tx_count     = d.get("transactions_count", 0) or 0
        return {
            "chain_stats": {
                "funded_txo_sum": balance_wei,   # best approximation
                "spent_txo_sum":  0,
                "tx_count":       tx_count,
                "funded_txo_count": tx_count,
                "spent_txo_count":  0,
            },
            "mempool_stats": {
                "funded_txo_sum": 0,
                "spent_txo_sum":  0,
                "tx_count":       0,
            },
            # Keep raw data accessible
            "_raw": d,
        }
    except Exception as e:
        print(f"[BLOCKSCOUT JSON ERROR] {e}")
        return None


def _blockscout_transactions(address: str, base: str, max_txs: int) -> list[dict]:
    """
    Fetch ETH transactions from Blockscout and normalise them into a shape
    similar to Esplora transactions so the existing parser works.
    """
    all_txs: list[dict] = []
    next_page_params: Optional[str] = None

    while len(all_txs) < max_txs:
        url = f"{base}/addresses/{address}/transactions?filter=to%7Cfrom"
        if next_page_params:
            url += f"&{next_page_params}"

        r = _get(url)
        if r is None:
            break
        try:
            data = r.json()
        except Exception as e:
            print(f"[BLOCKSCOUT TX JSON ERROR] {e}")
            break

        items = data.get("items", [])
        if not items:
            break

        for tx in items:
            value_wei = int(tx.get("value") or 0)
            fee_wei   = int((tx.get("fee") or {}).get("value") or 0)
            sender    = (tx.get("from") or {}).get("hash", "")
            receiver  = (tx.get("to")   or {}).get("hash", "") if tx.get("to") else ""
            is_out    = sender.lower() == address.lower()

            # Normalise to Esplora-ish shape
            normalised = {
                "txid":   tx.get("hash", ""),
                "fee":    fee_wei,
                "status": {
                    "confirmed":    tx.get("status") == "ok",
                    "block_height": tx.get("block"),
                    "block_time":   tx.get("timestamp"),
                },
                "vin": [{"prevout": {"scriptpubkey_address": sender, "value": value_wei}}],
                "vout": [{"scriptpubkey_address": receiver, "value": value_wei}],
                "_direction": "out" if is_out else "in",
                "_value_wei": value_wei,
            }
            all_txs.append(normalised)

        # Pagination
        next_params = data.get("next_page_params")
        if not next_params:
            break
        # Convert dict to query string
        next_page_params = "&".join(f"{k}={v}" for k, v in next_params.items())

    return all_txs[:max_txs]


def _blockscout_utxos(address: str, base: str) -> list[dict]:
    """
    ETH doesn't use UTXOs. We return a synthetic single UTXO representing
    the current balance so the /utxos endpoint still returns useful data.
    """
    r = _get(f"{base}/addresses/{address}")
    if r is None:
        return []
    try:
        d = r.json()
        balance = int(d.get("coin_balance") or 0)
        if balance == 0:
            return []
        return [{
            "txid":  "eth_balance",
            "vout":  0,
            "value": balance,
            "status": {"confirmed": True, "block_height": None},
        }]
    except Exception as e:
        print(f"[BLOCKSCOUT UTXO ERROR] {e}")
        return []

def _lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000


def _solana_wallet_info(address: str, rpc: str) -> Optional[dict]:
    # getAccountInfo
    r = _post(rpc, {
        "jsonrpc": "2.0", "id": 1,
        "method": "getAccountInfo",
        "params": [address, {"encoding": "jsonParsed"}],
    })
    if r is None:
        return None
    try:
        data  = r.json()
        value = data.get("result", {}).get("value") or {}
        lamports = value.get("lamports", 0)
        return {
            "chain_stats": {
                "funded_txo_sum":   lamports,
                "spent_txo_sum":    0,
                "tx_count":         0,
                "funded_txo_count": 1,
                "spent_txo_count":  0,
            },
            "mempool_stats": {"funded_txo_sum": 0, "spent_txo_sum": 0, "tx_count": 0},
            "_raw": value,
        }
    except Exception as e:
        print(f"[SOLANA JSON ERROR] {e}")
        return None


def _solana_transactions(address: str, rpc: str, max_txs: int) -> list[dict]:
    sig_r = _post(rpc, {
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": min(max_txs, 100)}],
    })
    if sig_r is None:
        return []
    try:
        sigs = [s["signature"] for s in sig_r.json().get("result", [])]
    except Exception as e:
        print(f"[SOLANA SIG ERROR] {e}")
        return []

    all_txs: list[dict] = []
    for sig in sigs[:max_txs]:
        tx_r = _post(rpc, {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTransaction",
            "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        })
        if tx_r is None:
            continue
        try:
            tx_data = tx_r.json().get("result")
            if not tx_data:
                continue
            meta    = tx_data.get("meta", {})
            slot    = tx_data.get("slot", 0)
            fee_lam = meta.get("fee", 0)

            # Build counterparties from accountKeys
            keys = (tx_data.get("transaction", {})
                           .get("message", {})
                           .get("accountKeys", []))
            addresses = []
            for k in keys:
                addr = k.get("pubkey") if isinstance(k, dict) else k
                if addr and addr != address:
                    addresses.append(addr)

            normalised = {
                "txid":   sig,
                "fee":    fee_lam,
                "status": {
                    "confirmed":    meta.get("err") is None,
                    "block_height": slot,
                    "block_time":   tx_data.get("blockTime"),
                },
                "vin":  [{"prevout": {"scriptpubkey_address": address, "value": 0}}],
                "vout": [{"scriptpubkey_address": a, "value": 0} for a in addresses[:5]],
            }
            all_txs.append(normalised)
        except Exception as e:
            print(f"[SOLANA TX ERROR] {e}")
            continue

    return all_txs


def _solana_utxos(address: str, rpc: str) -> list[dict]:
    r = _post(rpc, {
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [address],
    })
    if r is None:
        return []
    try:
        lamports = r.json().get("result", {}).get("value", 0)
        if lamports == 0:
            return []
        return [{
            "txid":  "sol_balance",
            "vout":  0,
            "value": lamports,
            "status": {"confirmed": True, "block_height": None},
        }]
    except Exception as e:
        print(f"[SOLANA UTXO ERROR] {e}")
        return []

_DROPS_PER_XRP = 1_000_000


def _xrp_wallet_info(address: str, base: str) -> Optional[dict]:
    r = _get(f"{base}/account/{address}")
    if r is None:
        return None
    try:
        d      = r.json()
        acct   = d.get("account_data", d)  # xrpscan wraps in account_data
        drops  = int(acct.get("Balance", 0))
        tx_seq = int(acct.get("Sequence", 0))
        return {
            "chain_stats": {
                "funded_txo_sum":   drops,
                "spent_txo_sum":    0,
                "tx_count":         tx_seq,
                "funded_txo_count": tx_seq,
                "spent_txo_count":  0,
            },
            "mempool_stats": {"funded_txo_sum": 0, "spent_txo_sum": 0, "tx_count": 0},
            "_raw": d,
        }
    except Exception as e:
        print(f"[XRPSCAN JSON ERROR] {e}")
        return None


def _xrp_transactions(address: str, base: str, max_txs: int) -> list[dict]:
    r = _get(f"{base}/account/{address}/transactions?limit={min(max_txs, 200)}")
    if r is None:
        return []
    try:
        items = r.json()
        if isinstance(items, dict):
            items = items.get("transactions", [])
    except Exception as e:
        print(f"[XRP TX JSON ERROR] {e}")
        return []

    all_txs: list[dict] = []
    for tx in items[:max_txs]:
        meta    = tx.get("meta", {})
        amount  = tx.get("Amount", 0)
        value   = int(amount) if isinstance(amount, (int, str)) and str(amount).isdigit() else 0
        sender  = tx.get("Account", "")
        dest    = tx.get("Destination", "")
        is_out  = sender == address

        normalised = {
            "txid":   tx.get("hash", ""),
            "fee":    int(tx.get("Fee", 0)),
            "status": {
                "confirmed":    meta.get("TransactionResult") == "tesSUCCESS",
                "block_height": tx.get("ledger_index"),
                "block_time":   tx.get("date"),
            },
            "vin":  [{"prevout": {"scriptpubkey_address": sender, "value": value}}],
            "vout": [{"scriptpubkey_address": dest,   "value": value}] if dest else [],
            "_direction": "out" if is_out else "in",
        }
        all_txs.append(normalised)
    return all_txs


def _xrp_utxos(address: str, base: str) -> list[dict]:
    """XRP doesn't use UTXOs; return balance as synthetic entry."""
    r = _get(f"{base}/account/{address}")
    if r is None:
        return []
    try:
        d     = r.json()
        acct  = d.get("account_data", d)
        drops = int(acct.get("Balance", 0))
        if drops == 0:
            return []
        return [{"txid": "xrp_balance", "vout": 0, "value": drops,
                 "status": {"confirmed": True, "block_height": None}}]
    except Exception as e:
        print(f"[XRP UTXO ERROR] {e}")
        return []

def get_wallet_info(address: str, chain: str = DEFAULT_CHAIN) -> Optional[dict]:
    key = f"info:{chain}:{address}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    print(f"[INFO] Fetching wallet info for: {address} [{chain}]")
    cfg = CHAIN_CONFIG.get(chain.upper())
    if not cfg:
        print(f"[ERROR] Unknown chain: {chain}")
        return None

    t = cfg["type"]
    if t == "esplora":
        data = _esplora_wallet_info(address, cfg["base"])
    elif t == "blockscout":
        data = _blockscout_wallet_info(address, cfg["base"])
    elif t == "solana_rpc":
        data = _solana_wallet_info(address, cfg["rpc"])
    elif t == "xrpscan":
        data = _xrp_wallet_info(address, cfg["base"])
    else:
        print(f"[ERROR] Unsupported chain type: {t}")
        return None

    if data:
        print(f"[SUCCESS] Wallet info fetched [{chain}]")
        _cache_set(key, data)
    return data


def get_wallet_transactions(
    address: str,
    max_txs: int = 100,
    chain: str = DEFAULT_CHAIN,
) -> list[dict]:
    key = f"txs:{chain}:{address}:{max_txs}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    print(f"[INFO] Fetching transactions for: {address} [{chain}]")
    cfg = CHAIN_CONFIG.get(chain.upper())
    if not cfg:
        return []

    t = cfg["type"]
    if t == "esplora":
        result = _esplora_transactions(address, cfg["base"], max_txs)
    elif t == "blockscout":
        result = _blockscout_transactions(address, cfg["base"], max_txs)
    elif t == "solana_rpc":
        result = _solana_transactions(address, cfg["rpc"], max_txs)
    elif t == "xrpscan":
        result = _xrp_transactions(address, cfg["base"], max_txs)
    else:
        result = []

    print(f"[SUCCESS] Loaded {len(result)} transactions [{chain}]")
    _cache_set(key, result)
    return result


def get_wallet_utxos(address: str, chain: str = DEFAULT_CHAIN) -> list[dict]:
    key = f"utxos:{chain}:{address}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    print(f"[INFO] Fetching UTXOs for: {address} [{chain}]")
    cfg = CHAIN_CONFIG.get(chain.upper())
    if not cfg:
        return []

    t = cfg["type"]
    if t == "esplora":
        result = _esplora_utxos(address, cfg["base"])
    elif t == "blockscout":
        result = _blockscout_utxos(address, cfg["base"])
    elif t == "solana_rpc":
        result = _solana_utxos(address, cfg["rpc"])
    elif t == "xrpscan":
        result = _xrp_utxos(address, cfg["base"])
    else:
        result = []

    print(f"[SUCCESS] Loaded {len(result)} UTXOs [{chain}]")
    _cache_set(key, result)
    return result


def get_transaction(txid: str, chain: str = DEFAULT_CHAIN) -> Optional[dict]:
    key = f"tx:{chain}:{txid}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    cfg = CHAIN_CONFIG.get(chain.upper())
    if not cfg:
        return None

    print(f"[INFO] Fetching tx: {txid} [{chain}]")
    t = cfg["type"]
    r = None
    if t == "esplora":
        r = _get(f"{cfg['base']}/tx/{txid}")
    elif t == "blockscout":
        r = _get(f"{cfg['base']}/transactions/{txid}")
    elif t == "xrpscan":
        r = _get(f"{cfg['base']}/tx/{txid}")

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
    addresses: list[str],
    chain: str = DEFAULT_CHAIN,
) -> dict[str, Optional[dict]]:
    return {addr: get_wallet_info(addr, chain=chain) for addr in addresses}


def clear_cache() -> None:
    _cache.clear()
    print("[CACHE] Cleared")
