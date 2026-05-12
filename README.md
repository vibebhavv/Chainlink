# ⬡ Chainlink — Bitcoin Wallet OSINT Tool

> Open-source Bitcoin wallet intelligence platform. Analyze addresses, visualize transaction networks, score risk, and manage investigations — all from a self-hosted interface with no API keys required.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat&logo=fastapi&logoColor=white)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat)

---

## What is Chainlink?

Chainlink is a self-hosted OSINT (Open Source Intelligence) tool for investigating Bitcoin wallet addresses. Enter any BTC address and get a full picture: balance, transaction history, behavioural profile, a 14-factor risk score, an interactive network graph, and a case management system to track ongoing investigations.

It talks directly to the [Blockstream.info](https://blockstream.info) public API — no account, no API key, no data sent to third parties.

---

## Features

### Wallet Analysis
- **Balance & flow stats** — current balance, total received, total sent (on-chain + mempool)
- **Address type detection** — P2PKH (Legacy), P2SH, P2WPKH (SegWit), P2TR (Taproot)
- **Full transaction history** — auto-paginates past Blockstream's 25-tx cap, up to 250 txs
- **UTXO set** — all unspent outputs with confirmation status and block height
- **Behavioural profile** — first/last seen, tx velocity (tx/day), average transaction size, fee total

### Transaction Pattern Classification
Every transaction is classified into one of seven structural patterns:

| Pattern | Description |
|---|---|
| `standard` | Normal payment with multiple inputs/outputs |
| `peel_chain` | One input → two outputs (payment + change address) |
| `fan_out` | Few inputs → many outputs (exchange payout, salary batch) |
| `consolidation` | Many inputs → one or two outputs (UTXO merge) |
| `mixing` | Symmetric many-to-many input/output structure (CoinJoin) |
| `self_transfer` | Wallet sends to itself only (internal reorganisation) |
| `sweep` | Single input → single output (full UTXO drain) |

### Risk Engine
A 14-factor weighted scoring engine produces a normalised 0–100 risk score with severity-labelled flags and a plain-English summary.

| Code | Factor | Max Score |
|---|---|---|
| F01 | High transaction volume | 15 |
| F02 | High outgoing activity | 15 |
| F03 | Large counterparty network | 15 |
| F04 | Repeated wallet interactions | 10 |
| F05 | Mixing / CoinJoin patterns | 20 |
| F06 | Fan-out distribution | 10 |
| F07 | Round-number transactions | 10 |
| F08 | High velocity (tx/day) | 15 |
| F09 | Dormancy break | 15 |
| F10 | Large single transactions | 10 |
| F11 | Consolidation bursts | 10 |
| F12 | Unconfirmed transaction cluster | 10 |
| F13 | Known-risk tag interaction (Mixer / Scam / Darknet / Sanctioned) | 50 |
| F14 | Frequent exchange interactions | 10 |

Risk levels: **LOW** < 35 · **MEDIUM** 35–64 · **HIGH** ≥ 65

### Network Graph
- **Directed weighted graph** — edges show BTC flow direction and volume
- **Node types** — colour-coded: Target (red), Connected (blue), Exchange (green), Risk (red-tinted)
- **Node sizing** — proportional to interaction frequency
- **Community detection** — clusters via NetworkX greedy modularity
- **Graph statistics** — node count, edge count, density, average degree, cluster count
- **Multi-hop traversal** — expand up to 3 hops deep (counterparties of counterparties)
- **Fullscreen mode** — native browser fullscreen API
- **In-graph controls** — zoom, fit-all, physics toggle, address search, node info panel
- Click any node to inspect it; double-click to pivot and analyze that wallet

### Wallet Comparison
Compare two addresses side-by-side to identify:
- Direct transaction links between the two wallets
- Shared counterparties (addresses both wallets interacted with)
- Risk score and activity profile for each

### Case Management
Persist investigations across sessions:
- Create named cases (stored as JSON files under `database/cases/`)
- Add wallet addresses to a case
- Append timestamped notes
- List, load, and delete cases via API

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | [FastAPI](https://fastapi.tiangolo.com) |
| Blockchain data | [Blockstream.info API](https://github.com/Blockstream/esplora/blob/master/API.md) |
| Graph analysis | [NetworkX](https://networkx.org) |
| Graph rendering | [vis.js Network](https://visjs.github.io/vis-network/docs/network/) |
| Frontend | Vanilla HTML/CSS/JS (zero build step) |
| Persistence | JSON flat-files |

---

## Project Structure

```
chainlink/
├── backend/
│   ├── app.py                  # FastAPI application & all route definitions
│   ├── services/
│   │   └── btc_service.py      # Blockstream API client, pagination, TTL cache
│   ├── utils/
│   │   ├── parser.py           # Transaction parsing & pattern classification
│   │   ├── risk_engine.py      # 14-factor risk scoring engine
│   │   ├── case_manager.py     # Investigation case CRUD
│   │   └── wallet_tags.py      # Known exchange & risk address registry
│   └── graphs/
│       └── wallet_graph.py     # vis.js graph builder, multi-hop, NetworkX stats
├── frontend/
│   └── index.html              # Single-page app (no build required)
├── database/
│   └── cases/                  # Auto-created. One JSON file per case.
└── README.md
```

---

## Installation

### Requirements
- Python 3.11+
- pip

### 1. Clone the repo

```bash
git clone https://github.com/your-username/chainlink.git
cd chainlink
```

### 2. Install dependencies

```bash
pip install fastapi uvicorn requests networkx
```

Or with a requirements file:

```bash
pip install -r requirements.txt
```

<details>
<summary><code>requirements.txt</code></summary>

```
fastapi>=0.110.0
uvicorn>=0.29.0
requests>=2.31.0
networkx>=3.3
```

</details>

### 3. Start the app

```bash
pythonx launch.py
```

The API will be available at `http://127.0.0.1:8000`.  
Interactive docs: `http://127.0.0.1:8000/docs`

### 4. Open the frontend

Open `frontend/index.html` directly in your browser — no web server needed.

> If you prefer to serve it: `python -m http.server 3000 --directory frontend`

---

## API Reference

All endpoints return JSON. No authentication required.

### Wallet

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/wallet/{address}` | Full analysis — balance, transactions, profile, risk score |
| `GET` | `/wallet/{address}/summary` | Lightweight stats only (no tx parsing) |
| `GET` | `/wallet/{address}/utxos` | All unspent outputs |
| `GET` | `/wallet/{address}/graph` | vis.js-ready graph JSON |
| `GET` | `/wallet/{address}/hops` | Multi-hop network graph |
| `GET` | `/compare?a={addr}&b={addr}` | Side-by-side wallet comparison |

**Query parameters for `/wallet/{address}`**

| Param | Default | Range | Description |
|---|---|---|---|
| `max_txs` | `100` | 1–250 | Maximum transactions to fetch |

**Query parameters for `/wallet/{address}/hops`**

| Param | Default | Range | Description |
|---|---|---|---|
| `depth` | `2` | 1–3 | How many hops to expand |
| `max_nodes` | `80` | 10–150 | Max graph nodes to return |
| `max_txs` | `50` | 1–100 | Transactions per address |

### Cases

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/case/create/{name}` | Create a new investigation case |
| `GET` | `/cases` | List all cases (summary) |
| `GET` | `/case/{name}` | Load full case data |
| `POST` | `/case/{name}/wallet/{address}` | Add a wallet to a case |
| `POST` | `/case/{name}/note` | Add a timestamped note (`{ "note": "..." }`) |
| `DELETE` | `/case/{name}` | Permanently delete a case |

### System

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API banner and endpoint list |
| `GET` | `/health` | Liveness check |

---

## Example Response

```bash
curl http://127.0.0.1:8000/wallet/bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh
```

```json
{
  "wallet": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
  "address_type": "P2WPKH (SegWit)",
  "balance_btc": 0.00412300,
  "total_received_btc": 1.58200000,
  "total_sent_btc": 1.57787700,
  "transaction_count": 47,
  "profile": {
    "first_seen": "2021-03-14 09:22:11 UTC",
    "last_seen":  "2024-11-02 17:04:38 UTC",
    "velocity_per_day": 0.04,
    "unique_counterparties": 31,
    "pattern_breakdown": { "peel_chain": 22, "standard": 18, "fan_out": 7 }
  },
  "risk_analysis": {
    "score": 28,
    "level": "LOW",
    "flags": [],
    "summary": "No significant risk indicators detected. Wallet behaviour appears normal."
  }
}
```

---

## Configuration

### Extending the known-address registry

Edit `backend/utils/wallet_tags.py` to add exchange or risk addresses:

```python
KNOWN_EXCHANGES = {
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf Na": "Binance",
    # add more...
}
```

The risk engine also recognises these tag values for automatic score escalation:

```python
KNOWN_RISK_TAGS = {
    "Mixer":      40,
    "Scam":       50,
    "Darknet":    45,
    "Sanctioned": 50,
}
```

Any counterparty tagged with one of these will trigger a **F13** flag.

### Cache TTL

The in-memory API response cache defaults to 120 seconds. Change it in `btc_service.py`:

```python
CACHE_TTL = 120  # seconds
```

### Transaction fetch limit

The default of 100 transactions per lookup can be adjusted per-request via `?max_txs=` (max 250), or you can change the default in `app.py`.

---

## How the Graph Works

The network graph maps the flow of funds between the target wallet and its counterparties.

```
TARGET (red)
  │── sent 0.5 BTC ──▶  bc1qabc… (blue, sized by frequency)
  │── sent 1.2 BTC ──▶  Binance hot wallet (green, exchange tag)
  ◀── recv 2.0 BTC ──   3FZbgi… (blue)
```

**Depth modes:**

- **Depth 1** — only direct counterparties of the target wallet (fast)
- **Depth 2** — counterparties of counterparties (fetches up to 20 extra wallets)
- **Depth 3** — third-order connections (fetches up to 35 extra wallets, slower)

**Community detection** uses NetworkX's greedy modularity algorithm on the undirected projection of the graph. Each cluster gets an ID; nodes are shaded accordingly.

---

## Data Sources & Privacy

Chainlink fetches data from **[Blockstream.info](https://blockstream.info)**, a public Bitcoin block explorer. This means:

- All data is already publicly visible on-chain — this tool does not expose anything that isn't already public
- No account or API key is required
- Your query addresses are sent to Blockstream's servers as part of normal HTTP requests — run behind a VPN or Tor if you require query privacy
- No data is stored remotely; cases are saved locally in `database/cases/`

---

## Limitations

- **Bitcoin only** — the current data layer is built against the Blockstream Esplora API. Multi-chain support (ETH, LTC etc.) is planned but not yet implemented.
- **Rate limits** — Blockstream applies soft rate limits on their public API. Multi-hop graph requests (depth 2–3) make many sequential requests and may be throttled on very active wallets.
- **Heuristics, not proof** — pattern classification and risk scoring are statistical heuristics. A HIGH risk score does not prove illicit activity; a LOW score does not guarantee a clean wallet. Use findings as investigative leads, not conclusions.
- **Transaction pagination cap** — a maximum of 250 transactions per wallet can be fetched in a single request. Wallets with thousands of transactions will be partially analysed.

---

## Roadmap

- [ ] Multi-chain support (Ethereum via Blockscout, Litecoin via LitecoinSpace)
- [ ] Graph fullscreen / open-in-new-tab mode
- [ ] Export case to PDF report
- [ ] Sanctions list integration (OFAC SDN)
- [ ] Tor/proxy support for query privacy
- [ ] Docker deployment
- [ ] Persistent graph layouts (save node positions)
- [ ] CSV export for transactions

---

## Contributing

Contributions are welcome. To get started:

```bash
git clone https://github.com/your-username/chainlink.git
cd chainlink
git checkout -b feature/your-feature-name
```

Please keep pull requests focused on a single change. If you're adding a new risk factor, add it as a self-contained function following the `_fXX_name(txs) → (int, dict | None)` pattern in `risk_engine.py`.

---

## Disclaimer

This tool is intended for **legal, ethical, and educational use only** — blockchain analytics, fraud investigation, compliance research, and personal wallet auditing.

Do not use Chainlink to:
- Facilitate financial crime, money laundering, or sanctions evasion
- Harass or stalk individuals
- Violate applicable laws in your jurisdiction

The authors accept no liability for misuse. All on-chain data analysed by this tool is already publicly visible on the Bitcoin blockchain.

<div align="center">
  <sub>Built with FastAPI · vis.js · Blockstream API · NetworkX</sub>
</div>
