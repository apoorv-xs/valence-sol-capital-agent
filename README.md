# Argon-Sol: Autonomous Capital Agent on Solana

> **Author:** Apoorv A S (@apoorv_xs) | IT & Software Systems Consulting  
> **Challenge:** Superteam Earn — "Steve Capital Agent Challenge" by OOBE Protocol ($500 USDC)  
> **Ecosystem Integration:** Steve Capital (@SteveCapitalOS) & OOBE Protocol (@OOBEonSol) | SAP MCP Standard

---

## What It Does

**Argon-Sol** is an enterprise-grade autonomous capital allocation agent built for **Steve Capital** and powered by **OOBE Protocol** on Solana mainnet:

1. **Reads live prices** from the Pyth pull oracle (Hermes endpoint, <50ms latency) with confidence interval validation and Coinbase/CoinGecko failover
2. **Computes momentum signals** from a 60-sample zero-allocation `numpy.float64` ring buffer
3. **Derives target portfolio weights** using a momentum-driven allocation model with circuit breakers
4. **Rebalances the vault** autonomously via Jupiter V6 DEX swaps when any asset deviates >5% from target
5. **Embeds reasoning hash** in every swap via the Solana Memo Program (cryptographic on-chain audit trail verified on Steve Arena)
6. **Logs all events** to a SQLite WAL ledger (`solana_capital_state.db`)
7. **Runs dry by default** — judges can verify the full reasoning pipeline in 1 second without funding a wallet
8. **Exposes MCP Server** — provides standard Model Context Protocol (SAP) interface for OOBE Protocol, MultiHopper, and Ace Data Cloud

**Zero GC pressure in hot path:** Pre-allocated `numpy.float64` ring buffers. Single persistent `httpx.AsyncClient` with keep-alive connection pooling. Fully compatible with Steve Capital's programmable guardrail framework.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    ARGON-SOL CAPITAL AGENT                     │
│                                                                 │
│  ┌──────────────────────┐    ┌──────────────────────────────┐  │
│  │   Pyth Hermes Oracle │    │   Momentum Engine            │  │
│  │   REST pull (<50ms)  │───▶│   (60-sample float64 ring    │  │
│  │   SOL/USD + JUP/USD  │    │    buffer, zero-alloc)       │  │
│  │   + confidence %     │    └──────────────┬───────────────┘  │
│  └──────────────────────┘                   │                  │
│                                             ▼                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │   Circuit Breakers                                       │  │
│  │   • Pyth confidence > 0.5% → 100% USDC safe harbor      │  │
│  │   • Portfolio drawdown > 3% → 100% USDC safe harbor      │  │
│  │   • Target weight deviation < 5% → no action            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │   Jupiter V6 DEX Routing                                 │  │
│  │   USDC ↔ SOL  |  USDC ↔ JUP  |  slippage ≤ 0.5%        │  │
│  │   + Jito MEV Bundle (sandwich protection)                │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │   On-Chain Audit Trail (Solana Memo Program)             │  │
│  │   SHA-256(tick + prices + balances + targets + momentum) │  │
│  │   Embedded in every swap tx → verified on Steve Arena    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────▼──────────────────────────────┐  │
│  │   SQLite WAL Ledger (solana_capital_state.db)            │  │
│  │   oracle_ticks | rebalance_events | tx signatures        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────▼──────────────────────────────┐  │
│  │   Model Context Protocol (MCP) Server                    │  │
│  │   JSON-RPC toolset for OOBE / Steve Arena / SAP          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## OOBE Protocol & Steve Arena Integration

Argon-Sol is engineered to natively interface with **Steve Capital (OOBE Protocol)** and the **Solana Agentic Protocol (SAP)**:

- **Model Context Protocol (MCP) Server (`argon_mcp_server.py`)**: Exposes structured JSON-RPC tools (`get_vault_state`, `get_oracle_prices`, `evaluate_rebalance`, `get_steve_arena_status`) so external AI agents, Steve Arena coordinators, MultiHopper routers, and Ace Data Cloud can orchestrate Argon-Sol programmatically.
- **Steve Arena On-Chain Verification**: Every live rebalance transaction embeds the SHA-256 decision hash into the Solana Memo Program (`MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`), creating an immutable cryptographic audit record registered directly on Steve Arena.

```bash
# Launch Argon-Sol MCP Server (SAP bridge for OOBE / Steve Capital)
python argon_mcp_server.py
```

---

## Circuit Breakers

| Condition | Action |
|-----------|--------|
| Pyth confidence interval > 0.5% | Safe harbor (rebalance 100% to USDC) |
| Portfolio drawdown > 3.0% | Liquidate to 100% USDC immediately |
| Swap slippage quote > 50 bps | Reject swap entirely |
| Swap USD delta < $10 | Skip (dust prevention) |

---

## Quickstart (Zero-Friction 1-Command Verification)

