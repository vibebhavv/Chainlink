from datetime import datetime
from collections import defaultdict
from backend.utils.wallet_tags import (
    KNOWN_EXCHANGES
)


# ─── Utilities ───────────────────────────────────────────────────────────────

def satoshi_to_btc(value: int) -> float:
    return round(value / 100_000_000, 8)


def format_timestamp(ts: int) -> str:
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─── Transaction pattern classifier ─────────────────────────────────────────

def _classify_pattern(
    n_inputs: int,
    n_outputs: int,
    wallet_is_input: bool,
    wallet_is_output: bool,
    unique_input_addrs: int,
    unique_output_addrs: int,
) -> str:
    """
    Heuristically classify the structural pattern of a transaction.
    """
    # Self-transfer: wallet is both sender and sole receiver
    if wallet_is_input and wallet_is_output and unique_output_addrs == 1:
        return "self_transfer"

    # Sweep: single input, single output (full UTXO drain)
    if n_inputs == 1 and n_outputs == 1:
        return "sweep"

    # Consolidation: many inputs collapsing into one/two outputs
    if n_inputs >= 4 and n_outputs <= 2:
        return "consolidation"

    # Fan-out: one/two inputs, many outputs (e.g. exchange payout)
    if n_inputs <= 2 and n_outputs >= 5:
        return "fan_out"

    # Mixing heuristic: many inputs AND many outputs with similar counts
    ratio = max(n_inputs, n_outputs) / max(min(n_inputs, n_outputs), 1)
    if n_inputs >= 3 and n_outputs >= 3 and ratio < 2.5:
        return "mixing"

    # Peel chain: one input, two outputs (classic payment + change)
    if n_inputs == 1 and n_outputs == 2:
        return "peel_chain"

    return "standard"


# ─── Main parser ─────────────────────────────────────────────────────────────

def parse_transactions(
    transactions: list[dict],
    wallet_address: str,
) -> list[dict]:
    """
    Parse raw Blockstream transaction objects into enriched dicts.
    """
    parsed = []

    for tx in transactions:
        txid       = tx.get("txid", "")
        fee_sats   = tx.get("fee", 0)
        status     = tx.get("status", {})
        block_time = status.get("block_time")
        confirmed  = status.get("confirmed", False)

        timestamp = format_timestamp(block_time) if block_time else "Unconfirmed"

        vin  = tx.get("vin", [])
        vout = tx.get("vout", [])

        # ── Flow calculation ──────────────────────────────────────────────
        incoming_sats = 0
        outgoing_sats = 0
        input_addrs:  set[str] = set()
        output_addrs: set[str] = set()

        for inp in vin:
            prevout = inp.get("prevout") or {}
            addr = prevout.get(
                "scriptpubkey_address"
            )
            value   = prevout.get("value", 0)
            if addr:
                input_addrs.add(addr)
            if addr == wallet_address:
                outgoing_sats += value

        for out in vout:
            addr  = out.get("scriptpubkey_address")
            value = out.get("value", 0)
            if addr:
                output_addrs.add(addr)
            if addr == wallet_address:
                incoming_sats += value

        incoming_btc = satoshi_to_btc(incoming_sats)
        outgoing_btc = satoshi_to_btc(outgoing_sats)
        fee_btc      = satoshi_to_btc(fee_sats)
        net_btc      = round(incoming_btc - outgoing_btc, 8)

        direction = "INCOMING" if net_btc >= 0 else "OUTGOING"

        # ── Counterparties ────────────────────────────────────────────────
        # Exclude the wallet itself from the counterparty list
        all_addrs = (input_addrs | output_addrs) - {wallet_address}

        # Build per-counterparty metadata
        counterparties: list[dict] = []
        for addr in all_addrs:
            sent_to   = addr in output_addrs and wallet_address in input_addrs
            recv_from = addr in input_addrs  and wallet_address in output_addrs

            # BTC amount flowing between wallet and this counterparty
            cp_value = 0.0
            if sent_to:
                for out in vout:
                    if out.get("scriptpubkey_address") == addr:
                        cp_value += satoshi_to_btc(out.get("value", 0))
            elif recv_from:
                for inp in vin:
                    po = inp.get("prevout") or {}
                    if po.get("scriptpubkey_address") == addr:
                        cp_value += satoshi_to_btc(po.get("value", 0))

            tag = KNOWN_EXCHANGES.get(
                addr,
                "Unknown"
            )

            counterparties.append({

                "address": addr,

                "direction":
                    "sent_to"
                    if sent_to
                    else "received_from",

                "btc":
                    round(cp_value, 8),

                "tag": tag
            })

        # ── Pattern classification ────────────────────────────────────────
        wallet_is_input  = wallet_address in input_addrs
        wallet_is_output = wallet_address in output_addrs

        pattern = _classify_pattern(
            n_inputs           = len(vin),
            n_outputs          = len(vout),
            wallet_is_input    = wallet_is_input,
            wallet_is_output   = wallet_is_output,
            unique_input_addrs = len(input_addrs),
            unique_output_addrs= len(output_addrs),
        )

        # ── Total tx volume (all outputs) ─────────────────────────────────
        total_output_sats = sum(o.get("value", 0) for o in vout)
        total_output_btc  = satoshi_to_btc(total_output_sats)

        parsed.append({
            "txid":              txid,
            "timestamp":         timestamp,
            "block_time":        block_time,
            "confirmed":         confirmed,
            "incoming_btc":      incoming_btc,
            "outgoing_btc":      outgoing_btc,
            "net_btc":           net_btc,
            "fee_btc":           fee_btc,
            "total_output_btc":  total_output_btc,
            "direction":         direction,
            "pattern":           pattern,
            "input_count":       len(vin),
            "output_count":      len(vout),
            "counterparties":    counterparties,
            # Legacy key kept for graph compatibility
            "connected_wallets": list(all_addrs),
        })

    return parsed


