from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware

from backend.utils.case_manager import (
    create_case,
    load_case,
    list_cases,
    save_case,
    add_wallet_to_case,
    add_note_to_case,
    delete_case,
)
from backend.utils.risk_engine import calculate_risk_score
from backend.services.btc_service import (
    validate_address,
    detect_address_type,
    get_wallet_info,
    get_wallet_transactions,
    get_wallet_utxos,
)
from backend.utils.parser import (
    parse_transactions,
    build_wallet_profile,
    satoshi_to_btc,
)
from backend.graphs.wallet_graph import build_graph_data, build_multihop_graph

# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Chainlink OSINT API",
    description="Bitcoin wallet intelligence & graph analysis",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _require_valid_address(address: str) -> None:
    if not validate_address(address):
        raise HTTPException(
            status_code=400,
            detail=f"'{address}' is not a valid Bitcoin address.",
        )


def _chain_stats(wallet_info: dict) -> dict:
    return wallet_info.get("chain_stats", {})


def _mempool_stats(wallet_info: dict) -> dict:
    return wallet_info.get("mempool_stats", {})


# ─── Core routes ──────────────────────────────────────────────────────────────

@app.get("/")
def home():
    return {
        "tool":    "Chainlink BTC Wallet OSINT",
        "version": "2.1.0",
        "status":  "running",
        "endpoints": [
            "GET  /wallet/{address}",
            "GET  /wallet/{address}/summary",
            "GET  /wallet/{address}/utxos",
            "GET  /wallet/{address}/graph",
            "GET  /wallet/{address}/hops?depth=2&max_nodes=80",
            "GET  /compare?a={addr1}&b={addr2}",
            "POST /case/create/{name}",
            "GET  /cases",
            "GET  /case/{name}",
            "POST /case/{name}/wallet/{address}",
            "POST /case/{name}/note",
            "DELETE /case/{name}",
        ],
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── Full wallet analysis ──────────────────────────────────────────────────────

@app.get("/wallet/{address}")
def wallet_lookup(
    address: str,
    max_txs: int = Query(default=100, ge=1, le=250),
):
    _require_valid_address(address)

    wallet_info = get_wallet_info(address)
    if not wallet_info:
        raise HTTPException(status_code=404, detail="Wallet not found or API unavailable.")

    transactions  = get_wallet_transactions(address, max_txs=max_txs)
    parsed_txs    = parse_transactions(transactions, address)
    profile       = build_wallet_profile(parsed_txs, address)
    risk_analysis = calculate_risk_score(parsed_txs)  # called once

    cs = _chain_stats(wallet_info)
    ms = _mempool_stats(wallet_info)

    funded_chain = cs.get("funded_txo_sum", 0)
    spent_chain  = cs.get("spent_txo_sum",  0)
    funded_mem   = ms.get("funded_txo_sum", 0)
    spent_mem    = ms.get("spent_txo_sum",  0)

    return {
        "wallet":             address,
        "address_type":       detect_address_type(address),
        "balance_btc":        satoshi_to_btc((funded_chain + funded_mem) - (spent_chain + spent_mem)),
        "total_received_btc": satoshi_to_btc(funded_chain),
        "total_sent_btc":     satoshi_to_btc(spent_chain),
        "transaction_count":  cs.get("tx_count", 0) + ms.get("tx_count", 0),
        "confirmed_tx_count": cs.get("tx_count", 0),
        "mempool_tx_count":   ms.get("tx_count", 0),
        "profile":            profile,
        "transactions":       parsed_txs,
        "risk_analysis":      risk_analysis,
    }


# ── Lightweight summary ───────────────────────────────────────────────────────

@app.get("/wallet/{address}/summary")
def wallet_summary(address: str):
    _require_valid_address(address)

    wallet_info = get_wallet_info(address)
    if not wallet_info:
        raise HTTPException(status_code=404, detail="Wallet not found or API unavailable.")

    cs = _chain_stats(wallet_info)
    ms = _mempool_stats(wallet_info)

    funded = cs.get("funded_txo_sum", 0) + ms.get("funded_txo_sum", 0)
    spent  = cs.get("spent_txo_sum",  0) + ms.get("spent_txo_sum",  0)

    return {
        "wallet":             address,
        "address_type":       detect_address_type(address),
        "balance_btc":        satoshi_to_btc(funded - spent),
        "total_received_btc": satoshi_to_btc(cs.get("funded_txo_sum", 0)),
        "total_sent_btc":     satoshi_to_btc(cs.get("spent_txo_sum",  0)),
        "confirmed_tx_count": cs.get("tx_count", 0),
        "mempool_tx_count":   ms.get("tx_count", 0),
        "utxo_count":         cs.get("funded_txo_count", 0) - cs.get("spent_txo_count", 0),
    }


# ── UTXO set ──────────────────────────────────────────────────────────────────

@app.get("/wallet/{address}/utxos")
def wallet_utxos(address: str):
    _require_valid_address(address)

    raw_utxos = get_wallet_utxos(address)

    enriched: list[dict] = []
    total_btc = 0.0
    for u in raw_utxos:
        value_btc = satoshi_to_btc(u.get("value", 0))
        total_btc += value_btc
        status = u.get("status", {})
        enriched.append({
            "txid":         u.get("txid"),
            "vout":         u.get("vout"),
            "value_btc":    value_btc,
            "confirmed":    status.get("confirmed", False),
            "block_height": status.get("block_height"),
        })

    enriched.sort(key=lambda x: -x["value_btc"])

    return {
        "wallet":     address,
        "utxo_count": len(enriched),
        "total_btc":  round(total_btc, 8),
        "utxos":      enriched,
    }


# ── Graph data ────────────────────────────────────────────────────────────────

@app.get("/wallet/{address}/graph")
def wallet_graph(
    address:   str,
    max_txs:   int = Query(default=100, ge=1,  le=250),
    max_nodes: int = Query(default=60,  ge=5,  le=150),
):
    _require_valid_address(address)

    transactions = get_wallet_transactions(address, max_txs=max_txs)
    parsed_txs   = parse_transactions(transactions, address)
    graph_data   = build_graph_data(address, parsed_txs, max_nodes=max_nodes)

    return {"wallet": address, **graph_data}


# ── Multi-hop network ─────────────────────────────────────────────────────────

@app.get("/wallet/{address}/hops")
def wallet_hops(
    address:   str,
    depth:     int = Query(default=2,  ge=1, le=3),
    max_nodes: int = Query(default=80, ge=10, le=150),
    max_txs:   int = Query(default=50, ge=1,  le=100),
):
    _require_valid_address(address)

    origin_txs    = get_wallet_transactions(address, max_txs=max_txs)
    parsed_origin = parse_transactions(origin_txs, address)
    all_parsed: dict[str, list[dict]] = {address: parsed_origin}

    # Depth-1: direct counterparties
    cp_set: set[str] = set()
    for tx in parsed_origin:
        for cp in tx.get("counterparties", []):
            a = cp.get("address", "")
            if a and validate_address(a):
                cp_set.add(a)

    for cp_addr in list(cp_set)[:20]:
        if cp_addr in all_parsed:
            continue
        all_parsed[cp_addr] = parse_transactions(
            get_wallet_transactions(cp_addr, max_txs=25), cp_addr
        )

    # Depth-2: neighbours of depth-1
    if depth >= 2:
        d2_candidates: set[str] = set()
        for addr, txs in list(all_parsed.items()):
            if addr == address:
                continue
            for tx in txs:
                for cp in tx.get("counterparties", []):
                    a = cp.get("address", "")
                    if a and a not in all_parsed and validate_address(a):
                        d2_candidates.add(a)

        for d2_addr in list(d2_candidates)[:15]:
            if d2_addr in all_parsed:
                continue
            all_parsed[d2_addr] = parse_transactions(
                get_wallet_transactions(d2_addr, max_txs=15), d2_addr
            )

    graph_data = build_multihop_graph(
        origin_address=address,
        all_parsed_txs=all_parsed,
        depth=depth,
        max_nodes=max_nodes,
    )

    return {"wallet": address, "depth": depth, **graph_data}


# ── Wallet comparison ─────────────────────────────────────────────────────────

@app.get("/compare")
def compare_wallets(
    a: str = Query(..., description="First wallet address"),
    b: str = Query(..., description="Second wallet address"),
):
    _require_valid_address(a)
    _require_valid_address(b)

    info_a = get_wallet_info(a)
    info_b = get_wallet_info(b)
    if not info_a:
        raise HTTPException(status_code=404, detail=f"Wallet A ({a}) not found.")
    if not info_b:
        raise HTTPException(status_code=404, detail=f"Wallet B ({b}) not found.")

    ptxs_a = parse_transactions(get_wallet_transactions(a, max_txs=75), a)
    ptxs_b = parse_transactions(get_wallet_transactions(b, max_txs=75), b)

    risk_a = calculate_risk_score(ptxs_a)
    risk_b = calculate_risk_score(ptxs_b)
    prof_a = build_wallet_profile(ptxs_a, a)
    prof_b = build_wallet_profile(ptxs_b, b)

    cp_a = {cp["address"] for tx in ptxs_a for cp in tx.get("counterparties", [])}
    cp_b = {cp["address"] for tx in ptxs_b for cp in tx.get("counterparties", [])}
    shared = list(cp_a & cp_b)

    def _card(addr, info, profile, risk):
        cs = _chain_stats(info)
        ms = _mempool_stats(info)
        funded = cs.get("funded_txo_sum", 0) + ms.get("funded_txo_sum", 0)
        spent  = cs.get("spent_txo_sum",  0) + ms.get("spent_txo_sum",  0)
        return {
            "address":          addr,
            "address_type":     detect_address_type(addr),
            "balance_btc":      satoshi_to_btc(funded - spent),
            "total_received":   satoshi_to_btc(cs.get("funded_txo_sum", 0)),
            "total_sent":       satoshi_to_btc(cs.get("spent_txo_sum",  0)),
            "tx_count":         cs.get("tx_count", 0) + ms.get("tx_count", 0),
            "first_seen":       profile.get("first_seen"),
            "last_seen":        profile.get("last_seen"),
            "velocity_per_day": profile.get("velocity_per_day"),
            "risk_score":       risk["score"],
            "risk_level":       risk["level"],
            "top_patterns":     profile.get("pattern_breakdown", {}),
        }

    return {
        "wallet_a":              _card(a, info_a, prof_a, risk_a),
        "wallet_b":              _card(b, info_b, prof_b, risk_b),
        "direct_link":           b in cp_a or a in cp_b,
        "shared_counterparties": shared[:20],
        "shared_count":          len(shared),
    }


# ─── Case management ──────────────────────────────────────────────────────────

@app.post("/case/create/{case_name}")
def create_new_case(case_name: str):
    """Create a new investigation case."""
    if load_case(case_name):
        raise HTTPException(status_code=409, detail=f"Case '{case_name}' already exists.")
    return create_case(case_name)


@app.get("/cases")
def get_all_cases():
    """List all saved investigation cases (name + created_at + wallet count)."""
    return {"cases": list_cases()}


@app.get("/case/{case_name}")
def get_case(case_name: str):
    """Load a full investigation case."""
    case = load_case(case_name)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_name}' not found.")
    return case


@app.post("/case/{case_name}/wallet/{wallet}")
def add_wallet(case_name: str, wallet: str):
    """Add a wallet address to an existing case."""
    _require_valid_address(wallet)
    success = add_wallet_to_case(case_name, wallet)
    if not success:
        raise HTTPException(status_code=404, detail=f"Case '{case_name}' not found.")
    return {"success": True, "wallet": wallet, "case": case_name}


@app.post("/case/{case_name}/note")
def add_note(case_name: str, note: str = Body(..., embed=True)):
    """Append a timestamped note to a case."""
    success = add_note_to_case(case_name, note)
    if not success:
        raise HTTPException(status_code=404, detail=f"Case '{case_name}' not found.")
    return {"success": True}


@app.delete("/case/{case_name}")
def remove_case(case_name: str):
    """Permanently delete a case file."""
    success = delete_case(case_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Case '{case_name}' not found.")
    return {"success": True, "deleted": case_name}
