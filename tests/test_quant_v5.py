#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_quant_v5.py — ชุดทดสอบอัตโนมัติ (Automated Unit Tests) สำหรับ AI Quant Workbench v5.0
ครอบคลุมการทดสอบระดับวิศวกรรมซอฟต์แวร์ (Software Engineering & Quantitative Validation):
  1) การคำนวณ Technical Indicators (SMA, RSI, ADX, ATR, Bollinger, VWAP, Weekly MTF)
  2) การจำลองต้นทุนแฝง Dynamic Volatility-Adjusted Slippage & Commission
  3) การคำนวณสถิติระดับกองทุน (Sharpe, Sortino, Omega Ratio, Jensen's Alpha, Market Beta)
  4) พฤติกรรมกลยุทธ์อัจฉริยะ Regime-Adaptive V5 ในสภาวะตลาด Uptrend, Sideways และ Downtrend
  5) โมเดล Machine Learning Meta-Labeling & Explainable AI (XAI Feature Attribution)
  6) ระบบจัดพอร์ต Portfolio Optimizer & Pre-Trade Risk Gate
วิธีรันทดสอบ:
  python -m unittest discover -s tests -p "test_*.py" -v
"""

import os
import sys
import unittest

import numpy as np
import pandas as pd

# เพิ่มโฟลเดอร์รากของโปรเจกต์เข้า sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import backtest_engine as be
import quant_v4_modules as qv4
import quant_v5_institutional as qv5


def _make_synthetic_ohlcv(n: int = 260, mode: str = "uptrend") -> dict[str, pd.Series]:
    """สร้างข้อมูลราคาจำลอง (Synthetic Market Data) สำหรับทดสอบ Unit Test แบบไม่ต้องต่อเน็ต"""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")

    if mode == "uptrend":
        rets = 0.0012 + rng.normal(0.0, 0.011, size=n)
    elif mode == "sideways":
        t = np.linspace(0, 8 * np.pi, n)
        osc = np.sin(t) * 0.04
        base = 100.0 * (1.0 + osc + rng.normal(0.0, 0.004, size=n))
        close = pd.Series(base, index=idx, dtype=float)
        high = close * 1.012
        low = close * 0.988
        vol = pd.Series(rng.uniform(1e6, 2e6, size=n), index=idx, dtype=float)
        return {"high": high, "low": low, "close": close, "volume": vol}
    else:  # downtrend
        rets = -0.0020 + rng.normal(0.0, 0.018, size=n)

    close_vals = 100.0 * np.cumprod(1.0 + rets)
    close = pd.Series(close_vals, index=idx, dtype=float)
    high = close * (1.0 + rng.uniform(0.003, 0.018, size=n))
    low = close * (1.0 - rng.uniform(0.003, 0.018, size=n))
    vol = pd.Series(rng.uniform(8e5, 3e6, size=n), index=idx, dtype=float)
    return {"high": high, "low": low, "close": close, "volume": vol}


class TestQuantEngineV5(unittest.TestCase):
    def test_01_indicators_integrity(self):
        """ตรวจสอบว่า compute_indicators สร้างตัวชี้วัดครบและไม่มีค่า NaN ค้างที่จุดล่าสุด"""
        ohlcv = _make_synthetic_ohlcv(260, "uptrend")
        ind = be.compute_indicators(ohlcv)
        required_keys = ["sma20", "sma50", "sma200", "rsi14", "adx14", "atr14", "bb_pct_b", "vwap20", "wk_rsi"]
        for k in required_keys:
            self.assertIn(k, ind)
            self.assertFalse(np.isnan(float(ind[k].iloc[-1])), f"Indicator {k} has NaN at last row")

    def test_02_dynamic_slippage_and_institutional_metrics(self):
        """ตรวจสอบการคำนวณ Dynamic Slippage, Sortino, Omega, Alpha และ Beta"""
        ohlcv = _make_synthetic_ohlcv(260, "uptrend")
        bm_ohlcv = _make_synthetic_ohlcv(260, "sideways")
        ind = be.compute_indicators(ohlcv)
        slip = qv5.compute_dynamic_slippage_series(ohlcv["close"], ind)

        self.assertEqual(len(slip), len(ohlcv["close"]))
        self.assertTrue((slip >= 0.0002).all() and (slip <= 0.0035).all())

        sig = pd.Series(1.0, index=ohlcv["close"].index)
        res = be.evaluate_strategy(
            ohlcv["close"],
            sig,
            fee=0.001,
            shift_signal=True,
            ind=ind,
            benchmark_close=bm_ohlcv["close"],
        )
        for metric in ("sharpe", "sortino", "omega_ratio", "alpha_pct", "beta", "cost_drag_pct"):
            self.assertIn(metric, res)
        self.assertGreater(res["total_ret_pct"], 0.0)
        self.assertGreater(res["omega_ratio"], 1.0)

    def test_03_regime_adaptive_v5_and_four_core_strategies(self):
        """ตรวจสอบว่า generate_signals คืนค่าเฉพาะ 4 กลยุทธ์หลักที่ผ่านการคัดกรอง และทุกสัญญาณอยู่ในช่วง [0.0, 1.0]"""
        down_ohlcv = _make_synthetic_ohlcv(260, "downtrend")
        down_ind = be.compute_indicators(down_ohlcv)
        signals, _, _ = be.generate_signals(down_ohlcv["close"], down_ind)

        self.assertEqual(set(signals.keys()), {"buy_hold", "trend_atr_vol", "regime_adaptive_v5", "cross_sectional_mom"})
        for s_name, s_ser in signals.items():
            self.assertTrue((s_ser >= 0.0).all() and (s_ser <= 1.0).all(), f"{s_name} out of [0, 1] bounds")

        res_v5 = be.evaluate_strategy(down_ohlcv["close"], signals["regime_adaptive_v5"], fee=0.001, shift_signal=True, ind=down_ind)
        res_bh = be.evaluate_strategy(down_ohlcv["close"], signals["buy_hold"], shift_signal=False)
        self.assertGreater(res_v5["total_ret_pct"], res_bh["total_ret_pct"] + 10.0)

        # ทดสอบ Backtest ของทั้ง 6 ปุ่มโหมดบน GUI (1..6)
        up_ohlcv = _make_synthetic_ohlcv(260, "uptrend")
        up_ind = be.compute_indicators(up_ohlcv)
        up_sigs, _, _ = be.generate_signals(up_ohlcv["close"], up_ind)
        up_res = {k: be.evaluate_strategy(up_ohlcv["close"], v, shift_signal=(k != "buy_hold"), ind=up_ind) for k, v in up_sigs.items()}
        best_is = be.pick_best_active_strategy(up_res, close=up_ohlcv["close"], signals=up_sigs, ind=up_ind)
        six_bt = qv5.evaluate_six_button_modes(up_ohlcv["close"], up_ohlcv["volume"], up_ind, up_sigs, be.evaluate_strategy, best_is)
        self.assertEqual(len(six_bt), 6)
        for m_k, m_v in six_bt.items():
            self.assertIn("full", m_v)
            self.assertIn("oos_ret_pct", m_v)

    def test_04_explainable_ai_and_ml_meta_labeling(self):
        """ตรวจสอบว่าโมเดล ML Meta-Model และ Explainable AI (XAI) คืนค่าครบทั้ง 7 ปัจจัย"""
        ohlcv = _make_synthetic_ohlcv(260, "uptrend")
        ind = be.compute_indicators(ohlcv)
        xai = qv5.compute_xai_feature_importance(ohlcv["close"], ind)

        self.assertEqual(len(xai["xai_features"]), 7)
        self.assertEqual(len(xai["xai_impacts"]), 7)
        for v in xai["xai_impacts"]:
            self.assertTrue(-100.0 <= v <= 100.0)
        self.assertTrue(len(xai["top_bullish_driver"]) > 3)

    def test_05_pre_trade_risk_gate(self):
        """ตรวจสอบระบบ Pre-Trade Risk Gate ว่าตรวจจับคำสั่งซื้อที่เกินสัดส่วนหรือ VIX Panic ได้ถูกต้อง"""
        # กรณีปกติ (ซื้อ 10% ของพอร์ต, VIX 18) -> ต้องผ่าน (passed = True)
        ok_gate = qv5.check_pre_trade_risk_gate(
            symbol="AAPL", side="BUY", qty=50, price=200.0, stop_loss=185.0, account_equity=100000.0, macro_vix=18.0
        )
        self.assertTrue(ok_gate["passed"])

        # กรณีสั่งซื้อเกิน 60% ของพอร์ตและ VIX พุ่ง 40 -> ต้องแจ้งเตือน (passed = False)
        risky_gate = qv5.check_pre_trade_risk_gate(
            symbol="NVDA", side="BUY", qty=300, price=200.0, stop_loss=120.0, account_equity=100000.0, macro_vix=40.0
        )
        self.assertFalse(risky_gate["passed"])
        self.assertGreaterEqual(len(risky_gate["warnings"]), 2)

    def test_06_cross_sectional_universe_scanner_and_backtest(self):
        """ตรวจสอบ Cross-Sectional Universe Scanner (คัด Top Leaders + SPY>SMA200 Filter) และ Portfolio Backtest"""
        idx = pd.date_range("2024-01-01", periods=320, freq="B")
        t_arr = np.arange(320, dtype=float)
        # SPY ขาขึ้นชัด (SPY > SMA200)
        spy_bull = pd.Series(400.0 * np.exp(0.0005 * t_arr), index=idx)
        # สร้างตะกร้า 8 หุ้น: 3 ตัวนำตลาดขาขึ้นแรง, 2 ตัวทรงๆ, 3 ตัวขาลง
        close_map = {
            "LEAD1": pd.Series(100.0 * np.exp(0.0022 * t_arr), index=idx),
            "LEAD2": pd.Series(100.0 * np.exp(0.0018 * t_arr), index=idx),
            "LEAD3": pd.Series(100.0 * np.exp(0.0014 * t_arr), index=idx),
            "MID1": pd.Series(100.0 * np.exp(0.0004 * t_arr), index=idx),
            "MID2": pd.Series(100.0 * np.exp(0.0002 * t_arr), index=idx),
            "LAG1": pd.Series(100.0 * np.exp(-0.0010 * t_arr), index=idx),
            "LAG2": pd.Series(100.0 * np.exp(-0.0015 * t_arr), index=idx),
            "LAG3": pd.Series(100.0 * np.exp(-0.0020 * t_arr), index=idx),
        }

        scan = qv5.scan_cross_sectional_universe(close_map, spy_bull, top_n=3, hold_buffer=5)
        self.assertTrue(scan["market_bull"])
        top3_tickers = [r["ticker"] for r in scan["rankings"][:3]]
        self.assertEqual(top3_tickers, ["LEAD1", "LEAD2", "LEAD3"])
        self.assertAlmostEqual(sum(r["target_weight_pct"] for r in scan["rankings"]), 100.0, delta=0.5)

        # ทดสอบเมื่อ SPY เป็นขาลง (SPY <= SMA200) + มี Safe-Haven (GLD ขาขึ้น + SHY) -> ต้องหมุนเงินไปพักใน GLD/SHY
        spy_bear = pd.Series(400.0 * np.exp(-0.0015 * t_arr), index=idx)
        sh_map = {
            "GLD": pd.Series(200.0 * np.exp(0.0010 * t_arr), index=idx),
            "SHY": pd.Series(82.0 * np.exp(0.00015 * t_arr), index=idx),
        }
        scan_bear = qv5.scan_cross_sectional_universe(close_map, spy_bear, top_n=3, hold_buffer=5, safe_haven_map=sh_map)
        self.assertFalse(scan_bear["market_bull"])
        self.assertAlmostEqual(scan_bear["safe_haven_alloc"].get("GLD", 0.0), 50.0, delta=0.5)
        self.assertAlmostEqual(scan_bear["safe_haven_alloc"].get("SHY", 0.0), 50.0, delta=0.5)

        # ทดสอบ Historical Cross-Sectional Portfolio Backtest (Zero Look-ahead + Safe-Haven + Cost Drag)
        bt = qv5.backtest_cross_sectional_portfolio(close_map, spy_bull, top_n=3, hold_buffer=5, rebalance_days=21, safe_haven_map=sh_map)
        self.assertGreater(bt["total_ret_pct"], bt["spy_ret_pct"])
        self.assertIn(bt["gate_status"], ("PASS", "FAIL"))

    def test_07_rolling_walk_forward_gate_zero_lookahead(self):
        """ตรวจสอบ Rolling Walk-Forward Validation Gate (12M Train -> 3M OOS -> Roll Forward)"""
        ohlcv = _make_synthetic_ohlcv(420, "uptrend")
        ind = be.compute_indicators(ohlcv)
        sigs, _, _ = be.generate_signals(ohlcv["close"], ind)

        wfo = qv5.run_rolling_walk_forward_gate(
            ohlcv["close"], ind, sigs, be.evaluate_strategy, train_days=252, test_days=63, fee=0.001
        )
        self.assertGreaterEqual(wfo["n_folds"], 2)
        self.assertIn(wfo["gate_status"], ("PASS", "FAIL"))
        self.assertEqual(len(wfo["fold_details"]), wfo["n_folds"])
        for fd in wfo["fold_details"]:
            self.assertIn(fd["locked_strategy"], ("trend_atr_vol", "regime_adaptive_v5", "cross_sectional_mom"))

    def test_08_circuit_breaker_and_smart_limit_order(self):
        """ตรวจสอบ Portfolio Circuit Breaker (-5% ลดไม้ครึ่ง, -8% ล็อกซื้อ) และระบบ Smart Limit Order บน SQLite ชั่วคราว"""
        import tempfile
        import broker_bridge as bb

        # 1) ทดสอบ 3 ระดับของ Portfolio Circuit Breaker
        cb_norm = bb.evaluate_circuit_breaker(current_equity=98000.0, peak_equity=100000.0)
        self.assertEqual(cb_norm["status"], "NORMAL")
        self.assertEqual(cb_norm["size_multiplier"], 1.0)
        self.assertTrue(cb_norm["allow_buy"])

        cb_half = bb.evaluate_circuit_breaker(current_equity=94000.0, peak_equity=100000.0)
        self.assertEqual(cb_half["status"], "HALF_SIZE")
        self.assertEqual(cb_half["size_multiplier"], 0.5)
        self.assertTrue(cb_half["allow_buy"])

        cb_halt = bb.evaluate_circuit_breaker(current_equity=91000.0, peak_equity=100000.0)
        self.assertEqual(cb_halt["status"], "HALT_NEW_BUYS")
        self.assertEqual(cb_halt["size_multiplier"], 0.0)
        self.assertFalse(cb_halt["allow_buy"])

        # 2) ทดสอบการรัน Limit Order จำลองบนฐานข้อมูล SQLite ชั่วคราว (ไม่กระทบพอร์ตจริง)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = os.path.join(tmpdir, "test_paper.db")
            bb.reset_local_paper_account(100000.0, db_path=tmp_db)
            res_buy = bb._execute_local_paper_order("AAPL", "BUY", 10.0, 200.0, 184.0, order_type="limit", db_path=tmp_db)
            self.assertTrue(res_buy["ok"])
            self.assertIn("LIMIT", res_buy["message"])
            res_sell = bb._execute_local_paper_order("AAPL", "SELL", 10.0, 215.0, 0.0, order_type="limit", db_path=tmp_db)
            self.assertTrue(res_sell["ok"])

    def test_09_webhook_alert_graceful_skip(self):
        """ตรวจสอบว่า send_webhook_alert ข้ามอย่างปลอดภัยเมื่อยังไม่ได้ตั้งค่า Webhook URL"""
        import daily_runner as dr
        res = dr.send_webhook_alert("Test Quant v7.0 Alert")
        self.assertIn("sent", res)
        self.assertIn("channels", res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