# ─── Aggregate helpers ────────────────────────────────────────────────────────

def build_wallet_profile(
    parsed_transactions: list[dict],
    wallet_address: str,
) -> dict:
    """
    Derive aggregate behavioural stats from parsed transactions.
    Used by the risk engine and summary endpoint.
    """
    if not parsed_transactions:
        return {}

    total_received = sum(
        t["incoming_btc"] for t in parsed_transactions
    )
    total_sent = sum(
        t["outgoing_btc"] for t in parsed_transactions
    )
    total_fees = sum(
        t["fee_btc"] for t in parsed_transactions
    )

    # Timestamps (only confirmed txs)
    times = [
        t["block_time"]
        for t in parsed_transactions
        if t.get("block_time")
    ]
    first_seen = format_timestamp(min(times)) if times else None
    last_seen  = format_timestamp(max(times)) if times else None

    # Pattern breakdown
    pattern_counts: dict[str, int] = defaultdict(int)
    for t in parsed_transactions:
        pattern_counts[t["pattern"]] += 1

    # Counterparty frequency map
    cp_freq: dict[str, int] = defaultdict(int)
    cp_vol:  dict[str, float] = defaultdict(float)
    for t in parsed_transactions:
        for cp in t["counterparties"]:
            cp_freq[cp["address"]] += 1
            cp_vol[cp["address"]]  += cp["btc"]

    top_counterparties = sorted(
        [
            {"address": a, "interactions": n, "volume_btc": round(cp_vol[a], 8)}
            for a, n in cp_freq.items()
        ],
        key=lambda x: x["interactions"],
        reverse=True,
    )[:10]

    outgoing_count = sum(
        1 for t in parsed_transactions if t["direction"] == "OUTGOING"
    )
    incoming_count = len(parsed_transactions) - outgoing_count

    # Velocity: txs per day across the observed window
    velocity_per_day = None
    if len(times) >= 2:
        span_days = (max(times) - min(times)) / 86_400
        if span_days > 0:
            velocity_per_day = round(len(times) / span_days, 2)

    # Average transaction size
    sizes = [t["total_output_btc"] for t in parsed_transactions]
    avg_tx_size = round(sum(sizes) / len(sizes), 8) if sizes else 0

    return {
        "total_received_btc":  round(total_received, 8),
        "total_sent_btc":      round(total_sent, 8),
        "total_fees_btc":      round(total_fees, 8),
        "first_seen":          first_seen,
        "last_seen":           last_seen,
        "incoming_count":      incoming_count,
        "outgoing_count":      outgoing_count,
        "pattern_breakdown":   dict(pattern_counts),
        "top_counterparties":  top_counterparties,
        "unique_counterparties": len(cp_freq),
        "velocity_per_day":    velocity_per_day,
        "avg_tx_size_btc":     avg_tx_size,
    }   
