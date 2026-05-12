from collections import Counter

# ── Known risk tags and their score contributions ─────────────────────────────
# Tags come from counterparty["tag"] set by the parser via wallet_tags.py
KNOWN_RISK_TAGS: dict[str, int] = {
    "Mixer":    40,
    "Scam":     50,
    "Darknet":  45,
    "Sanctioned": 50,
}

# Patterns that add score when repeated
SUSPICIOUS_PATTERNS: dict[str, int] = {
    "mixing":        30,
    "fan_out":       20,
    "peel_chain":    10,
    "consolidation": 10,
}

_MAX_RAW = 215


# ─── Factor functions — each returns (points: int, flag: dict | None) ─────────

def _f01_tx_volume(txs: list[dict]) -> tuple[int, dict | None]:
    n = len(txs)
    if n > 100:
        return 15, {"code": "F01", "severity": "high",
                    "label": "Very high transaction volume",
                    "detail": f"{n} transactions detected (threshold: >100)"}
    if n > 40:
        return 10, {"code": "F01", "severity": "medium",
                    "label": "High transaction volume",
                    "detail": f"{n} transactions detected (threshold: >40)"}
    if n > 20:
        return 5,  {"code": "F01", "severity": "low",
                    "label": "Elevated transaction count",
                    "detail": f"{n} transactions detected (threshold: >20)"}
    return 0, None


def _f02_outgoing_activity(txs: list[dict]) -> tuple[int, dict | None]:
    out_count = sum(1 for t in txs if t.get("direction") == "OUTGOING")
    if out_count > 50:
        return 15, {"code": "F02", "severity": "high",
                    "label": "Very high outgoing activity",
                    "detail": f"{out_count} outgoing transactions"}
    if out_count > 20:
        return 10, {"code": "F02", "severity": "medium",
                    "label": "High outgoing activity",
                    "detail": f"{out_count} outgoing transactions"}
    if out_count > 10:
        return 5,  {"code": "F02", "severity": "low",
                    "label": "Elevated outgoing activity",
                    "detail": f"{out_count} outgoing transactions"}
    return 0, None


def _f03_large_network(txs: list[dict]) -> tuple[int, dict | None]:
    unique: set[str] = set()
    for t in txs:
        unique.update(t.get("connected_wallets", []))
    n = len(unique)
    if n > 100:
        return 15, {"code": "F03", "severity": "high",
                    "label": "Massive counterparty network",
                    "detail": f"{n} unique wallets interacted with"}
    if n > 50:
        return 10, {"code": "F03", "severity": "medium",
                    "label": "Large counterparty network",
                    "detail": f"{n} unique wallets interacted with"}
    if n > 25:
        return 5,  {"code": "F03", "severity": "low",
                    "label": "Broad counterparty network",
                    "detail": f"{n} unique wallets interacted with"}
    return 0, None


def _f04_repeated_interactions(txs: list[dict]) -> tuple[int, dict | None]:
    counter: Counter = Counter()
    for t in txs:
        for w in t.get("connected_wallets", []):
            counter[w] += 1
    repeated = [(w, c) for w, c in counter.items() if c > 3]
    if not repeated:
        return 0, None
    top = sorted(repeated, key=lambda x: -x[1])[:3]
    detail = "; ".join(f"{w[:10]}… ×{c}" for w, c in top)
    sev = "high" if len(repeated) > 5 else "medium"
    return 10, {"code": "F04", "severity": sev,
                "label": "Repeated counterparty interactions",
                "detail": f"{len(repeated)} wallets seen >3× — {detail}"}


def _f05_mixing_patterns(txs: list[dict]) -> tuple[int, dict | None]:
    mixing_count = sum(1 for t in txs if t.get("pattern") == "mixing")
    pct = mixing_count / max(len(txs), 1) * 100
    if pct > 30 or mixing_count >= 5:
        return 20, {"code": "F05", "severity": "critical",
                    "label": "Possible CoinJoin / mixing activity",
                    "detail": f"{mixing_count} mixing-pattern transactions ({pct:.0f}% of total)"}
    if mixing_count >= 2:
        return 12, {"code": "F05", "severity": "high",
                    "label": "Suspected mixing transactions",
                    "detail": f"{mixing_count} mixing-pattern transactions detected"}
    return 0, None


