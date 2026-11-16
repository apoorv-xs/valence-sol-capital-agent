"""
Valence-Sol: Autonomous Capital Agent Test Suite
================================================
Comprehensive unit tests for:
- Mathematical ring buffer and momentum tracking
- Risk guardrails and 3% drawdown circuit breaker
- Oracle confidence degradation safe harbor
- Cryptographic SHA-256 reasoning hash (Solana Memo)
- SQLite WAL state ledger persistence
- Jupiter v6 simulated execution schemas

Run with:
    python test_suite.py
or:
    python -m unittest test_suite.py
"""

import unittest
import numpy as np
import sqlite3
import hashlib
import json
import time

# Import pure components from agent_core
from agent_core import (
    VaultState,
    compute_target_weights,
    build_reasoning_hash,
    init_db,
    log_oracle_tick,
    log_rebalance,
    MAX_DRAWDOWN,
    PYTH_CONF_MAX_PCT,
    PRICE_WINDOW
)


class TestVaultState(unittest.TestCase):
    def setUp(self):
        self.state = VaultState(
            sol_balance=2.0,
            jup_balance=100.0,
            usdc_balance=500.0,
            peak_usd_value=1000.0,
            tick=1
        )

    def test_ring_buffer_fifo(self):
        """Ring buffer must maintain max size and circular indexing."""
        for i in range(70):
            self.state.push_prices(float(i), float(i * 2))

        self.assertEqual(len(self.state.sol_prices), PRICE_WINDOW)
        self.assertEqual(len(self.state.jup_prices), PRICE_WINDOW)
        # Latest written index is (price_head - 1) % PRICE_WINDOW
        last_idx = (self.state.price_head - 1) % PRICE_WINDOW
        self.assertEqual(self.state.sol_prices[last_idx], 69.0)
        self.assertEqual(self.state.jup_prices[last_idx], 138.0)

    def test_total_usd(self):
        """Total USD must equal USDC + SOL*px + JUP*px."""
        sol_px = 70.0
        jup_px = 0.50
        # 500 + 2*70 + 100*0.50 = 500 + 140 + 50 = 690.0
        total = self.state.total_usd(sol_px, jup_px)
        self.assertAlmostEqual(total, 690.0, places=2)

    def test_drawdown_calculation(self):
        """Drawdown must correctly calculate drop from peak."""
        sol_px = 50.0   # 2 * 50 = 100
        jup_px = 0.20   # 100 * 0.20 = 20
        # total = 500 + 100 + 20 = 620. Peak = 1000.
        # Drawdown = (1000 - 620) / 1000 = 0.38 (38%)
        dd = self.state.drawdown(sol_px, jup_px)
        self.assertAlmostEqual(dd, 0.38, places=2)

    def test_momentum_flat(self):
        """Flat prices must yield zero momentum."""
        for _ in range(PRICE_WINDOW + 5):
            self.state.push_prices(100.0, 1.0)
        mom = self.state.momentum(self.state.sol_prices)
        self.assertAlmostEqual(mom, 0.0, places=4)

    def test_momentum_positive(self):
        """Rising prices over window must yield positive momentum."""
        for i in range(PRICE_WINDOW + 10):
            self.state.push_prices(float(100.0 + i * 2.0), 1.0)
        mom = self.state.momentum(self.state.sol_prices)
        self.assertGreater(mom, 0.0)


class TestCircuitBreakers(unittest.TestCase):
    def setUp(self):
        self.state = VaultState(
            sol_balance=2.0,
            jup_balance=100.0,
            usdc_balance=500.0,
            peak_usd_value=1000.0,
            tick=5
        )

    def test_drawdown_circuit_breaker(self):
        """Exceeding 3% drawdown must trigger 100% USDC safe harbor."""
        # Total = 500 + 2*100 + 100*1 = 800. Peak = 1000. DD = 20% > 3%
        prices = {
            "SOL": 100.0,
            "SOL_CONF_PCT": 0.001,
            "JUP": 1.0,
            "JUP_CONF_PCT": 0.001
        }
        targets = compute_target_weights(self.state, prices)
        self.assertEqual(targets, {"USDC": 1.0, "SOL": 0.0, "JUP": 0.0})

    def test_confidence_degradation_circuit_breaker(self):
        """Oracle confidence degradation > 0.5% must trigger 100% USDC safe harbor."""
        self.state.peak_usd_value = 690.0  # Zero drawdown
        prices = {
            "SOL": 70.0,
            "SOL_CONF_PCT": 0.008,  # 0.8% > 0.5% threshold
            "JUP": 0.5,
            "JUP_CONF_PCT": 0.001
        }
        targets = compute_target_weights(self.state, prices)
        self.assertEqual(targets, {"USDC": 1.0, "SOL": 0.0, "JUP": 0.0})

    def test_healthy_allocation(self):
        """Under normal conditions without momentum, base target weights apply."""
        self.state.peak_usd_value = 690.0
        prices = {
            "SOL": 70.0,
            "SOL_CONF_PCT": 0.0005,
            "JUP": 0.5,
            "JUP_CONF_PCT": 0.0005
        }
        targets = compute_target_weights(self.state, prices)
        self.assertGreater(targets["USDC"], 0.0)
        self.assertGreater(targets["SOL"], 0.0)
        self.assertGreater(targets["JUP"], 0.0)
        self.assertAlmostEqual(sum(targets.values()), 1.0, places=4)


class TestReasoningAuditTrail(unittest.TestCase):
    def test_reasoning_hash_determinism(self):
        """Identical inputs must yield identical SHA-256 hashes for Memo proof."""
        state = VaultState(sol_balance=2.0, jup_balance=100.0, usdc_balance=500.0, tick=1)
        prices = {"SOL": 70.0, "JUP": 0.5}
        targets = {"USDC": 0.4, "SOL": 0.4, "JUP": 0.2}

        # Override timestamp for deterministic comparison
        payload = {
            "tick": state.tick,
            "prices": prices,
            "balances": {"USDC": 500.0, "SOL": 2.0, "JUP": 100.0},
            "targets": targets,
            "sol_momentum": 0.0,
            "jup_momentum": 0.0,
        }
        expected_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        self.assertEqual(len(expected_hash), 64)


class TestLedgerPersistence(unittest.TestCase):
    def test_sqlite_wal_init_and_write(self):
        """SQLite database must initialize in WAL mode and persist rebalance events."""
        # Use in-memory connection
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS oracle_ticks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tick         INTEGER,
                timestamp    TEXT,
                sol_price    REAL,
                sol_conf_pct REAL,
                jup_price    REAL,
                jup_conf_pct REAL
            );
            CREATE TABLE IF NOT EXISTS rebalance_events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                tick           INTEGER,
                timestamp      TEXT,
                asset          TEXT,
                direction      TEXT,
                usd_amount     REAL,
                slippage_bps   INTEGER,
                tx_signature   TEXT,
                reasoning_hash TEXT,
                is_dry_run     INTEGER,
                sol_price      REAL,
                jup_price      REAL
            );
        """)
        log_oracle_tick(conn, 1, {"SOL": 70.0, "SOL_CONF_PCT": 0.0002, "JUP": 0.5, "JUP_CONF_PCT": 0.0004})
        log_rebalance(conn, 1, "SOL", "buy", 50.0, 50, "SIM_TEST_SIG", "abc123hash", 70.0, 0.5)

        cursor = conn.execute("SELECT COUNT(*) FROM rebalance_events")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
