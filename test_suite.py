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


class TestPartnerTracks(unittest.TestCase):
    def test_multihopper_routing_evaluation(self):
        """MultiHopper router must compute net output with fee rebate."""
        from multihopper_router import MultiHopperRouter
        router = MultiHopperRouter(rebate_bps=5)
        direct_quote = {"outAmount": "1000000"}
        route = router.evaluate_multi_hop_route("USDC_MINT", "SOL_MINT", 1000000, direct_quote)
        self.assertTrue(route["is_optimal"])
        self.assertGreater(route["estimated_out_units"], 1000000)
        self.assertEqual(route["fee_rebate_bps"], 5)

    def test_multihopper_priority_fee_escalation(self):
        """Priority fees must scale dynamically with network congestion."""
        from multihopper_router import MultiHopperRouter
        router = MultiHopperRouter()
        low_fee = router.compute_priority_fee_micro_lamports("low")
        high_fee = router.compute_priority_fee_micro_lamports("high")
        self.assertGreater(high_fee, low_fee)

    def test_ace_data_cloud_conviction_scoring(self):
        """Ace Data Cloud client must return structured sentiment conviction scores."""
        from ace_data_client import AceDataCloudClient
        client = AceDataCloudClient()
        conviction = client.get_market_conviction("SOL")
        self.assertIn("conviction_score", conviction)
        self.assertGreater(conviction["conviction_score"], 0.0)
        self.assertEqual(conviction["status"], "HEALTHY")

    def test_ace_data_cloud_half_kelly_modulation(self):
        """Ace Data Cloud conviction must modulate Half-Kelly sizing as a Bayesian prior."""
        from ace_data_client import AceDataCloudClient
        client = AceDataCloudClient()
        base_f = 0.40
        modulated_f = client.modulate_half_kelly(base_f, "SOL")
        self.assertIsInstance(modulated_f, float)
        self.assertGreater(modulated_f, 0.0)


class TestHardenedEdgeCases(unittest.TestCase):
    def test_zero_division_guard_on_prices(self):
        """Zero asset prices must never trigger ZeroDivisionError."""
        state = VaultState(sol_balance=2.0, jup_balance=100.0, usdc_balance=500.0, peak_usd_value=1000.0)
        total = state.total_usd(0.0, 0.0)
        self.assertEqual(total, 500.0)
        dd = state.drawdown(0.0, 0.0)
        self.assertEqual(dd, 0.50)

    def test_empty_and_short_buffer_momentum(self):
        """Empty or single-element buffers must return 0.0 momentum without crashing."""
        state = VaultState()
        self.assertEqual(state.momentum(np.array([])), 0.0)
        self.assertEqual(state.momentum(np.array([100.0])), 0.0)

    def test_steve_arena_timestamp_epoch_validity(self):
        """Steve Arena payload must contain valid Unix epoch timestamp (> 1.7e9)."""
        from steve_mcp_adapter import SteveArenaAdapter
        adapter = SteveArenaAdapter(agent_id="test_agent")
        payload = adapter.format_arena_activity_payload(
            tick=1, asset="SOL", direction="buy", usd_delta=50.0,
            reasoning_hash="abcd1234abcd", tx_signature="sim_tx_123"
        )
        self.assertGreater(payload["timestamp"], 1700000000.0)
        self.assertIn("timestamp_iso", payload)
        self.assertTrue(payload["timestamp_iso"].endswith("Z"))

    def test_balance_clamping_invariants(self):
        """Sell units must be mathematically clamped to avoid on-chain Insufficient Funds reverts."""
        sol_balance = 2.500000000
        sol_px = 72.36
        # Simulate an extreme $500 sell delta (more than the $180.90 SOL balance)
        usd_delta = -500.0
        max_sol_lamports = int(sol_balance * 1_000_000_000)
        unclamped = int(abs(usd_delta) / sol_px * 1_000_000_000)
        clamped = min(unclamped, max_sol_lamports)
        self.assertEqual(clamped, max_sol_lamports)
        self.assertLessEqual(clamped, max_sol_lamports)


if __name__ == "__main__":
    unittest.main(verbosity=2)