def _f06_fan_out(txs: list[dict]) -> tuple[int, dict | None]:
    n = sum(1 for t in txs if t.get("pattern") == "fan_out")
    if n >= 3:
        return 10, {"code": "F06", "severity": "medium",
                    "label": "Repeated fan-out distribution",
                    "detail": f"{n} one-to-many disbursement transactions"}
    if n >= 1:
        return 5,  {"code": "F06", "severity": "low",
                    "label": "Fan-out transaction detected",
                    "detail": f"{n} one-to-many output transaction(s)"}
    return 0, None


def _f07_round_numbers(txs: list[dict]) -> tuple[int, dict | None]:
    round_count = 0
    for t in txs:
        btc = abs(t.get("net_btc", 0))
        if btc >= 0.001:
            scaled = btc * 1000
            if abs(scaled - round(scaled)) < 0.01:
                round_count += 1
    pct = round_count / max(len(txs), 1) * 100
    if pct > 50 and round_count >= 5:
        return 10, {"code": "F07", "severity": "medium",
                    "label": "High proportion of round-value transactions",
                    "detail": f"{round_count} transactions with round BTC amounts ({pct:.0f}%)"}
    if pct > 30 and round_count >= 3:
        return 5,  {"code": "F07", "severity": "low",
                    "label": "Several round-value transactions",
                    "detail": f"{round_count} transactions with round BTC amounts"}
    return 0, None


def _f08_velocity(txs: list[dict]) -> tuple[int, dict | None]:
    times = [t["block_time"] for t in txs if t.get("block_time")]
    if len(times) < 2:
        return 0, None
    span_days = max((max(times) - min(times)) / 86_400, 0.01)
    velocity = len(times) / span_days
    if velocity > 20:
        return 15, {"code": "F08", "severity": "high",
                    "label": "Very high transaction velocity",
                    "detail": f"{velocity:.1f} transactions/day"}
    if velocity > 8:
        return 10, {"code": "F08", "severity": "medium",
                    "label": "High transaction velocity",
                    "detail": f"{velocity:.1f} transactions/day"}
    if velocity > 3:
        return 5,  {"code": "F08", "severity": "low",
                    "label": "Elevated transaction velocity",
                    "detail": f"{velocity:.1f} transactions/day"}
    return 0, None


def _f09_dormancy_break(txs: list[dict]) -> tuple[int, dict | None]:
    times = sorted(t["block_time"] for t in txs if t.get("block_time"))
    if len(times) < 3:
        return 0, None
    max_gap_days = max((times[i] - times[i-1]) / 86_400 for i in range(1, len(times)))
    if max_gap_days > 365:
        return 15, {"code": "F09", "severity": "high",
                    "label": "Long dormancy break detected",
                    "detail": f"Wallet inactive for {max_gap_days:.0f} days before resuming"}
    if max_gap_days > 180:
        return 10, {"code": "F09", "severity": "medium",
                    "label": "Dormancy period detected",
                    "detail": f"Gap of {max_gap_days:.0f} days between transactions"}
    return 0, None


def _f10_large_transactions(txs: list[dict]) -> tuple[int, dict | None]:
    large = [t for t in txs if t.get("total_output_btc", 0) >= 1.0]
    if large:
        max_val = max(t["total_output_btc"] for t in large)
        return 10, {"code": "F10", "severity": "medium",
                    "label": "Large-value transactions present",
                    "detail": f"{len(large)} tx(s) ≥1 BTC; largest: {max_val:.4f} BTC"}
    return 0, None


def _f11_consolidation_bursts(txs: list[dict]) -> tuple[int, dict | None]:
    n = sum(1 for t in txs if t.get("pattern") == "consolidation")
    if n >= 3:
        return 10, {"code": "F11", "severity": "medium",
                    "label": "Multiple UTXO consolidations",
                    "detail": f"{n} consolidation transactions (many-in → few-out)"}
    return 0, None


def _f12_unconfirmed(txs: list[dict]) -> tuple[int, dict | None]:
    unconf = sum(1 for t in txs if not t.get("confirmed", True))
    if unconf >= 5:
        return 10, {"code": "F12", "severity": "medium",
                    "label": "Many unconfirmed transactions",
                    "detail": f"{unconf} transactions still in mempool"}
    if unconf >= 2:
        return 5,  {"code": "F12", "severity": "low",
                    "label": "Unconfirmed transactions present",
                    "detail": f"{unconf} mempool transaction(s)"}
    return 0, None


