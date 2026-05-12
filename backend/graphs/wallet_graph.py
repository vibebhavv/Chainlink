from __future__ import annotations

from collections import defaultdict

try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False


MAX_NODES_DEFAULT = 60

# ── Visual palette ────────────────────────────────────────────────────────────

_NODE_STYLES: dict[str, dict] = {
    "target": {
        "color": {"background": "#ef4444", "border": "#fca5a5",
                  "highlight": {"background": "#f87171", "border": "#fca5a5"}},
        "font":  {"size": 10, "color": "#ffffff", "face": "DM Mono"},
    },
    "exchange": {
        "color": {"background": "#1a2d10", "border": "#84cc16",
                  "highlight": {"background": "#2a4018", "border": "#a3e635"}},
        "font":  {"size": 9, "color": "#a3e635", "face": "DM Mono"},
    },
    "risk": {
        "color": {"background": "#2d1010", "border": "#f87171",
                  "highlight": {"background": "#3d1515", "border": "#fca5a5"}},
        "font":  {"size": 9, "color": "#fca5a5", "face": "DM Mono"},
    },
    "connected": {
        "color": {"background": "#0f2a3f", "border": "#38bdf8",
                  "highlight": {"background": "#1e3a52", "border": "#7dd3fc"}},
        "font":  {"size": 9, "color": "#94c8e0", "face": "DM Mono"},
    },
}

_RISK_TAGS = {"Mixer", "Scam", "Darknet", "Sanctioned"}


def _addr_short(addr: str) -> str:
    return addr[:6] + "…" + addr[-4:] if len(addr) > 12 else addr


def _node_group(addr: str, tag: str) -> str:
    if tag and tag != "Unknown":
        return "risk" if tag in _RISK_TAGS else "exchange"
    return "connected"


# ─── Core graph builder ───────────────────────────────────────────────────────

def build_graph_data(
    wallet_address: str,
    transactions: list[dict],
    max_nodes: int = MAX_NODES_DEFAULT,
) -> dict:
    """
    Build a directed weighted graph from parsed transactions.

    Returns { nodes, edges, stats } compatible with vis.js Network.
    """
    # edge_data[src][dst] = { tx_count, btc_volume, txids }
    edge_data: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"tx_count": 0, "btc_volume": 0.0, "txids": []})
    )

    node_freq: dict[str, int]   = defaultdict(int)
    node_vol:  dict[str, float] = defaultdict(float)
    node_tag:  dict[str, str]   = {}  # address → tag label

    node_freq[wallet_address] = 0  # always include target

    for tx in transactions:
        is_outgoing  = tx.get("direction") == "OUTGOING"
        counterparties = tx.get("counterparties", [])

        # Fallback: build minimal counterparty list from connected_wallets
        if not counterparties:
            for w in tx.get("connected_wallets", []):
                counterparties = [{"address": w, "direction": "received_from",
                                   "btc": 0.0, "tag": "Unknown"}]

        for cp in counterparties:
            addr   = cp.get("address", "")
            vol    = cp.get("btc", 0.0)
            cp_dir = cp.get("direction", "")
            tag    = cp.get("tag", "Unknown")

            if not addr or addr == wallet_address:
                continue

            node_freq[addr] += 1
            node_vol[addr]  += vol
            node_freq[wallet_address] += 1
            if tag and tag != "Unknown":
                node_tag[addr] = tag

            # ── Edge direction resolution ─────────────────────────────────
            # Prefer the counterparty-level direction; fall back to tx direction.
            if cp_dir == "sent_to":
                src, dst = wallet_address, addr
            elif cp_dir == "received_from":
                src, dst = addr, wallet_address
            elif is_outgoing:
                src, dst = wallet_address, addr
            else:
                src, dst = addr, wallet_address

            ek = edge_data[src][dst]
            ek["tx_count"]   += 1
            ek["btc_volume"] += vol
            ek["txids"].append(tx.get("txid", "")[:16])

    # ── Select top-N nodes ────────────────────────────────────────────────
    other_nodes = sorted(
        [(a, f) for a, f in node_freq.items() if a != wallet_address],
        key=lambda x: -x[1],
    )[: max_nodes - 1]

    allowed: set[str] = {wallet_address} | {a for a, _ in other_nodes}

    # ── Build node list ───────────────────────────────────────────────────
    nodes: list[dict] = []

    target_style = _NODE_STYLES["target"]
    nodes.append({
        "id":    wallet_address,
        "label": "TARGET\n" + _addr_short(wallet_address),
        "group": "target",
        "size":  48,
        "title": (
            f"<b>TARGET WALLET</b><br>{wallet_address}"
            f"<br>Interactions: {node_freq[wallet_address]}"
        ),
        "metadata": {
            "address":      wallet_address,
            "type":         "target",
            "interactions": node_freq[wallet_address],
            "volume_btc":   round(node_vol.get(wallet_address, 0), 8),
            "tag":          "Target",
        },
        **target_style,
    })

    max_freq = max((f for _, f in other_nodes), default=1)
    for addr, freq in other_nodes:
        size  = 14 + int(30 * freq / max(max_freq, 1))
        vol   = round(node_vol.get(addr, 0), 8)
        tag   = node_tag.get(addr, "Unknown")
        group = _node_group(addr, tag)
        style = _NODE_STYLES.get(group, _NODE_STYLES["connected"])

        tag_label = f"<br>Tag: <b>{tag}</b>" if tag != "Unknown" else ""

        nodes.append({
            "id":    addr,
            "label": _addr_short(addr),
            "group": group,
            "size":  size,
            "title": (
                f"<b>{_addr_short(addr)}</b><br>"
                f"{addr}<br>"
                f"Interactions: {freq}<br>"
                f"Volume: {vol} BTC"
                f"{tag_label}"
            ),
            "metadata": {
                "address":      addr,
                "type":         group,
                "interactions": freq,
                "volume_btc":   vol,
                "tag":          tag,
            },
            **style,
        })

    # ── Build edge list ───────────────────────────────────────────────────
    edges: list[dict] = []
    eid = 0
    for src, dsts in edge_data.items():
        if src not in allowed:
            continue
        for dst, meta in dsts.items():
            if dst not in allowed:
                continue
            vol   = round(meta["btc_volume"], 8)
            count = meta["tx_count"]
            width = max(1.5, min(1 + count * 0.8, 8))

            edges.append({
                "id":    eid,
                "from":  src,
                "to":    dst,
                "value": vol,
                "width": width,
                "label": f"{vol} BTC" if vol > 0 else f"×{count}",
                "title": (
                    f"<b>{_addr_short(src)} → {_addr_short(dst)}</b><br>"
                    f"Transactions: {count}<br>"
                    f"Volume: {vol} BTC"
                ),
                "arrows": "to",
                "color":  {"color": "#1e3a52", "highlight": "#38bdf8", "opacity": 0.85},
                "smooth": {"type": "dynamic"},
                "metadata": {
                    "tx_count":   count,
                    "btc_volume": vol,
                    "txids":      meta["txids"][:5],
                },
            })
            eid += 1

    stats = _compute_stats(wallet_address, nodes, edges)

    return {"nodes": nodes, "edges": edges, "stats": stats}