```bash
# 1. Clone
git clone https://github.com/apoorv-xs/argon-sol-capital-agent
cd argon-sol-capital-agent

# 2. Install lightweight requirements (zero solana compilation required for dry-run/testing)
pip install httpx numpy

# 3. Run automated unit test suite (10 tests, 0.003s execution)
python test_suite.py

# 4. Run judge verification (3 ticks with live oracle & Jupiter routing)
python agent_core.py --ticks 3

# 5. Live mode (requires wallet + solana packages + explicit risk acknowledgement)
pip install solana solders python-dotenv
cp .env.example .env
# → Set AGENT_KEYPAIR_B58 in .env
python agent_core.py --live --confirm-live-risk
```

**For Judges:** `python agent_core.py --ticks 3` runs the full autonomous sense-evaluate-guard-execute loop with real Pyth/Coinbase prices and live Jupiter v6 quote routing, displaying a high-contrast terminal dashboard and logging reasoning hashes. No private key or Solana wallet setup required.

---

## Live Demo Dashboard

```
╔══════════════════════════════════════════════════════════════╗
║          ARGON-SOL // AUTONOMOUS CAPITAL AGENT  [DRY-RUN]  ║
╠══════════════════════════════════════════════════════════════╣
║  Tick #42     Vault Total:   $1,034.52   DD:  0.00%         ║
╠══════════════════════════════════════════════════════════════╣
║  PYTH ORACLE                                                 ║
║   SOL/USD  $   218.4512  ±  0.037%  conf                    ║
║   JUP/USD  $     1.0842  ±  0.112%  conf                    ║
╠══════════════════════════════════════════════════════════════╣
║  PORTFOLIO STATE                                             ║
║   USDC  $  400.00  ( 38.7% current →  40.0% target)         ║
║   SOL      2.5000  ( 52.8% current →  40.0% target)         ║
║   JUP    150.00  (  15.7% current →  20.0% target)          ║
╠══════════════════════════════════════════════════════════════╣
║  MOMENTUM                                                    ║
║   SOL    +1.247%   JUP    +2.891%                            ║
╚══════════════════════════════════════════════════════════════╝
```

---

## State Ledger Schema

All state is recorded to SQLite WAL (`solana_capital_state.db`):

- `oracle_ticks`: timestamp, sol_price, sol_conf, jup_price, jup_conf
- `rebalance_events`: tick, asset, direction, usd_amount, slippage_bps, tx_signature, reasoning_hash, is_dry_run

Query the ledger:
```bash
sqlite3 solana_capital_state.db "SELECT * FROM rebalance_events ORDER BY id DESC LIMIT 5;"
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_KEYPAIR_B58` | — | Solana wallet base58 private key (live mode only) |
| `SOLANA_RPC` | `https://api.mainnet-beta.solana.com` | Solana RPC endpoint |

---

## Security

- Private keys loaded only from environment variables — never logged or printed
- **Dry-run default:** no on-chain transactions without `--live --confirm-live-risk`
- Slippage hard cap: 50 bps
- Minimum swap: $10 USDC
- Circuit breakers: Pyth confidence + max drawdown
- Jito MEV bundle protection on live swaps

---

## On-Chain Audit Trail

Every rebalance transaction includes a **Solana Memo Program** instruction with the SHA-256 hash of:
```json
{
  "tick": 42,
  "timestamp": "2026-11-16T12:30:00Z",
  "prices": {"SOL": 218.45, "JUP": 1.08},
  "balances": {"USDC": 400.0, "SOL": 2.5, "JUP": 150.0},
  "targets": {"USDC": 0.40, "SOL": 0.40, "JUP": 0.20},
  "sol_momentum": 0.01247,
  "jup_momentum": 0.02891
}
```

Verifiable on Solscan: `https://solscan.io/tx/<signature>`

*(In `--dry-run` mode, on-chain broadcast is safely bypassed while the full route calculation, simulation receipt, and SHA-256 reasoning memo are verified locally. For live on-chain execution, pass `--live --confirm-live-risk` with your wallet loaded in `.env` to emit live mainnet transactions).*

---

## Roadmap & Ecosystem Grant Pitch

Argon-Sol was built with an extensible plugin architecture. The next milestone expands this core into:

- **Jupiter Perps hedging** — autonomous delta-neutral position management
- **Kamino / Meteora yield harvesting** — multi-protocol liquidity optimization
- **Multi-agent vault coordination** — DAO treasury management with on-chain governance hooks
- **Pyth WebSocket push** — upgrade from REST polling to sub-40ms push oracle stream

> I am actively seeking **Solana Foundation / Superteam ecosystem grants** ($10,000–$25,000) to deploy multi-agent vault coordination infrastructure for Solana DAOs.  
> Interested? Reach out: **@apoorv_xs** on X

---

## USDC Settlement Address

`TBD — Apoorv A S (@apoorv_xs)`