def _f13_risk_tags(txs: list[dict]) -> tuple[int, list[dict]]:
    """
    Scan counterparty tags. Each hit from KNOWN_RISK_TAGS adds to score
    and generates its own flag. Returns total pts and a list of flags.
    """
    seen_tags: Counter = Counter()
    for t in txs:
        for cp in t.get("counterparties", []):
            tag = cp.get("tag", "Unknown")
            if tag in KNOWN_RISK_TAGS:
                seen_tags[tag] += 1

    flags: list[dict] = []
    pts = 0
    for tag, count in seen_tags.items():
        tag_pts = min(KNOWN_RISK_TAGS[tag], 50)  # cap per tag
        pts += tag_pts
        flags.append({
            "code":     "F13",
            "severity": "critical",
            "label":    f"Interaction with {tag} wallet",
            "detail":   f"{count} transaction(s) involving a known {tag} address",
        })
    return pts, flags


def _f14_exchange_interactions(txs: list[dict]) -> tuple[int, dict | None]:
    exchange_hits = sum(
        1
        for t in txs
        for cp in t.get("counterparties", [])
        if cp.get("tag", "Unknown") not in ("Unknown",) + tuple(KNOWN_RISK_TAGS)
    )
    if exchange_hits >= 5:
        return 10, {"code": "F14", "severity": "low",
                    "label": "Frequent exchange interactions",
                    "detail": f"{exchange_hits} interactions with known exchange addresses"}
    return 0, None


# ─── Scalar factor list (all return single flag or None) ──────────────────────

_SCALAR_FACTORS = [
    _f01_tx_volume,
    _f02_outgoing_activity,
    _f03_large_network,
    _f04_repeated_interactions,
    _f05_mixing_patterns,
    _f06_fan_out,
    _f07_round_numbers,
    _f08_velocity,
    _f09_dormancy_break,
    _f10_large_transactions,
    _f11_consolidation_bursts,
    _f12_unconfirmed,
    _f14_exchange_interactions,
]


# ─── Main entry point ─────────────────────────────────────────────────────────

def calculate_risk_score(transactions: list[dict]) -> dict:
    """
    Run all risk factors and return a structured risk report.

    Returns:
        {
          score:   0–100,
          level:   "LOW" | "MEDIUM" | "HIGH",
          flags:   [ { code, severity, label, detail } ],
          reasons: [ str ]   ← legacy compatibility
          summary: str
        }
    """
    raw_score = 0
    flags: list[dict] = []

    # Scalar factors
    for factor_fn in _SCALAR_FACTORS:
        pts, flag = factor_fn(transactions)
        raw_score += pts
        if flag:
            flags.append(flag)

    # Tag-based factor (returns multiple flags)
    tag_pts, tag_flags = _f13_risk_tags(transactions)
    raw_score += tag_pts
    flags.extend(tag_flags)

    # Normalise to 0–100
    score = min(100, round(raw_score / _MAX_RAW * 100))

    if score >= 65:
        level = "HIGH"
    elif score >= 35:
        level = "MEDIUM"
    else:
        level = "LOW"

    # Sort flags: critical → high → medium → low
    _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    flags.sort(key=lambda f: _sev_order.get(f["severity"], 9))

    # Human-readable summary
    if not flags:
        summary = "No significant risk indicators detected. Wallet behaviour appears normal."
    elif level == "HIGH":
        summary = (
            f"{len(flags)} risk indicator(s) detected. "
            "This wallet exhibits patterns consistent with high-risk activity. "
            "Further investigation is strongly recommended."
        )
    elif level == "MEDIUM":
        summary = (
            f"{len(flags)} risk indicator(s) detected. "
            "This wallet shows unusual patterns that warrant closer review."
        )
    else:
        summary = (
            f"{len(flags)} minor indicator(s) noted. "
            "Overall activity appears low-risk."
        )

    return {
        "score":   score,
        "level":   level,
        "flags":   flags,
        "reasons": [f["label"] for f in flags],  # legacy compat
        "summary": summary,
    }