def _compute_stats(
    wallet_address: str,
    nodes: list[dict],
    edges: list[dict],
) -> dict:
    base = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "clusters":   None,
        "density":    None,
        "avg_degree": None,
        "hub_nodes":  [],
    }

    if not _NX_AVAILABLE or len(nodes) < 2:
        return base

    G = nx.DiGraph()
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        G.add_edge(e["from"], e["to"], weight=e.get("value", 1))

    base["density"]    = round(nx.density(G), 4)
    degrees            = dict(G.degree())
    base["avg_degree"] = round(sum(degrees.values()) / max(len(degrees), 1), 2)

    try:
        UG          = G.to_undirected()
        communities = list(nx.community.greedy_modularity_communities(UG))
        base["clusters"] = len(communities)

        addr_to_cluster = {
            addr: i
            for i, community in enumerate(communities)
            for addr in community
        }
        for node in nodes:
            node["cluster"] = addr_to_cluster.get(node["id"], 0)
    except Exception:
        base["clusters"] = 1

    in_degrees = dict(G.in_degree())
    base["hub_nodes"] = [
        {"address": a, "in_degree": d}
        for a, d in sorted(
            [(a, d) for a, d in in_degrees.items() if a != wallet_address],
            key=lambda x: -x[1],
        )[:3]
    ]

    return base


# ─── Multi-hop graph ──────────────────────────────────────────────────────────

def build_multihop_graph(
    origin_address: str,
    all_parsed_txs: dict[str, list[dict]],
    depth: int = 2,
    max_nodes: int = 80,
) -> dict:
    """Merge transactions from multiple hops and build a combined graph."""
    combined_txs: list[dict] = []
    for txs in all_parsed_txs.values():
        combined_txs.extend(txs)

    # Deduplicate by txid
    seen: set[str] = set()
    unique_txs: list[dict] = []
    for tx in combined_txs:
        if tx["txid"] not in seen:
            seen.add(tx["txid"])
            unique_txs.append(tx)

    graph_data = build_graph_data(origin_address, unique_txs, max_nodes=max_nodes)
    graph_data["multihop_depth"]     = depth
    graph_data["addresses_fetched"]  = list(all_parsed_txs.keys())

    return graph_data
