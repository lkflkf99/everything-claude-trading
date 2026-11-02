#!/usr/bin/env python3
"""Unit tests for carry_paper_bot — SPEC v1.1 mechanics invariants.

Run:  python3 research/carry/bot/carry_paper_bot_tests.py
"""

import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from carry_paper_bot import (  # noqa: E402
    CarryPaperBot, Store, DAY_MS, H4_MS, ECON_FLOOR_ANN,
)
from carry_backtest import liq_price_short  # noqa: E402

C, N = 10_000.0, 6_250.0          # capital / notional (N = C/1.6)
PP, PS = 50_000.0, 50_010.0       # entry prices perp / spot
T0 = 1_600_000_000_000


def fresh_bot(pure=True):
    d = Path(tempfile.mkdtemp(prefix="carry_bot_test_"))
    bot = CarryPaperBot(Store(d), pure=pure)
    bot.enter(T0, PP, PS, C)
    bot._tmpdir = d
    return bot


class TestEntry(unittest.TestCase):
    def test_entry_math(self):
        b = fresh_bot()
        s = b.st
        self.assertEqual(s.Q, 0.125)                     # floor(6250/50000 / 0.001)
        self.assertEqual(s.EP, PP)
        self.assertEqual(s.M, 0.5 * N)
        self.assertEqual(s.M_floor, s.M)
        self.assertEqual(s.P0, PP)
        fee_s = 0.125 * PS * 0.001
        fee_p = 0.125 * PP * 0.0005
        self.assertAlmostEqual(s.R, C - 0.125 * PS - fee_s - s.M - fee_p, places=8)
        self.assertAlmostEqual(b.equity(PS, PP), C - fee_s - fee_p, places=6)
        shutil.rmtree(b._tmpdir)

    def test_equity_identity_invariant(self):
        """E = Q(Ps-Pp) + Q*EP + M + R must equal cash accounting after events."""
        b = fresh_bot()
        s = b.st
        for i in range(1, 50):  # random-ish funding + bars below trigger
            b.apply_funding(T0 + i * 8 * 3_600_000, 0.0001 * (1 if i % 3 else -1), PP * (1 + i / 1000))
            b.process_4h_bar(T0 + i * H4_MS, PP * 1.1, PP * 1.05, PS * 1.05)
        e = b.equity(PS * 1.05, PP * 1.05)
        self.assertAlmostEqual(e, s.Q * (PS * 1.05 - PP * 1.05) + s.Q * s.EP + s.M + s.R, places=6)
        self.assertGreater(e, C - 20)   # funding accumulated, no big loss
        shutil.rmtree(b._tmpdir)


class TestFunding(unittest.TestCase):
    def test_sign_and_amount(self):
        b = fresh_bot()
        mark = 50_100.0
        b.apply_funding(T0 + 8 * 3_600_000, 0.0001, mark)   # positive: short receives
        self.assertAlmostEqual(b.st.M, 0.5 * N + 0.125 * mark * 0.0001, places=8)
        b.apply_funding(T0 + 16 * 3_600_000, -0.0002, mark)  # negative: short pays
        self.assertAlmostEqual(b.st.funding_total,
                               0.125 * mark * 0.0001 - 0.125 * mark * 0.0002, places=8)
        shutil.rmtree(b._tmpdir)

    def test_no_double_apply_and_no_pre_entry(self):
        b = fresh_bot()
        b.apply_funding(T0 - 8 * 3_600_000, 0.0001, PP)      # before entry: ignored
        b.apply_funding(T0 + 8 * 3_600_000, 0.0001, PP)
        b.apply_funding(T0 + 8 * 3_600_000, 0.0001, PP)      # duplicate: ignored
        self.assertEqual(len(b.st.applied_funding), 1)
        shutil.rmtree(b._tmpdir)


class TestRebalanceAndSweep(unittest.TestCase):
    def test_trigger_exactly_at_1_2x_anchor(self):
        b = fresh_bot()
        # high just below trigger: sweep only, no rebalance
        b.process_4h_bar(T0 + H4_MS, 1.199 * PP, 1.19 * PP, 1.19 * PS)
        self.assertEqual(len(b.st.rebalances), 0)
        # high touches 1.2x P0 -> rebalance at bar close, delta = Q/6 floored
        b.process_4h_bar(T0 + 2 * H4_MS, 1.2 * PP, 1.2 * PP, 1.2 * PS)
        self.assertEqual(len(b.st.rebalances), 1)
        self.assertEqual(b.st.rebalances[0][1], 0.02)        # floor(0.125/6 / .001)
        self.assertAlmostEqual(b.st.Q, 0.105, places=10)
        self.assertEqual(b.st.P0, 1.2 * PP)                  # anchor reset to exec
        self.assertEqual(b.st.M_floor, b.st.M)               # floor re-anchored
        shutil.rmtree(b._tmpdir)

    def test_sweep_floor_locked(self):
        b = fresh_bot()
        s = b.st
        s.M = s.M_floor - 1.0                    # wallet below floor (uPnL loss)
        b.process_4h_bar(T0 + H4_MS, PP * 1.01, PP, PS)
        self.assertEqual(s.sweeps_total, 0.0)    # never sweeps principal/uPnL
        s.M = s.M_floor + 25.0                   # carry inflow above floor
        b.process_4h_bar(T0 + 2 * H4_MS, PP * 1.01, PP, PS)
        self.assertAlmostEqual(s.sweeps_total, 25.0, places=8)
        self.assertAlmostEqual(s.M, s.M_floor, places=8)
        shutil.rmtree(b._tmpdir)

    def test_funding_then_sweep_same_close_order(self):
        """Stamp at bar close must credit before the sweep (backtest order)."""
        b = fresh_bot()
        s = b.st
        stamp = T0 + H4_MS
        b.apply_funding(stamp, 0.001, PP)        # credit at old size first
        b.process_4h_bar(T0, PP * 1.01, PP, PS)  # then sweep: excess leaves wallet
        self.assertAlmostEqual(s.M, s.M_floor, places=8)
        self.assertAlmostEqual(s.sweeps_total, 0.125 * PP * 0.001, places=8)
        shutil.rmtree(b._tmpdir)


