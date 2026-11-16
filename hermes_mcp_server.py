"""
Hermes-Sol: Model Context Protocol (MCP) Server Interface
==========================================================
Enables Steve Capital (OOBE Protocol), MultiHopper, and Ace Data Cloud
autonomous orchestrators to inspect vault metrics and trigger rebalancing
actions via standardized JSON-RPC Model Context Protocol.

Compatible with Solana Agentic Protocol (SAP) & Steve Arena.
Author: Apoorv A S (@apoorv_xs)
"""

import asyncio
import json
import sys
import logging
from typing import Any, Dict

# Pure state & evaluation functions from agent_core
from agent_core import (
    VaultState,
    compute_target_weights,
    build_reasoning_hash,
    fetch_pyth_prices,
    get_jupiter_quote,
    USDC_MINT,
    SOL_MINT,
    JUP_MINT,
    DRY_RUN
)
import httpx

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger("hermes-mcp")

# Standard Mock / Live Vault State
_vault = VaultState(
    sol_balance=2.5,
    jup_balance=150.0,
    usdc_balance=400.0,
    peak_usd_value=615.0,
    tick=1
)


async def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute MCP tool calls."""
    async with httpx.AsyncClient(timeout=8.0) as session:
        if name == "get_vault_state":
            prices = await fetch_pyth_prices(session)
            sol_px = prices.get("SOL", 70.0)
            jup_px = prices.get("JUP", 0.25)
            total = _vault.total_usd(sol_px, jup_px)
            dd = _vault.drawdown(sol_px, jup_px)
            return {
                "tick": _vault.tick,
                "balances": {
                    "USDC": _vault.usdc_balance,
                    "SOL": _vault.sol_balance,
                    "JUP": _vault.jup_balance
                },
                "total_usd": round(total, 2),
                "peak_usd": round(_vault.peak_usd_value, 2),
                "drawdown_pct": round(dd * 100, 2),
                "mode": "DRY_RUN" if DRY_RUN else "LIVE"
            }

        elif name == "get_oracle_prices":
            prices = await fetch_pyth_prices(session)
            return {
                "prices": prices,
                "source": prices.get("SOURCE", "Pyth Hermes Pull Oracle"),
                "status": "HEALTHY"
            }

        elif name == "evaluate_rebalance":
            prices = await fetch_pyth_prices(session)
            targets = compute_target_weights(_vault, prices)
            reasoning_hash = build_reasoning_hash(_vault, prices, targets)
            return {
                "target_weights": targets,
                "reasoning_hash": reasoning_hash,
                "memo_instruction": f"MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr:{reasoning_hash[:32]}"
            }

        elif name == "get_steve_arena_status":
            return {
                "protocol": "OOBE Protocol / Steve Capital",
                "arena": "Steve Arena Leaderboard",
                "agent_name": "Hermes-Sol",
                "sap_mcp_compatible": True,
                "features": [
                    "Pyth Hermes sub-400ms pull oracle",
                    "Jupiter v6 optimal split-routing",
                    "3% drawdown safe harbor circuit breaker",
                    "Solana Memo Program cryptographic reasoning audit"
                ]
            }

        else:
            raise ValueError(f"Unknown tool: {name}")


async def main():
    """Simple JSON-RPC stdin/stdout loop for MCP clients."""
    log.info("Hermes-Sol MCP Server listening (SAP/OOBE Protocol bridge)...")
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            req = json.loads(line.decode().strip())
            req_id = req.get("id")
            tool_name = req.get("params", {}).get("name", "")
            args = req.get("params", {}).get("arguments", {})

            result = await handle_tool_call(tool_name, args)
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "error": str(e)}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