class TestKillSwitchAndLadder(unittest.TestCase):
    def test_kill_switch_halves_and_widens_lp(self):
        b = fresh_bot(pure=False)
        s = b.st
        # pump mark so liq distance < 5%: LP(0)=(M+Q*EP)/(1.005Q) = 1.4925x EP
        mark = 1.44 * PP
        dist_before = b.liq_distance(mark)
        self.assertLess(dist_before, 0.05)
        lp_before = liq_price_short(s.M, s.Q, s.EP)
        b.update_monitors(T0 + H4_MS, mark, mark, mark)
        self.assertAlmostEqual(s.Q, 0.063, places=10)        # halved (floor step)
        lp_after = liq_price_short(s.M, s.Q, s.EP)
        dist_after = b.liq_distance(mark)
        self.assertGreater(lp_after, lp_before)              # LP pushed higher
        self.assertGreater(dist_after / dist_before, 1.5)    # distance ~doubles
        self.assertEqual(s.M_floor, s.M)                     # buffer retained
        self.assertGreater(s.R, 0.1 * N)                     # spot proceeds banked
        # cooldown blocks immediate second cut
        q_now = s.Q
        b.update_monitors(T0 + 2 * H4_MS, mark, mark, mark)
        self.assertEqual(s.Q, q_now)
        shutil.rmtree(b._tmpdir)

    def test_pure_mode_suppresses_actions(self):
        b = fresh_bot(pure=True)
        mark = 1.44 * PP
        b.update_monitors(T0 + H4_MS, mark, mark, mark)
        self.assertEqual(b.st.Q, 0.125)                      # alert only, no cut
        shutil.rmtree(b._tmpdir)

    def test_derisk_ladder_winddown(self):
        b = fresh_bot(pure=False)
        s = b.st
        s.peak_equity = C + 200
        # fabricate equity loss > 8%: wallet burned
        s.M = 0.5 * N - 0.09 * (C + 200) - 100
        b.update_monitors(T0 + H4_MS, PP, PS, PP)
        self.assertFalse(s.open)
        self.assertTrue(s.halted)
        shutil.rmtree(b._tmpdir)


class TestEconomicFloor(unittest.TestCase):
    def test_floor_fires_after_60d_below(self):
        b = fresh_bot(pure=False)
        s = b.st
        # 90 days of tiny funding credits -> annualized carry << 1.5%
        for i in range(1, 90 * 3 + 1):
            b.apply_funding(T0 + i * 8 * 3_600_000, 0.000001, PP)
        # at day 89: below floor but < 60d persistence window start...
        # force persistence: set econ since 61 days ago
        s.floor_below_since["econ"] = T0 + (89 - 61) * DAY_MS
        b.update_monitors(T0 + 91 * DAY_MS, PP, PS, PP)
        self.assertFalse(s.open)                             # wound down per spec
        shutil.rmtree(b._tmpdir)

    def test_floor_recovers(self):
        b = fresh_bot()
        s = b.st
        for i in range(1, 91 * 3):
            b.apply_funding(T0 + i * 8 * 3_600_000, 0.0002, PP)  # healthy ~5.5%/yr
        b.update_monitors(T0 + 91 * DAY_MS, PP, PS, PP)
        self.assertIsNone(s.floor_below_since.get("econ"))
        self.assertTrue(s.open)
        shutil.rmtree(b._tmpdir)


class TestWindDown(unittest.TestCase):
    def test_wind_down_accounting(self):
        b = fresh_bot()
        s = b.st
        px_p, px_s = 1.1 * PP, 1.1 * PS
        b.wind_down(T0 + H4_MS, px_p, px_s, "test")
        fee_p = 0.125 * px_p * 0.0005
        fee_s = 0.125 * px_s * 0.001
        expect = (C - 0.125 * PS - 0.125 * PS * 0.001 - 0.5 * N - 0.125 * PP * 0.0005
                  + 0.5 * N + 0.125 * (PP - px_p) - fee_p + 0.125 * px_s - fee_s)
        self.assertAlmostEqual(s.R, expect, places=6)
        self.assertFalse(s.open)
        shutil.rmtree(b._tmpdir)

    def test_math_sanity(self):
        self.assertTrue(math.isfinite(liq_price_short(0.5 * N, 0.125, PP)))
        self.assertGreater(ECON_FLOOR_ANN, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
