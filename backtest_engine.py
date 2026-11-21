#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_engine.py — AI Quant Engine Phase 2.5 (Multi-Factor Score, Regime Filter, MTF, Auto-Tune & Trade Log)
รองรับ:
  1) 7 กลยุทธ์ (รวมกลยุทธ์ใหม่ adaptive_quant_pro):
     - buy_hold           : ถือยาว 100% (Benchmark)
     - sma_cross          : ตัดเส้นค่าเฉลี่ย (SMA50 > SMA200)
     - trend_momentum     : Trend (SMA) + MACD + RSI < 78
     - rsi_mean_rev       : ซื้อเมื่อ Oversold (RSI < 35) ขายเมื่อ Overbought (RSI > 65)
     - trend_vol_stop     : Trend + Momentum + Volume Filter + Fixed Trailing Stop (8%)
     - atr_vol_target     : Trend + ATR Trailing Stop (3.2x) + Volatility-Targeted Sizing
     - adaptive_quant_pro : [NEW] Market Regime (ADX + Bollinger) + Weekly MTF Confirmation + In-Sample Auto-Tuning
  2) Multi-Factor Quant Score (0-100) & เกรดสัญญาณ (A+ ถึง D):
     - แยกคะแนน Trend (25), Weekly MTF (20), Momentum (20), Regime & Volume (20), Risk/Volatility (15)
  3) สถิติเชิงลึก (Deep Metrics) & ประวัติเทรดรายไม้ (Trade-by-Trade Log):
     - Expectancy%, Payoff Ratio, Recovery Factor, Max Win/Loss Streak, จุดเข้า-ออก (Buy/Sell Markers) และเหตุผลที่ออก
  4) โหมดสแกนรายวัน (--scan --capital 100000), บันทึก SQLite (runs.db), ส่งออก CSV และวิเคราะห์ด้วย Ollama AI (--ai)
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

plt.rcParams["font.family"] = ["Tahoma", "Leelawadee UI", "Malgun Gothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OLLAMA_API = "http://127.0.0.1:11434/api/chat"
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
RISK_FREE_RATE = 0.02  # สมมติผลตอบแทนไร้ความเสี่ยง 2% ต่อปี


# ==========================================
# 1. Ollama LLM & Model Configuration
# ==========================================
def load_model_config(model_key: str | None = None) -> dict:
    """โหลดคอนฟิกโมเดลและพารามิเตอร์จากโฟลเดอร์ /model"""
    default_cfg = {
        "key": "llama3.1-8b",
        "ollama_pull_name": "llama3.1:8b",
        "default": True,
        "status": "active",
        "options": {"max_tokens": 300, "temperature": 0.3, "top_p": 0.9},
    }
    if model_key:
        cfg_path = os.path.join(MODEL_DIR, f"{model_key}.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                return json.load(f)

    models_file = os.path.join(MODEL_DIR, "models.json")
    if os.path.exists(models_file):
        with open(models_file, encoding="utf-8") as f:
            data = json.load(f)
        for m in data.get("models", []):
            if (model_key and m.get("key") == model_key) or (not model_key and m.get("default")):
                key_file = os.path.join(MODEL_DIR, f"{m['key']}.json")
                if os.path.exists(key_file):
                    with open(key_file, encoding="utf-8") as kf:
                        return json.load(kf)
                return m
    return default_cfg


def query_llm(prompt: str, model_key: str | None = None) -> str:
    """ส่ง Prompt ไปยัง Ollama Local API"""
    cfg = load_model_config(model_key)
    model_name = cfg.get("ollama_pull_name", "llama3.1:8b")
    opts = cfg.get("options", {})

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "num_predict": min(opts.get("max_tokens", 300), 300),
            "temperature": opts.get("temperature", 0.3),
            "top_p": opts.get("top_p", 0.9),
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_API, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8")
    except Exception as e:
        return f"[Ollama Error: {e}]"

    contents = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj.get("message"), dict) and "content" in obj["message"]:
                contents.append(obj["message"]["content"])
        except json.JSONDecodeError:
            continue
    return "".join(contents).strip()


def build_ai_prompt(
    ticker: str,
    period: str,
    results: dict[str, dict],
    best_strat: str,
    scan_info: dict,
    oos_results: dict[str, dict] | None = None,
) -> str:
    """สร้าง Prompt สรุปเปรียบเทียบกลยุทธ์ คะแนน Multi-Factor และแผนเทรดวันนี้ให้ Ollama วิเคราะห์"""
    bh = results["buy_hold"]
    best = results[best_strat]
    lines = [
        "คุณคือ Quant Analyst อาชีพ ช่วยสรุปผล Backtest และแผนเทรดวันนี้สั้นๆ กระชับ 4 ข้อ (ภาษาไทย):",
        "1. เปรียบเทียบ Buy & Hold กับกลยุทธ์ที่ชนะ (ผลตอบแทน, Sharpe, Expectancy, การลด Max Drawdown)",
        "2. วิเคราะห์สภาวะตลาด (Market Regime), เทรนด์ Weekly MTF และคะแนน Multi-Factor Score (0-100)",
        "3. แผนปฏิบัติวันนี้ (Action, ราคา Stop-Loss, ขนาดไม้ที่เหมาะสม และพารามิเตอร์ที่จูนได้)",
        "4. ข้อควรระวังตามความผันผวนปัจจุบัน (ATR / Max Consecutive Losses)\n",
        f"[สินทรัพย์: {ticker} | ช่วงเวลา: {period}]",
        f"- Buy & Hold: Ret {bh['total_ret_pct']:+.2f}%, CAGR {bh['cagr_pct']:+.2f}%, MaxDD {bh['max_dd_pct']:.2f}%, Sharpe {bh['sharpe']:.2f}",
        f"- Best Active Strategy ({best_strat}): Ret {best['total_ret_pct']:+.2f}%, MaxDD {best['max_dd_pct']:.2f}%, Sharpe {best['sharpe']:.2f}, Expectancy {best['expectancy_pct']:+.2f}%/trade, WinRate {best['win_rate_pct']:.1f}% ({best['trades_count']} trades)",
        f"- Quant Score วันนี้: {scan_info['quant_score']:.0f}/100 (เกรด {scan_info['grade']}) | สภาวะตลาด: {scan_info['regime']} | Weekly Trend: {scan_info['weekly_trend']}",
        f"- สัญญาณวันนี้: {scan_info['action']} | ราคาล่าสุด {scan_info['close']:.2f} | ATR Stop-Loss {scan_info['stop_price']:.2f} (-{scan_info['stop_dist_pct']:.2f}%) | แนะนำพอร์ต {scan_info['alloc_pct']:.1f}%",
        f"- พารามิเตอร์ Auto-Tune: {scan_info['tuned_params_str']}",
    ]
    if oos_results and best_strat in oos_results:
        oos_bh = oos_results["buy_hold"]
        oos_b = oos_results[best_strat]
        lines.append(
            f"- ผลช่วง Out-of-Sample (Test): {best_strat} ได้ Ret {oos_b['total_ret_pct']:+.2f}%, MaxDD {oos_b['max_dd_pct']:.2f}%, Sharpe {oos_b['sharpe']:.2f} "
            f"(เทียบ Buy & Hold Ret {oos_bh['total_ret_pct']:+.2f}%, Sharpe {oos_bh['sharpe']:.2f})"
        )
    return "\n".join(lines)


# ==========================================
# 2. Data Fetching & Deep Technical Indicators (ADX, Bollinger, Weekly MTF, ATR)
# ==========================================
def extract_series(df: pd.DataFrame, field: str, ticker: str) -> pd.Series:
    """ดึงคอลัมน์ราคา/วอลุ่มจาก DataFrame ของ yfinance (รองรับทั้ง MultiIndex และปกติ)"""
    if isinstance(df.columns, pd.MultiIndex):
        if (field, ticker) in df.columns:
            return df[(field, ticker)].astype(float)
        return df[field].iloc[:, 0].astype(float)
    return df[field].astype(float)


def fetch_ohlcv(ticker: str, period: str, force_refresh: bool = False) -> dict[str, pd.Series]:
    """ดาวน์โหลดข้อมูล High, Low, Close, Volume (ผ่าน Local SQLite Cache ใน quant_v4_modules เพื่อความเร็วสูง)"""
    try:
        import quant_v4_modules as qv4
        ohlcv, _ = qv4.fetch_ohlcv_cached(ticker, period, force_refresh=force_refresh)
        return ohlcv
    except Exception:
        df = yf.download(ticker, period=period, progress=False, auto_adjust=False)
        df = df.dropna(how="all")
        if df.empty:
            raise ValueError(f"ไม่พบข้อมูลสำหรับ {ticker} (period={period})")
        close = extract_series(df, "Close", ticker).dropna()
        high = extract_series(df, "High", ticker).reindex(close.index).fillna(close)
        low = extract_series(df, "Low", ticker).reindex(close.index).fillna(close)
        volume = extract_series(df, "Volume", ticker).reindex(close.index).fillna(0.0)
        return {"high": high, "low": low, "close": close, "volume": volume}


def compute_indicators(ohlcv: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """
    คำนวณ Technical Indicators เชิงลึก:
      - Daily SMA (15, 20, 30, 50, 200), EMA, MACD(12,26,9), RSI(14)
      - ATR(14) & Annualized Rolling Volatility (20D)
      - ADX(14), +DI, -DI (สำหรับแยกสภาวะตลาด Trending vs Sideway)
      - Bollinger Bands (20, 2.0) -> Upper, Lower, %B, Bandwidth
      - Multi-Timeframe Weekly Equivalent (Weekly EMA10 = 50D, Weekly EMA30 = 150D, Weekly RSI)
    """
    high = ohlcv["high"]
    low = ohlcv["low"]
    close = ohlcv["close"]
    volume = ohlcv["volume"]

    sma15 = close.rolling(15, min_periods=5).mean()
    sma20 = close.rolling(20, min_periods=5).mean()
    sma30 = close.rolling(30, min_periods=10).mean()
    sma50 = close.rolling(50, min_periods=15).mean()
    sma200 = close.rolling(200, min_periods=50).mean()

    # RSI(14) แบบ Wilder's Smoothing
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi14 = (100 - (100 / (1 + rs))).fillna(50.0)

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_sig

    # Volume Ratio (20D)
    vol_sma20 = volume.rolling(20, min_periods=5).mean()
    vol_ratio = (volume / vol_sma20.replace(0, np.nan)).fillna(1.0)

    # True Range & ATR(14)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    # ADX(14) & Directional Indicators (+DI / -DI)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm_s = pd.Series(plus_dm, index=close.index).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    minus_dm_s = pd.Series(minus_dm, index=close.index).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    plus_di = 100.0 * (plus_dm_s / atr14.replace(0, np.nan)).fillna(0.0)
    minus_di = 100.0 * (minus_dm_s / atr14.replace(0, np.nan)).fillna(0.0)
    dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0.0)
    adx14 = dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().fillna(20.0)

    # Bollinger Bands (20, 2.0)
    bb_std = close.rolling(20, min_periods=5).std()
    bb_upper = sma20 + 2.0 * bb_std
    bb_lower = sma20 - 2.0 * bb_std
    bb_pct_b = ((close - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)).fillna(0.5)
    bb_width = ((bb_upper - bb_lower) / sma20.replace(0, np.nan) * 100.0).fillna(10.0)

    # Multi-Timeframe (Weekly Trend Confirmation แบบไร้ Look-ahead Bias)
    # 10 สัปดาห์ = 50 วันทำการ, 30 สัปดาห์ = 150 วันทำการ, Weekly RSI(14 สัปดาห์ = 70 วันทำการ)
    wk_ema10 = close.ewm(span=50, adjust=False).mean()
    wk_ema30 = close.ewm(span=150, adjust=False).mean()
    wk_gain = delta.clip(lower=0).ewm(alpha=1 / 70, min_periods=20, adjust=False).mean()
    wk_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 70, min_periods=20, adjust=False).mean()
    wk_rs = wk_gain / wk_loss.replace(0, np.nan)
    wk_rsi = (100.0 - (100.0 / (1.0 + wk_rs))).fillna(50.0)
    weekly_bull = ((wk_ema10 > wk_ema30) & (close > wk_ema10 * 0.98)) | ((close > wk_ema10) & (wk_rsi > 51))

    # Rolling 20-Day Annualized Volatility
    rets = close.pct_change()
    roll_vol20 = (rets.rolling(20, min_periods=5).std() * np.sqrt(252.0)).fillna(0.20)

    # Institutional Rolling VWAP (20D & 60D)
    typ_price = (high + low + close) / 3.0
    tp_vol = typ_price * volume.replace(0, 1.0)
    vwap20 = (tp_vol.rolling(20, min_periods=3).sum() / volume.replace(0, 1.0).rolling(20, min_periods=3).sum())
    vwap60 = (tp_vol.rolling(60, min_periods=10).sum() / volume.replace(0, 1.0).rolling(60, min_periods=10).sum())

    return {
        "sma15": sma15,
        "sma20": sma20,
        "sma30": sma30,
        "sma50": sma50,
        "sma200": sma200,
        "rsi14": rsi14,
        "macd": macd,
        "macd_sig": macd_sig,
        "macd_hist": macd_hist,
        "vol_ratio": vol_ratio,
        "atr14": atr14,
        "adx14": adx14,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_pct_b": bb_pct_b,
        "bb_width": bb_width,
        "wk_ema10": wk_ema10,
        "wk_ema30": wk_ema30,
        "wk_rsi": wk_rsi,
        "weekly_bull": weekly_bull.astype(float),
        "roll_vol20": roll_vol20,
        "vwap20": vwap20,
        "vwap60": vwap60,
    }


def compute_volume_profile(close: pd.Series, volume: pd.Series, n_bins: int = 24, lookback: int = 126) -> dict:
    """
    คำนวณ Volume Profile (Volume-by-Price) ย้อนหลัง lookback วัน:
      - POC (Point of Control): ระดับราคาที่มีปริมาณซื้อขายสะสมสูงสุด (ฐานต้นทุนสถาบัน)
      - VAH / VAL (Value Area High / Low 70%): กรอบราคาที่กินสัดส่วนวอลุ่มรวม 70%
    """
    c_sub = close.iloc[-lookback:] if len(close) > lookback else close
    v_sub = volume.iloc[-lookback:] if len(volume) > lookback else volume
    v_clean = v_sub.replace(0, 1.0).to_numpy()
    c_vals = c_sub.to_numpy()

    p_min, p_max = float(np.min(c_vals)), float(np.max(c_vals))
    if p_max <= p_min:
        p_max = p_min * 1.01

    edges = np.linspace(p_min, p_max, n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    hist_vol, _ = np.histogram(c_vals, bins=edges, weights=v_clean)

    poc_idx = int(np.argmax(hist_vol))
    poc_price = float(centers[poc_idx])

    # คำนวณ Value Area 70% รอบ POC
    total_vol = float(np.sum(hist_vol))
    target_vol = 0.70 * total_vol
    cum_vol = float(hist_vol[poc_idx])
    left_i, right_i = poc_idx, poc_idx
    while cum_vol < target_vol and (left_i > 0 or right_i < n_bins - 1):
        v_left = hist_vol[left_i - 1] if left_i > 0 else -1.0
        v_right = hist_vol[right_i + 1] if right_i < n_bins - 1 else -1.0
        if v_left >= v_right:
            left_i -= 1
            cum_vol += float(hist_vol[left_i])
        else:
            right_i += 1
            cum_vol += float(hist_vol[right_i])

    val_price = float(edges[left_i])
    vah_price = float(edges[right_i + 1])
    last_c = float(close.iloc[-1])

    if last_c >= vah_price:
        vp_status = f"Breakout เหนือ VAH ({poc_price:,.1f})"
    elif last_c >= poc_price:
        vp_status = f"ยืนเหนือ POC ({poc_price:,.1f} = แนวรับ)"
    elif last_c >= val_price:
        vp_status = f"ใต้ POC ({poc_price:,.1f} = แนวต้าน)"
    else:
        vp_status = f"หลุดกรอบ VAL ({val_price:,.1f})"

    return {
        "poc_price": poc_price,
        "vah_price": vah_price,
        "val_price": val_price,
        "bin_centers": centers,
        "bin_volumes": hist_vol,
        "vp_status": vp_status,
    }


def run_monte_carlo_and_var(
    close: pd.Series,
    raw_signal: pd.Series,
    fee: float = 0.001,
    n_sims: int = 1000,
    horizon_days: int = 252,
    shift_signal: bool = True,
) -> dict:
    """
    จำลอง Monte Carlo Simulation (1,000 เส้นทาง, 252 วันทำการ = 1 ปีข้างหน้า) และคำนวณ Value at Risk (VaR / CVaR):
      - Historical Daily VaR (95%, 99%) & Expected Shortfall (CVaR 95%)
      - สุ่ม Bootstrap จากผลตอบแทนรายวันของกลยุทธ์เพื่อหา:
          * P50 (Median 1Y Return), P05 (Worst 5% Return), P95 (Best 5% Return)
          * Probability of Profit (โอกาสกำไรใน 1 ปี %)
          * Risk of Ruin (โอกาสเกิด Drawdown ลึกเกิน -25% ระหว่างปี %)
    """
    rets = close.pct_change().fillna(0.0)
    pos = raw_signal.shift(1).fillna(0.0) if shift_signal else raw_signal.astype(float)
    trades = pos.diff().abs().fillna(0.0)
    strat_rets = ((pos * rets) - (trades * fee)).to_numpy()

    # กรองเฉพาะช่วงที่มีข้อมูลเพื่อคำนวณ VaR
    valid_rets = strat_rets[~np.isnan(strat_rets)]
    if len(valid_rets) < 10:
        valid_rets = rets.to_numpy()

    var_95 = float(np.percentile(valid_rets, 5) * 100.0)
    var_99 = float(np.percentile(valid_rets, 1) * 100.0)
    tail_losses = valid_rets[valid_rets <= np.percentile(valid_rets, 5)]
    cvar_95 = float(tail_losses.mean() * 100.0) if len(tail_losses) > 0 else var_95

    rng = np.random.default_rng(42)
    sim_idx = rng.integers(0, len(valid_rets), size=(n_sims, horizon_days))
    sim_daily = valid_rets[sim_idx]
    sim_eq = np.cumprod(1.0 + sim_daily, axis=1) * 100.0

    final_rets = (sim_eq[:, -1] / 100.0 - 1.0) * 100.0
    mc_p05_ret = float(np.percentile(final_rets, 5))
    mc_p50_ret = float(np.percentile(final_rets, 50))
    mc_p95_ret = float(np.percentile(final_rets, 95))
    prob_profit = float(np.mean(final_rets > 0.0) * 100.0)

    # คำนวณ Max Drawdown ของแต่ละเส้นทางจาก 1,000 เส้นทาง
    roll_peaks = np.maximum.accumulate(sim_eq, axis=1)
    sim_dds = (sim_eq - roll_peaks) / roll_peaks * 100.0
    path_max_dds = np.min(sim_dds, axis=1)
    mc_median_dd = float(np.percentile(path_max_dds, 50))
    mc_p05_dd = float(np.percentile(path_max_dds, 5))
    risk_of_ruin = float(np.mean(path_max_dds <= -25.0) * 100.0)

    # เส้น Percentile Curves สำหรับพล็อตกราฟพัด (Monte Carlo Fan Chart)
    p05_curve = np.percentile(sim_eq, 5, axis=0)
    p25_curve = np.percentile(sim_eq, 25, axis=0)
    p50_curve = np.percentile(sim_eq, 50, axis=0)
    p75_curve = np.percentile(sim_eq, 75, axis=0)
    p95_curve = np.percentile(sim_eq, 95, axis=0)

    return {
        "var_95_pct": var_95,
        "cvar_95_pct": cvar_95,
        "var_99_pct": var_99,
        "mc_p05_ret_pct": mc_p05_ret,
        "mc_median_ret_pct": mc_p50_ret,
        "mc_p95_ret_pct": mc_p95_ret,
        "mc_prob_profit_pct": prob_profit,
        "mc_median_dd_pct": mc_median_dd,
        "mc_p05_dd_pct": mc_p05_dd,
        "mc_risk_of_ruin_pct": risk_of_ruin,
        "p05_curve": p05_curve,
        "p25_curve": p25_curve,
        "p50_curve": p50_curve,
        "p75_curve": p75_curve,
        "p95_curve": p95_curve,
        "sample_paths": sim_eq[:45, :],
    }


def compute_half_kelly_pct(win_rate_pct: float, payoff_ratio: float) -> float:
    """คำนวณสัดส่วนการลงทุนตามสูตร Half-Kelly Criterion: 0.5 * (W - (1-W)/R)"""
    w = float(win_rate_pct) / 100.0
    r = float(payoff_ratio)
    if r <= 0 or w <= 0:
        return 0.0
    kelly = w - ((1.0 - w) / r)
    half_kelly = 0.5 * max(0.0, kelly)
    return float(np.clip(half_kelly * 100.0, 0.0, 100.0))


def compute_correlation_matrix(close_dict: dict[str, pd.Series]) -> pd.DataFrame:
    """คำนวณตารางสหสัมพันธ์ของผลตอบแทนรายวัน (Asset Return Correlation Matrix)"""
    if not close_dict:
        return pd.DataFrame()
    rets_df = pd.DataFrame({t: s.pct_change() for t, s in close_dict.items()}).dropna(how="all")
    return rets_df.corr().fillna(0.0)


# ==========================================
# 3. Multi-Factor Quant Score (0-100) & Market Regime Classifier
# ==========================================
def compute_quant_score_and_regime(close: pd.Series, ind: dict[str, pd.Series], best_res: dict) -> dict:
    """
    คำนวณคะแนน Multi-Factor Quant Score (0-100) ณ วันล่าสุด แยกเป็น 5 มิติ:
      1) Daily Trend Score (0-25)     : ราคาเทียบ SMA20/50/200 และทิศทาง DI+/DI-
      2) Weekly MTF Score (0-20)      : เทรนด์ภาพใหญ่ระดับสัปดาห์ (wk_ema10 > wk_ema30 & wk_rsi)
      3) Momentum Score (0-20)        : RSI(14) อยู่ในโซนแข็งแกร่งแต่ไม่ Overbought สุดโต่ง + MACD Hist
      4) Regime & Volume Score (0-20) : ความชัดเจนของสภาวะตลาด (ADX) + Volume Ratio
      5) Risk & Backtest Score (0-15) : ความสม่ำเสมอของกลยุทธ์ (Sharpe, Expectancy, MaxDD)
    """
    c = float(close.iloc[-1])
    s20 = float(ind["sma20"].iloc[-1])
    s50 = float(ind["sma50"].iloc[-1]) if not np.isnan(ind["sma50"].iloc[-1]) else s20
    s200 = float(ind["sma200"].iloc[-1]) if not np.isnan(ind["sma200"].iloc[-1]) else s50
    rsi = float(ind["rsi14"].iloc[-1])
    macd_v = float(ind["macd"].iloc[-1])
    macd_s = float(ind["macd_sig"].iloc[-1])
    macd_h = float(ind["macd_hist"].iloc[-1])
    adx = float(ind["adx14"].iloc[-1])
    p_di = float(ind["plus_di"].iloc[-1])
    m_di = float(ind["minus_di"].iloc[-1])
    vol_r = float(ind["vol_ratio"].iloc[-1])
    wk_bull = bool(ind["weekly_bull"].iloc[-1] > 0.5)
    wk_rsi = float(ind["wk_rsi"].iloc[-1])
    bb_b = float(ind["bb_pct_b"].iloc[-1])

    # 1. Daily Trend (เต็ม 25)
    trend_score = 0.0
    if c > s20:
        trend_score += 7.0
    if c > s50:
        trend_score += 6.0
    if s50 > s200:
        trend_score += 7.0
    if p_di > m_di:
        trend_score += 5.0

    # 2. Weekly MTF (เต็ม 20)
    mtf_score = 0.0
    if wk_bull:
        mtf_score += 12.0
    if 48.0 <= wk_rsi <= 75.0:
        mtf_score += 8.0
    elif wk_rsi > 75.0:
        mtf_score += 5.0

    # 3. Momentum (เต็ม 20)
    mom_score = 0.0
    if macd_v > macd_s:
        mom_score += 8.0
    if macd_h > 0:
        mom_score += 4.0
    if 45.0 <= rsi <= 68.0:
        mom_score += 8.0
    elif 30.0 <= rsi < 45.0 or (68.0 < rsi <= 76.0):
        mom_score += 5.0

    # 4. Regime & Volume (เต็ม 20)
    reg_score = 0.0
    if adx >= 25.0:
        reg_score += 10.0
    elif adx >= 18.0:
        reg_score += 7.0
    else:
        reg_score += 4.0
    if vol_r >= 1.05:
        reg_score += 10.0
    elif vol_r >= 0.85:
        reg_score += 6.0
    else:
        reg_score += 3.0

    # 5. Risk & Strategy Quality (เต็ม 15)
    risk_score = float(np.clip(best_res["sharpe"] * 7.5, 0.0, 10.0))
    if best_res["max_dd_pct"] > -20.0:
        risk_score += 5.0
    elif best_res["max_dd_pct"] > -30.0:
        risk_score += 2.5

    total_score = float(np.clip(trend_score + mtf_score + mom_score + reg_score + risk_score, 0.0, 100.0))

    if total_score >= 82:
        grade = "A+"
    elif total_score >= 72:
        grade = "A"
    elif total_score >= 60:
        grade = "B"
    elif total_score >= 48:
        grade = "C"
    else:
        grade = "D"

    # จำแนก Market Regime
    if adx >= 25.0 and p_di > m_di:
        regime = f"Strong Uptrend (ADX {adx:.0f})"
    elif adx >= 25.0 and p_di <= m_di:
        regime = f"Strong Downtrend (ADX {adx:.0f})"
    elif adx < 20.0:
        if bb_b < 0.25:
            regime = f"Sideway Oversold (ADX {adx:.0f})"
        elif bb_b > 0.75:
            regime = f"Sideway Overbought (ADX {adx:.0f})"
        else:
            regime = f"Range / Sideway (ADX {adx:.0f})"
    else:
        regime = f"Moderate Trend (ADX {adx:.0f})"

    weekly_label = f"Bullish (WK-RSI {wk_rsi:.0f})" if wk_bull else f"Neutral/Bear (WK-RSI {wk_rsi:.0f})"

    return {
        "quant_score": total_score,
        "grade": grade,
        "trend_score": trend_score,
        "mtf_score": mtf_score,
        "mom_score": mom_score,
        "reg_score": reg_score,
        "risk_score": risk_score,
        "regime": regime,
        "weekly_trend": weekly_label,
        "adx14": adx,
    }


# ==========================================
# 4. Signals, ATR Stop, Adaptive Regime-Switching & Auto-Tuning
# ==========================================
def apply_trailing_stop(close: pd.Series, raw_signal: pd.Series, stop_loss: float) -> pd.Series:
    """ตัดสถานะเป็น 0 ทันทีเมื่อราคาหลุด Fixed Trailing Stop (%) นับจากจุดสูงสุดตั้งแต่เข้าถือ"""
    if stop_loss <= 0:
        return raw_signal

    prices = close.to_numpy()
    sigs = raw_signal.to_numpy()
    out = np.zeros(len(prices), dtype=float)

    in_pos = False
    peak_price = 0.0
    for i in range(len(prices)):
        if sigs[i] > 0:
            if not in_pos:
                in_pos = True
                peak_price = prices[i]
                out[i] = 1.0
            else:
                peak_price = max(peak_price, prices[i])
                if prices[i] <= peak_price * (1.0 - stop_loss):
                    in_pos = False
                    out[i] = 0.0
                else:
                    out[i] = 1.0
        else:
            in_pos = False
            peak_price = 0.0
            out[i] = 0.0

    return pd.Series(out, index=close.index)


def apply_atr_vol_target(
    close: pd.Series,
    raw_signal: pd.Series,
    reentry_signal: pd.Series,
    atr: pd.Series,
    roll_vol: pd.Series,
    atr_mult: float = 3.2,
    target_vol: float = 0.25,
) -> tuple[pd.Series, pd.Series]:
    """กลยุทธ์ ATR Chandelier Trailing Stop + Volatility-Targeted Position Sizing"""
    prices = close.to_numpy()
    sigs = raw_signal.to_numpy()
    reentries = reentry_signal.to_numpy()
    atrs = atr.to_numpy()
    vols = roll_vol.to_numpy()

    n = len(prices)
    weights = np.zeros(n, dtype=float)
    stops = np.full(n, np.nan, dtype=float)

    in_pos = False
    stopped_out = False
    peak_price = 0.0
    stop_level = 0.0

    for i in range(n):
        cur_atr = atrs[i] if not np.isnan(atrs[i]) and atrs[i] > 0 else prices[i] * 0.025
        cur_vol = vols[i] if not np.isnan(vols[i]) and vols[i] > 0.01 else target_vol
        raw_w = float(np.clip(target_vol / cur_vol, 0.35, 1.0))
        stepped_w = round(raw_w * 5.0) / 5.0

        if sigs[i] <= 0:
            in_pos = False
            stopped_out = False
            peak_price = 0.0
            stop_level = prices[i] - atr_mult * cur_atr
            weights[i] = 0.0
            stops[i] = stop_level
            continue

        if stopped_out and reentries[i] <= 0:
            stop_level = prices[i] - atr_mult * cur_atr
            weights[i] = 0.0
            stops[i] = stop_level
            continue

        if not in_pos:
            in_pos = True
            stopped_out = False
            peak_price = prices[i]
            stop_level = prices[i] - atr_mult * cur_atr
            weights[i] = stepped_w
            stops[i] = stop_level
        else:
            peak_price = max(peak_price, prices[i])
            candidate_stop = peak_price - atr_mult * cur_atr
            stop_level = max(stop_level, candidate_stop)
            if prices[i] <= stop_level:
                in_pos = False
                stopped_out = True
                weights[i] = 0.0
                stops[i] = stop_level
            else:
                weights[i] = stepped_w
                stops[i] = stop_level

    return pd.Series(weights, index=close.index), pd.Series(stops, index=close.index)


def generate_signals(
    close: pd.Series,
    ind: dict[str, pd.Series],
    stop_loss: float = 0.08,
    atr_mult: float = 3.2,
    target_vol: float = 0.25,
    fee: float = 0.001,
    benchmark_close: pd.Series | None = None,
) -> tuple[dict[str, pd.Series], pd.Series, dict]:
    """
    สร้างสัญญาณสัดส่วนพอร์ต [0.0, 1.0] สำหรับ 4 กลยุทธ์แกนหลัก (v6.0 Lean Profitable Edition):
      1) buy_hold            : ถือยาว 100% (Benchmark มาตรฐาน)
      2) trend_atr_vol       : Core Trend-Following + ATR Chandelier Trailing Stop + Volatility-Targeted Sizing
      3) regime_adaptive_v5  : Core All-Weather (ADX Trend-Following + Sideways Bollinger/RSI Pullback + Bear Cash)
      4) cross_sectional_mom : Core Alpha / Relative Strength Leader (RS เทียบตลาด + Weekly MTF + ATR Vol Sizing)
    """
    import quant_v5_institutional as qv5

    n = len(close)
    if n >= 200:
        sma_trend = (ind["sma50"] > ind["sma200"]) | (ind["weekly_bull"] > 0.5)
    elif n >= 50:
        sma_trend = (ind["sma20"] > ind["sma50"]) | (ind["weekly_bull"] > 0.5)
    else:
        sma_trend = close > close.rolling(10, min_periods=2).mean()

    # 1. Buy & Hold (Benchmark)
    sig_bh = pd.Series(1.0, index=close.index, dtype=float)

    # 2. Core Trend-Following + ATR Chandelier Stop + Volatility-Targeted Sizing (trend_atr_vol)
    momentum_entry = (close > ind["sma20"]) & (ind["macd"] > ind["macd_sig"]) & (ind["rsi14"] < 75.0)
    trend_core = (sma_trend & (ind["rsi14"] < 80.0)) | momentum_entry
    reentry_trigger = (close > ind["sma20"]) & (ind["macd"] > ind["macd_sig"]) & (ind["rsi14"] < 72.0)
    sig_trend_atr, atr_stop_series = apply_atr_vol_target(
        close,
        trend_core.astype(float),
        reentry_trigger.astype(float),
        ind["atr14"],
        ind["roll_vol20"],
        atr_mult=atr_mult,
        target_vol=target_vol,
    )

    # 3. Core All-Weather Regime-Adaptive V5 (regime_adaptive_v5)
    sig_regime_v5 = qv5.build_regime_adaptive_v5_signal(
        close, ind, atr_mult=atr_mult, target_vol=target_vol
    )

    # 4. Core Alpha Relative Strength & Momentum Leader (cross_sectional_mom)
    sig_cs_mom = qv5.build_cross_sectional_mom_signal(
        close, ind, benchmark_close=benchmark_close, atr_mult=atr_mult, target_vol=target_vol
    )

    strategies = {
        "buy_hold": pd.Series(np.clip(sig_bh.to_numpy(), 0.0, 1.0), index=close.index, dtype=float),
        "trend_atr_vol": pd.Series(np.clip(sig_trend_atr.to_numpy(), 0.0, 1.0), index=close.index, dtype=float),
        "regime_adaptive_v5": pd.Series(np.clip(sig_regime_v5.to_numpy(), 0.0, 1.0), index=close.index, dtype=float),
        "cross_sectional_mom": pd.Series(np.clip(sig_cs_mom.to_numpy(), 0.0, 1.0), index=close.index, dtype=float),
    }
    tuned_params = {
        "fast_key": "sma20",
        "atr_mult": atr_mult,
        "adx_thresh": 22.0,
        "target_vol": target_vol,
    }
    return strategies, atr_stop_series, tuned_params


# ==========================================
# 5. Deep Strategy Evaluation & Trade-by-Trade Log Extraction
# ==========================================
def extract_trade_log(
    ticker: str,
    strategy_name: str,
    close: pd.Series,
    raw_signal: pd.Series,
    atr_stop: pd.Series | None = None,
    rsi_series: pd.Series | None = None,
    fee: float = 0.001,
    capital: float = 100000.0,
) -> list[dict]:
    """
    สกัดประวัติการเทรดรายไม้ (Trade-by-Trade Log) พร้อมจุดเข้า-ออก (Buy/Sell Markers) และเหตุผลที่ออก
    """
    pos = raw_signal.shift(1).fillna(0.0) if strategy_name != "buy_hold" else raw_signal.astype(float)
    rets = close.pct_change().fillna(0.0)
    trades_diff = pos.diff().abs().fillna(0.0)
    if strategy_name == "buy_hold" and len(pos) > 0 and pos.iloc[0] > 0:
        trades_diff.iloc[0] = pos.iloc[0]
    strat_rets = (pos * rets) - (trades_diff * fee)

    in_pos = pos > 0.01
    dates = close.index
    prices = close.to_numpy()
    pos_arr = pos.to_numpy()
    s_rets = strat_rets.to_numpy()
    stops_arr = atr_stop.to_numpy() if atr_stop is not None else np.full(len(close), np.nan)
    rsi_arr = rsi_series.to_numpy() if rsi_series is not None else np.full(len(close), 50.0)

    trade_list = []
    i = 0
    n = len(close)
    trade_no = 0

    while i < n:
        if in_pos.iloc[i]:
            trade_no += 1
            start_i = i
            while i < n and in_pos.iloc[i]:
                i += 1
            end_i = min(i - 1, n - 1)

            entry_dt = dates[start_i].strftime("%Y-%m-%d")
            exit_dt = dates[end_i].strftime("%Y-%m-%d")
            entry_price = float(prices[start_i])
            exit_price = float(prices[end_i])
            hold_days = int(end_i - start_i + 1)
            avg_weight = float(pos_arr[start_i : end_i + 1].mean() * 100.0)
            net_ret_pct = float(((1.0 + s_rets[start_i : end_i + 1]).prod() - 1.0) * 100.0)
            pnl_amt = float(capital * (net_ret_pct / 100.0))

            # วิเคราะห์เหตุผลที่ออก (Exit Reason)
            if end_i == n - 1 and in_pos.iloc[-1]:
                reason = "OPEN (กำลังถือครอง)"
            else:
                stop_val = stops_arr[end_i]
                rsi_val = rsi_arr[end_i]
                if not np.isnan(stop_val) and exit_price <= stop_val * 1.01:
                    reason = "ATR Trailing Stop"
                elif rsi_val >= 68.0:
                    reason = "Take Profit (RSI Overbought)"
                elif net_ret_pct < -6.5:
                    reason = "Stop-Loss Cut"
                else:
                    reason = "Trend / Signal Reversal"

            trade_list.append({
                "ticker": ticker,
                "strategy": strategy_name,
                "trade_no": trade_no,
                "entry_date": entry_dt,
                "exit_date": exit_dt,
                "entry_idx": start_i,
                "exit_idx": end_i,
                "hold_days": hold_days,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "avg_weight_pct": avg_weight,
                "net_return_pct": net_ret_pct,
                "pnl_amount": pnl_amt,
                "exit_reason": reason,
            })
        else:
            i += 1

    return trade_list


def _compute_max_streaks(trade_returns: pd.Series) -> tuple[int, int]:
    """คำนวณจำนวนครั้งที่ชนะติดต่อกันสูงสุด (Max Win Streak) และแพ้ติดต่อกันสูงสุด (Max Loss Streak)"""
    max_w, max_l = 0, 0
    cur_w, cur_l = 0, 0
    for r in trade_returns:
        if r > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        else:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
    return max_w, max_l


def evaluate_strategy(
    close: pd.Series,
    raw_signal: pd.Series,
    fee: float = 0.001,
    shift_signal: bool = True,
    ind: dict[str, pd.Series] | None = None,
    benchmark_close: pd.Series | None = None,
) -> dict:
    """คำนวณผลตอบแทนและความเสี่ยงเชิงลึก v5.0 (รวม Dynamic Slippage, Sortino, Omega, Jensen's Alpha, Beta, Expectancy, Payoff Ratio)"""
    import quant_v5_institutional as qv5

    rets = close.pct_change().fillna(0.0)
    pos = raw_signal.shift(1).fillna(0.0) if shift_signal else raw_signal.astype(float)

    trades = pos.diff().abs().fillna(0.0)
    if not shift_signal and pos.iloc[0] > 0:
        trades.iloc[0] = pos.iloc[0]

    # คำนวณ Dynamic Volatility-Adjusted Slippage (หากส่ง ind มาให้ใช้ ATR+Volume, มิฉะนั้นประเมินจาก Rolling Volatility)
    if ind is not None and "atr14" in ind and "vol_ratio" in ind:
        slip_series = qv5.compute_dynamic_slippage_series(close, ind)
    else:
        r_vol = rets.rolling(20, min_periods=3).std().fillna(0.015)
        slip_series = (0.0004 * (r_vol / 0.015).clip(0.5, 2.5)).clip(0.0002, 0.0020)

    total_unit_cost = fee + (slip_series if shift_signal else 0.0)
    gross_rets = pos * rets
    cost_series = trades * total_unit_cost
    strat_rets = gross_rets - cost_series

    gross_equity = (1.0 + gross_rets).cumprod() * 100.0
    equity = (1.0 + strat_rets).cumprod() * 100.0

    n_days = max(len(close), 1)
    gross_ret_pct = (gross_equity.iloc[-1] / 100.0 - 1.0) * 100.0 if len(gross_equity) > 0 else 0.0
    total_ret = (equity.iloc[-1] / 100.0 - 1.0) * 100.0 if len(equity) > 0 else 0.0
    cost_drag_pct = float(max(0.0, gross_ret_pct - total_ret))
    cagr = ((equity.iloc[-1] / 100.0) ** (252.0 / n_days) - 1.0) * 100.0 if equity.iloc[-1] > 0 else -100.0

    ann_ret = strat_rets.mean() * 252.0
    ann_vol = strat_rets.std() * np.sqrt(252.0)
    sharpe = (ann_ret - RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0.0

    downside = strat_rets[strat_rets < 0]
    down_vol = downside.std() * np.sqrt(252.0) if len(downside) > 1 else 0.0
    sortino = (ann_ret - RISK_FREE_RATE) / down_vol if down_vol > 0 else 0.0

    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max * 100.0
    max_dd = dd.min()
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0.0
    recovery_factor = (total_ret / abs(max_dd)) if max_dd < 0 else 0.0

    # สถิติระดับรอบเทรด (Win Rate, Profit Factor, Expectancy, Payoff Ratio, Streaks)
    in_pos = pos > 0.01
    trade_groups = (~in_pos).cumsum()[in_pos]
    if len(trade_groups) > 0:
        trade_returns = strat_rets[in_pos].groupby(trade_groups).apply(lambda r: (1.0 + r).prod() - 1.0)
        trades_count = int(len(trade_returns))
        wins = trade_returns[trade_returns > 0]
        losses = trade_returns[trade_returns <= 0]
        win_rate = float((len(wins) / trades_count) * 100.0)
        avg_win_pct = float(wins.mean() * 100.0) if len(wins) > 0 else 0.0
        avg_loss_pct = float(losses.mean() * 100.0) if len(losses) > 0 else 0.0
        expectancy_pct = float(trade_returns.mean() * 100.0)
        payoff_ratio = float(avg_win_pct / abs(avg_loss_pct)) if avg_loss_pct < 0 else (99.99 if avg_win_pct > 0 else 0.0)
        gross_win = wins.sum()
        gross_loss = abs(losses.sum())
        profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else (99.99 if gross_win > 0 else 0.0)
        max_win_streak, max_loss_streak = _compute_max_streaks(trade_returns)
    else:
        trades_count = 0
        win_rate = 0.0
        avg_win_pct = 0.0
        avg_loss_pct = 0.0
        expectancy_pct = 0.0
        payoff_ratio = 0.0
        profit_factor = 0.0
        max_win_streak, max_loss_streak = 0, 0

    bm_stats = qv5.compute_benchmark_alpha_beta(strat_rets, close, benchmark_close=benchmark_close)

    return {
        "equity": equity,
        "dd": dd,
        "total_ret_pct": float(total_ret),
        "cagr_pct": float(cagr),
        "vol_pct": float(ann_vol * 100.0),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "omega_ratio": float(bm_stats["omega_ratio"]),
        "alpha_pct": float(bm_stats["alpha_pct"]),
        "beta": float(bm_stats["beta"]),
        "information_ratio": float(bm_stats["information_ratio"]),
        "cost_drag_pct": float(cost_drag_pct),
        "calmar": float(calmar),
        "recovery_factor": float(recovery_factor),
        "max_dd_pct": float(max_dd),
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "expectancy_pct": expectancy_pct,
        "payoff_ratio": payoff_ratio,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "trades_count": trades_count,
        "exposure_pct": float(pos.mean() * 100.0),
    }


def pick_best_active_strategy(
    results: dict[str, dict],
    close: pd.Series | None = None,
    signals: dict[str, pd.Series] | None = None,
    fee: float = 0.001,
    train_ratio: float = 0.70,
    ind: dict[str, pd.Series] | None = None,
) -> str:
    """
    เลือกกลยุทธ์ Active (ไม่รวม buy_hold) โดยประเมินเฉพาะบนช่วง In-Sample (70% แรก) เท่านั้น
    เพื่อป้องกัน Selection Bias (ห้ามเลือกผู้ชนะจากผลลัพธ์ Full Period เด็ดขาด)
    """
    candidates = [k for k in results.keys() if k != "buy_hold"]
    if not candidates:
        return "buy_hold"

    if close is not None and signals is not None and len(close) >= 50:
        cut = max(30, int(len(close) * train_ratio))
        c_is = close.iloc[:cut]
        ind_is = {k: v.iloc[:cut] for k, v in ind.items()} if ind is not None else None
        is_scores = {}
        for k in candidates:
            if k in signals:
                r_is = evaluate_strategy(c_is, signals[k].iloc[:cut], fee=fee, shift_signal=True, ind=ind_is)
                is_scores[k] = r_is["sharpe"] + 0.30 * r_is["calmar"]
        if is_scores:
            return max(is_scores.keys(), key=lambda k: is_scores[k])

    return max(candidates, key=lambda k: (results[k]["sharpe"] + 0.30 * results[k]["calmar"]))


# ==========================================
# 6. Daily Signal Scanner & Multi-Factor Position Sizing
# ==========================================
def compute_daily_scan(
    ticker: str,
    close: pd.Series,
    volume: pd.Series,
    ind: dict[str, pd.Series],
    signals: dict[str, pd.Series],
    atr_stop_series: pd.Series,
    best_strat: str,
    best_res: dict,
    tuned_params: dict,
    capital: float = 100000.0,
    risk_pct: float = 0.02,
    atr_mult: float = 3.2,
    target_vol: float = 0.25,
) -> dict:
    """คำนวณสัญญาณซื้อขายวันนี้ คะแนน Quant Score (0-100) Volume Profile POC, Monte Carlo VaR, Half-Kelly และขนาดไม้จริง"""
    last_close = float(close.iloc[-1])
    last_atr = float(ind["atr14"].iloc[-1])
    last_vol = float(ind["roll_vol20"].iloc[-1])
    last_rsi = float(ind["rsi14"].iloc[-1])
    last_vwap20 = float(ind["vwap20"].iloc[-1])

    q_meta = compute_quant_score_and_regime(close, ind, best_res)
    vp_meta = compute_volume_profile(close, volume)
    mc_meta = run_monte_carlo_and_var(close, signals[best_strat], shift_signal=(best_strat != "buy_hold"))
    half_kelly_pct = compute_half_kelly_pct(best_res["win_rate_pct"], best_res["payoff_ratio"])

    import quant_v4_modules as qv4
    import quant_v5_institutional as qv5
    ml_meta = qv4.compute_ml_meta_and_walk_forward(close, ind, signals[best_strat])
    xai_meta = qv5.compute_xai_feature_importance(close, ind)
    fund_meta = qv4.fetch_fundamentals_and_sentiment(ticker)
    macro_meta = qv4.get_macro_vix_regime()

    best_sig_series = signals[best_strat]
    curr_w = float(best_sig_series.iloc[-1])
    prev_w = float(best_sig_series.iloc[-2]) if len(best_sig_series) > 1 else 0.0

    raw_stop = float(atr_stop_series.iloc[-1])
    if np.isnan(raw_stop) or raw_stop <= 0 or raw_stop >= last_close:
        stop_price = max(0.01, last_close - atr_mult * last_atr)
    else:
        stop_price = raw_stop

    stop_dist = max(last_close - stop_price, last_close * 0.01)
    stop_dist_pct = (stop_dist / last_close) * 100.0

    # 1) Risk-Per-Trade Sizing
    risk_budget = capital * risk_pct
    risk_based_value = risk_budget / (stop_dist / last_close)
    risk_based_weight = min(1.0, risk_based_value / max(capital, 1.0))

    # 2) Volatility Target Sizing
    vol_based_weight = float(np.clip(target_vol / max(last_vol, 0.05), 0.20, 1.0))

    # 3) Half-Kelly Cap (ถ้ามีสถิติเทรด >= 3 ไม้และ Half-Kelly > 10% นำมาช่วยถ่วงน้ำหนัก)
    kelly_w = (half_kelly_pct / 100.0) if best_res["trades_count"] >= 3 and half_kelly_pct > 10.0 else vol_based_weight
    rec_weight = min(risk_based_weight, vol_based_weight, max(0.15, kelly_w))

    if curr_w > 0 and prev_w == 0:
        action = "BUY (เข้าซื้อใหม่)"
        order_side = "BUY"
        final_weight = rec_weight * curr_w
    elif curr_w > 0 and prev_w > 0:
        if curr_w < prev_w - 0.05:
            action = "HOLD/TRIM (ถือ+ลดไม้)"
        else:
            action = "HOLD (ถือรันเทรนด์)"
        order_side = "BUY"
        final_weight = rec_weight * curr_w
    elif curr_w == 0 and prev_w > 0:
        action = "SELL (ออก/ตัดขาดทุน)"
        order_side = "SELL"
        final_weight = 0.0
    else:
        action = "WAIT (ถือเงินสด)"
        order_side = "NONE"
        final_weight = 0.0

    alloc_pct = final_weight * 100.0
    alloc_amount = capital * final_weight
    shares = alloc_amount / last_close if last_close > 0 else 0.0
    tuned_str = f"{tuned_params['fast_key'].upper()} | ATR {tuned_params['atr_mult']}x | ADX>{tuned_params['adx_thresh']:.0f}"

    scan_out = {
        "date": close.index[-1].strftime("%Y-%m-%d"),
        "ticker": ticker,
        "best_strategy": best_strat,
        "quant_score": q_meta["quant_score"],
        "grade": q_meta["grade"],
        "regime": q_meta["regime"],
        "weekly_trend": q_meta["weekly_trend"],
        "action": action,
        "order_side": order_side,
        "close": last_close,
        "vwap20": last_vwap20,
        "poc_price": vp_meta["poc_price"],
        "vah_price": vp_meta["vah_price"],
        "val_price": vp_meta["val_price"],
        "vp_status": vp_meta["vp_status"],
        "rsi14": last_rsi,
        "adx14": q_meta["adx14"],
        "ann_vol_pct": last_vol * 100.0,
        "atr14": last_atr,
        "stop_price": stop_price,
        "stop_dist_pct": stop_dist_pct,
        "half_kelly_pct": half_kelly_pct,
        "alloc_pct": alloc_pct,
        "alloc_amount": alloc_amount,
        "shares": shares,
        "risk_amount": alloc_amount * (stop_dist_pct / 100.0),
        "var_95_pct": mc_meta["var_95_pct"],
        "cvar_95_pct": mc_meta["cvar_95_pct"],
        "mc_median_ret_pct": mc_meta["mc_median_ret_pct"],
        "mc_p05_ret_pct": mc_meta["mc_p05_ret_pct"],
        "mc_p95_ret_pct": mc_meta["mc_p95_ret_pct"],
        "mc_prob_profit_pct": mc_meta["mc_prob_profit_pct"],
        "mc_risk_of_ruin_pct": mc_meta["mc_risk_of_ruin_pct"],
        "tuned_params_str": tuned_str,
        "trend_score": q_meta["trend_score"],
        "mtf_score": q_meta["mtf_score"],
        "mom_score": q_meta["mom_score"],
        "reg_score": q_meta["reg_score"],
        "risk_score": q_meta["risk_score"],
        "ml_win_prob_pct": ml_meta["ml_win_prob_pct"],
        "ml_oos_accuracy_pct": ml_meta["ml_oos_accuracy_pct"],
        "wfo_pass_pct": ml_meta["wfo_pass_pct"],
        "wfo_windows_str": ml_meta["wfo_windows_str"],
        "xai_features": json.dumps(xai_meta["xai_features"], ensure_ascii=False),
        "xai_impacts": json.dumps(xai_meta["xai_impacts"]),
        "top_bullish_driver": xai_meta["top_bullish_driver"],
        "top_risk_driver": xai_meta["top_risk_driver"],
        "sortino": best_res.get("sortino", 0.0),
        "omega_ratio": best_res.get("omega_ratio", 1.0),
        "alpha_pct": best_res.get("alpha_pct", 0.0),
        "beta": best_res.get("beta", 1.0),
        "cost_drag_pct": best_res.get("cost_drag_pct", 0.0),
        "macro_vix": macro_meta["vix"],
        "macro_vix_label": macro_meta["macro_label"],
        "fundamental_str": fund_meta["fundamental_str"],
        "news_sentiment": fund_meta["news_sentiment"],
        "news_sentiment_label": fund_meta["news_sentiment_label"],
        "top_headline": fund_meta["top_headline"],
        "opt_alloc_pct": alloc_pct,
        "opt_alloc_amount": alloc_amount,
        "opt_shares": shares,
    }
    return qv4.compute_sniper_and_tp_levels(scan_out)


def print_daily_scan_table(scan_rows: list[dict], capital: float, risk_pct: float):
    """แสดงตาราง Daily Actionable Scanner พร้อม Quant Score & Market Regime"""
    if not scan_rows:
        return
    print("\n" + "=" * 142)
    print(
        f"=== DAILY ACTIONABLE SIGNAL, QUANT SCORE & POSITION SIZING (พอร์ต: {capital:,.0f} | Max Risk/Trade: {risk_pct*100:.1f}%) ==="
    )
    header = (
        f"{'Ticker':<7} | {'Score':<8} | {'Market Regime':<23} | {'Weekly MTF':<19} | {'Best Strategy':<18} | "
        f"{'Action วันนี้':<18} | {'Close':>9} | {'Stop-Loss':>9} | {'Alloc%':>6} | {'เงินลงทุน':>9}"
    )
    print(header)
    print("-" * len(header))
    for s in scan_rows:
        score_str = f"{s['quant_score']:>3.0f} ({s['grade']:<2})"
        print(
            f"{s['ticker']:<7} | {score_str:<8} | {s['regime']:<23} | {s['weekly_trend']:<19} | {s['best_strategy']:<18} | "
            f"{s['action']:<18} | {s['close']:>9,.2f} | {s['stop_price']:>9,.2f} | {s['alloc_pct']:>5.1f}% | {s['alloc_amount']:>9,.0f}"
        )
    print("=" * 142)


# ==========================================
# 7. SQLite Database & Chart Generation
# ==========================================
def ensure_db_schema(conn: sqlite3.Connection):
    """สร้างตารางและอัปเกรดคอลัมน์อัตโนมัติหากเปิดไฟล์ runs.db เดิม"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            period TEXT,
            start_date TEXT,
            end_date TEXT,
            total_return_pct REAL,
            volatility_annual_pct REAL,
            max_drawdown_pct REAL,
            signal TEXT,
            chart_paths TEXT,
            created_at TEXT
        )
    """)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    phase2_cols = {
        "sharpe_ratio": "REAL",
        "sortino_ratio": "REAL",
        "rsi_14": "REAL",
        "strat_return_pct": "REAL",
        "strat_max_dd_pct": "REAL",
        "strat_sharpe": "REAL",
        "win_rate_pct": "REAL",
        "trades_count": "INTEGER",
        "ai_summary": "TEXT",
    }
    for col, col_type in phase2_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_type}")
    conn.commit()


def log_backtest_to_db(
    db_path: str,
    ticker: str,
    period: str,
    start: str,
    end: str,
    rsi_last: float,
    bh: dict,
    best_name: str,
    best_res: dict,
    scan_info: dict,
    chart_path: str,
    ai_ans: str | None = None,
):
    """บันทึกผลเปรียบเทียบ Buy & Hold คู่กับ Best Active Strategy และ Quant Score ลง runs.db"""
    conn = sqlite3.connect(db_path)
    ensure_db_schema(conn)
    signal_label = (
        f"Score:{scan_info['quant_score']:.0f}({scan_info['grade']}) | Best:{best_name} | "
        f"{scan_info['action']} (Stop {scan_info['stop_price']:.2f})"
    )
    conn.execute(
        """
        INSERT INTO runs (
            ticker, period, start_date, end_date,
            total_return_pct, volatility_annual_pct, max_drawdown_pct,
            sharpe_ratio, sortino_ratio, rsi_14,
            strat_return_pct, strat_max_dd_pct, strat_sharpe, win_rate_pct, trades_count,
            signal, chart_paths, ai_summary, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker, period, start, end,
            bh["total_ret_pct"], bh["vol_pct"], bh["max_dd_pct"],
            bh["sharpe"], bh["sortino"], rsi_last,
            best_res["total_ret_pct"], best_res["max_dd_pct"], best_res["sharpe"],
            best_res["win_rate_pct"], best_res["trades_count"],
            signal_label, chart_path, ai_ans, datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def show_history(db_path: str, limit: int = 12):
    """แสดงประวัติการรันจากฐานข้อมูล SQLite"""
    if not os.path.exists(db_path):
        print(f"[Info] ยังไม่มีไฟล์ฐานข้อมูล {db_path}")
        return
    conn = sqlite3.connect(db_path)
    ensure_db_schema(conn)
    rows = conn.execute(
        """
        SELECT id, ticker, period, total_return_pct, max_drawdown_pct, sharpe_ratio,
               strat_return_pct, strat_max_dd_pct, strat_sharpe, win_rate_pct, signal
        FROM runs ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"[Info] ยังไม่มีประวัติใน {db_path}")
        return

    print(f"\n=== ประวัติการรันล่าสุดจาก {db_path} ({len(rows)} รายการ) ===")
    header = (
        f"{'ID':>3} | {'Ticker':<8} | {'Per':<4} | {'B&H Ret':>8} | {'B&H DD':>8} | "
        f"{'StratRet':>8} | {'StratDD':>8} | {'StShrp':>6} | {'Win%':>6} | Signal / Quant Score"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        s_ret = f"{r[6]:>+7.2f}%" if r[6] is not None else "    N/A "
        s_dd = f"{r[7]:>7.2f}%" if r[7] is not None else "    N/A "
        s_sh = f"{r[8]:>6.2f}" if r[8] is not None else "   N/A"
        w_rt = f"{r[9]:>5.1f}%" if r[9] is not None else "  N/A "
        print(
            f"{r[0]:>3} | {r[1]:<8} | {r[2]:<4} | {r[3]:>+7.2f}% | {r[4]:>7.2f}% | "
            f"{s_ret} | {s_dd} | {s_sh} | {w_rt} | {r[10]}"
        )


def make_comparison_chart(ticker: str, period: str, results: dict[str, dict], out_dir: str) -> str:
    """สร้างกราฟเปรียบเทียบ Equity Curve และ Drawdown ของทั้ง 7 กลยุทธ์"""
    os.makedirs(out_dir, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 7.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]}
    )

    colors = {
        "buy_hold": ("#666666", "--"),
        "trend_atr_vol": ("#0A84FF", "-"),
        "regime_adaptive_v5": ("#30D158", "-"),
        "cross_sectional_mom": ("#BF5AF2", "-"),
    }

    for name, res in results.items():
        col, ls = colors.get(name, ("#000000", "-"))
        lw = 2.2 if name != "buy_hold" else 1.4
        label = f"{name} ({res['total_ret_pct']:+.1f}% | Shp {res['sharpe']:.2f})"
        ax1.plot(res["equity"].index, res["equity"].values, label=label, color=col, linestyle=ls, linewidth=lw)
        ax2.plot(res["dd"].index, res["dd"].values, label=f"{name} ({res['max_dd_pct']:.1f}%)", color=col, linestyle=ls, linewidth=1.1)

    ax1.set_title(f"{ticker} Multi-Strategy Backtest ({period}) — incl. Adaptive Quant Pro", fontsize=12)
    ax1.set_ylabel("Portfolio Value (Base 100)")
    ax1.legend(loc="upper left", fontsize=8, ncol=2)
    ax1.grid(True, alpha=0.3)

    ax2.set_xlabel("Date")
    ax2.set_ylabel("Drawdown (%)")
    ax2.legend(loc="lower left", fontsize=7.5, ncol=2)
    ax2.grid(True, alpha=0.3)

    fig.autofmt_xdate()
    fig.tight_layout()
    safe_ticker = ticker.replace("^", "")
    path = os.path.join(out_dir, f"{safe_ticker}_{period}_compare.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def print_summary_table(ticker: str, start: str, end: str, n_days: int, results: dict[str, dict], label: str = "Full"):
    """แสดงตารางสรุปผลเปรียบเทียบทุกกลยุทธ์ พร้อม Expectancy และ Streak"""
    print(f"\n=== {ticker} [{label}] ({start} ถึง {end} | {n_days} วันทำการ) ===")
    header = (
        f"{'Strategy':<18} | {'Ret%':>8} | {'CAGR%':>7} | {'MaxDD%':>8} | "
        f"{'Sharpe':>6} | {'Calmar':>6} | {'Win%':>6} | {'Expect%':>8} | {'PF':>5} | {'W/L Strk':>8} | {'Trades':>6}"
    )
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        strk = f"{r['max_win_streak']}W/{r['max_loss_streak']}L"
        print(
            f"{name:<18} | {r['total_ret_pct']:>+7.2f}% | {r['cagr_pct']:>+6.2f}% | {r['max_dd_pct']:>7.2f}% | "
            f"{r['sharpe']:>6.2f} | {r['calmar']:>6.2f} | {r['win_rate_pct']:>5.1f}% | {r['expectancy_pct']:>+7.2f}% | "
            f"{r['profit_factor']:>5.2f} | {strk:>8} | {r['trades_count']:>6d}"
        )


def print_cross_ticker_summary(winners: list[dict]):
    """แสดงตารางสรุปเปรียบเทียบกลยุทธ์ที่ดีที่สุดของแต่ละสินทรัพย์"""
    if len(winners) <= 1:
        return
    print("\n" + "=" * 124)
    print("=== สรุปเปรียบเทียบ Best Active Strategy ข้ามสินทรัพย์ (Multi-Ticker Benchmark) ===")
    header = (
        f"{'Ticker':<8} | {'B&H Ret%':>9} | {'B&H DD%':>8} | {'B&H Shp':>7} || "
        f"{'Best Strategy':<18} | {'StratRet%':>9} | {'StratDD%':>8} | {'StratShp':>8} | {'OOS Shp':>7} | {'Score'}"
    )
    print(header)
    print("-" * len(header))
    for w in winners:
        oos_str = f"{w['oos_sharpe']:>7.2f}" if w.get("oos_sharpe") is not None else "    N/A"
        print(
            f"{w['ticker']:<8} | {w['bh_ret']:>+8.2f}% | {w['bh_dd']:>7.2f}% | {w['bh_sharpe']:>7.2f} || "
            f"{w['best_strategy']:<18} | {w['strat_ret']:>+8.2f}% | {w['strat_dd']:>7.2f}% | {w['strat_sharpe']:>8.2f} | "
            f"{oos_str} | {w['quant_score']:.0f} ({w['grade']})"
        )
    print("=" * 124)


# ==========================================
# 8. Runner & CLI Entrypoint
# ==========================================
def run_for_ticker(
    ticker: str,
    period: str,
    fee: float,
    stop_loss: float,
    atr_mult: float,
    target_vol: float,
    capital: float,
    risk_pct: float,
    split: float | None,
    out_dir: str,
    db_path: str | None = None,
    use_ai: bool = False,
    model_key: str = "llama3.1-8b",
) -> tuple[list[dict], dict, dict, list[dict]]:
    """รัน Backtest 7 กลยุทธ์ + Auto-Tune + คำนวณ Daily Scan + สกัด Trade Log รายไม้"""
    ohlcv = fetch_ohlcv(ticker, period)
    close = ohlcv["close"]
    ind = compute_indicators(ohlcv)
    signals, atr_stop_series, tuned_params = generate_signals(
        close, ind, stop_loss=stop_loss, atr_mult=atr_mult, target_vol=target_vol, fee=fee
    )

    results = {}
    rows = []
    for name, sig in signals.items():
        res = evaluate_strategy(close, sig, fee=fee, shift_signal=(name != "buy_hold"))
        results[name] = res
        rows.append({
            "ticker": ticker,
            "period": period,
            "segment": "full",
            "strategy": name,
            **{k: v for k, v in res.items() if k not in ("equity", "dd")},
        })

    start = close.index[0].strftime("%Y-%m-%d")
    end = close.index[-1].strftime("%Y-%m-%d")
    print_summary_table(ticker, start, end, len(close), results, label="Full")

    chart_path = make_comparison_chart(ticker, period, results, out_dir)
    print(f"กราฟเปรียบเทียบ: {chart_path}")

    oos_results = None
    if split and 0.1 < split < 0.9:
        cut = int(len(close) * split)
        for seg_name, seg_key, sl in [
            ("In-Sample", "in_sample", slice(None, cut)),
            ("Out-of-Sample", "out_of_sample", slice(cut, None)),
        ]:
            c_seg = close.iloc[sl]
            seg_res = {}
            for name, sig in signals.items():
                r_seg = evaluate_strategy(c_seg, sig.iloc[sl], fee=fee, shift_signal=(name != "buy_hold"))
                seg_res[name] = r_seg
                rows.append({
                    "ticker": ticker,
                    "period": period,
                    "segment": seg_key,
                    "strategy": name,
                    **{k: v for k, v in r_seg.items() if k not in ("equity", "dd")},
                })
            if seg_key == "out_of_sample":
                oos_results = seg_res
            print_summary_table(
                ticker,
                c_seg.index[0].strftime("%Y-%m-%d"),
                c_seg.index[-1].strftime("%Y-%m-%d"),
                len(c_seg),
                seg_res,
                label=seg_name,
            )

    best_strat = pick_best_active_strategy(results, close=close, signals=signals, fee=fee, train_ratio=split or 0.70, ind=ind)
    best_res = results[best_strat]
    bh_res = results["buy_hold"]

    # คำนวณและแสดงผล Backtest จริงของทั้ง 6 ปุ่มโหมดบน GUI (1..6)
    import quant_v5_institutional as qv5
    bm_close = qv5.get_benchmark_close(period, "^GSPC")
    six_modes = qv5.evaluate_six_button_modes(
        close, ohlcv["volume"], ind, signals, evaluate_strategy, best_strat, fee=fee, benchmark_close=bm_close
    )
    print(f"\n=== ผล Backtest การใช้งานทั้ง 6 ปุ่มโหมดบน GUI สำหรับ {ticker} (IS Winner: {best_strat}) ===")
    m_hdr = f"{'Button Mode (1..6)':<38} | {'Full Ret%':>9} | {'OOS Ret(30%)':>12} | {'MaxDD%':>7} | {'Sharpe':>6} | {'OOS Shp':>7} | {'Sortino':>7} | {'Win%':>6} | {'PF':>5}"
    print(m_hdr)
    print("-" * len(m_hdr))
    for m_k, m_v in six_modes.items():
        fr = m_v["full"]
        print(
            f"{m_v['title']:<38} | {fr['total_ret_pct']:>+8.2f}% | {m_v['oos_ret_pct']:>+11.2f}% | "
            f"{fr['max_dd_pct']:>6.2f}% | {fr['sharpe']:>6.2f} | {m_v['oos_sharpe']:>7.2f} | "
            f"{fr['sortino']:>7.2f} | {fr['win_rate_pct']:>5.1f}% | {fr['profit_factor']:>5.2f}"
        )

    # รัน Rolling Walk-Forward Validation Gate (12M Train -> 3M OOS -> Roll Forward)
    wfo_gate = qv5.run_rolling_walk_forward_gate(
        close, ind, signals, evaluate_strategy, train_days=252, test_days=63, fee=fee, benchmark_close=bm_close
    )
    gate_badge = "✅ PASS" if wfo_gate["gate_passed"] else f"❌ FAIL ({', '.join(wfo_gate['failed_reasons'])})"
    print(
        f"\n>>> [Rolling Walk-Forward Gate ({wfo_gate['n_folds']} Folds: {wfo_gate['train_days']}d Train -> {wfo_gate['test_days']}d OOS)] "
        f"{ticker}: OOS Ret {wfo_gate['oos_total_ret_pct']:+.2f}% | Sharpe {wfo_gate['oos_sharpe']:.2f} | "
        f"PF {wfo_gate['oos_profit_factor']:.2f} | MaxDD {wfo_gate['oos_max_dd_pct']:.2f}% => {gate_badge}"
    )

    # สกัดประวัติเทรดรายไม้ (Trade-by-Trade Log) ของกลยุทธ์ที่ชนะและ adaptive_quant_pro
    trade_logs = extract_trade_log(
        ticker=ticker,
        strategy_name=best_strat,
        close=close,
        raw_signal=signals[best_strat],
        atr_stop=atr_stop_series,
        rsi_series=ind["rsi14"],
        fee=fee,
        capital=capital,
    )

    scan_info = compute_daily_scan(
        ticker=ticker,
        close=close,
        volume=ohlcv["volume"],
        ind=ind,
        signals=signals,
        atr_stop_series=atr_stop_series,
        best_strat=best_strat,
        best_res=best_res,
        tuned_params=tuned_params,
        capital=capital,
        risk_pct=risk_pct,
        atr_mult=atr_mult,
        target_vol=target_vol,
    )

    ai_ans = None
    if use_ai:
        print(f">>> กำลังให้ Ollama ({model_key}) วิเคราะห์กลยุทธ์และแผนเทรดวันนี้ของ {ticker} ...")
        prompt = build_ai_prompt(ticker, period, results, best_strat, scan_info, oos_results)
        ai_ans = query_llm(prompt, model_key=model_key)
        print(f"\n=== บทวิเคราะห์ AI สำหรับ {ticker} ({model_key}) ===")
        print(ai_ans)

    if db_path:
        rsi_last = float(ind["rsi14"].iloc[-1])
        log_backtest_to_db(
            db_path, ticker, period, start, end, rsi_last, bh_res, best_strat, best_res, scan_info, chart_path, ai_ans
        )

    winner_info = {
        "ticker": ticker,
        "bh_ret": bh_res["total_ret_pct"],
        "bh_dd": bh_res["max_dd_pct"],
        "bh_sharpe": bh_res["sharpe"],
        "best_strategy": best_strat,
        "strat_ret": best_res["total_ret_pct"],
        "strat_dd": best_res["max_dd_pct"],
        "strat_sharpe": best_res["sharpe"],
        "oos_sharpe": oos_results[best_strat]["sharpe"] if oos_results else None,
        "quant_score": scan_info["quant_score"],
        "grade": scan_info["grade"],
    }
    return rows, winner_info, scan_info, trade_logs


def run_universe_scanner_cli(period: str = "2y", top_n: int = 5, hold_buffer: int = 15, out_dir: str = "output_backtest"):
    """รันสแกนตะกร้าหุ้นสภาพคล่องสูง 30 ตัว + Dual-Momentum Safe-Haven (GLD/SHY) + Portfolio Backtest + Go/No-Go Gate"""
    import quant_v5_institutional as qv5

    print(f"\n>>> กำลังโหลดข้อมูลตะกร้าหุ้นสภาพคล่องสูง {len(qv5.LIQUID_UNIVERSE_30)} ตัว + SPY & Safe-Haven (GLD/SHY) ({period}) ...")
    spy_ohlcv = fetch_ohlcv("SPY", period)
    spy_close = spy_ohlcv["close"]

    safe_haven_map = {}
    for sh_sym in qv5.SAFE_HAVEN_ASSETS:
        try:
            safe_haven_map[sh_sym] = fetch_ohlcv(sh_sym, period)["close"]
        except Exception as e:
            print(f"  [Skip Safe-Haven] {sh_sym}: {e}", file=sys.stderr)

    close_map = {}
    for sym in qv5.LIQUID_UNIVERSE_30:
        try:
            close_map[sym] = fetch_ohlcv(sym, period)["close"]
        except Exception as e:
            print(f"  [Skip] {sym}: {e}", file=sys.stderr)

    scan = qv5.scan_cross_sectional_universe(
        close_map, spy_close, top_n=top_n, hold_buffer=hold_buffer, safe_haven_map=safe_haven_map
    )
    print("\n" + "=" * 116)
    print(f"=== CROSS-SECTIONAL UNIVERSE SCANNER ({scan['universe_count']} หุ้น) | {scan['spy_regime_label']} ===")
    hdr = f"{'Rank':>4} | {'Ticker':<6} | {'Close':>9} | {'6M Ret%':>8} | {'3M Ret%':>8} | {'Vol20%':>7} | {'RS vs SPY':>9} | {'RiskAdjMom':>10} | {'Weight%':>7} | Status"
    print(hdr)
    print("-" * len(hdr))
    for r in scan["rankings"][:15]:
        print(
            f"#{r['rank']:>3d} | {r['ticker']:<6} | {r['close']:>9,.2f} | {r['ret_126_pct']:>+7.2f}% | "
            f"{r['ret_63_pct']:>+7.2f}% | {r['vol_20_pct']:>6.1f}% | {r['rs_vs_spy_pct']:>+8.2f}% | "
            f"{r['risk_adj_mom']:>+10.2f} | {r['target_weight_pct']:>6.1f}% | {r['status']}"
        )
    sh_str = ", ".join(f"{k}: {v:.1f}%" for k, v in scan.get("safe_haven_alloc", {}).items()) or "None"
    print(f"Safe-Haven Rotation: [{sh_str}] | Cash Reserve: {scan['cash_weight_pct']:.1f}% | Equity Leaders: {scan['allocated_count']}/{top_n}")
    print("=" * 116)

    bt = qv5.backtest_cross_sectional_portfolio(
        close_map, spy_close, top_n=top_n, hold_buffer=hold_buffer, safe_haven_map=safe_haven_map
    )
    gate_txt = "✅ PASS (พร้อมเข้าสู่ Paper Execution)" if bt["gate_passed"] else f"❌ FAIL ({', '.join(bt['failed_reasons'])})"
    print(
        f"\n=== CROSS-SECTIONAL PORTFOLIO BACKTEST ({bt['start_date']} ถึง {bt['end_date']} | {bt['eval_days']} วันทำการ | Rebalance 21d + Fee/Slippage) ===\n"
        f"• Portfolio Net Return : {bt['total_ret_pct']:+.2f}%  (CAGR: {bt['cagr_pct']:+.2f}% | SPY Benchmark: {bt['spy_ret_pct']:+.2f}% | Excess: {bt['excess_ret_pct']:+.2f}%)\n"
        f"• Risk Metrics         : Sharpe {bt['sharpe']:.2f} | Sortino {bt['sortino']:.2f} | MaxDD {bt['max_dd_pct']:.2f}% | Profit Factor {bt['profit_factor']:.2f}\n"
        f"• Execution Realism    : Cost Drag (Fee+Slip): -{bt['cost_drag_pct']:.2f}% | Avg Exposure: {bt['avg_exposure_pct']:.1f}% | Period WinRate: {bt['period_win_rate_pct']:.1f}%\n"
        f"• Go/No-Go Gate        : {gate_txt}\n"
    )
    os.makedirs(out_dir, exist_ok=True)
    rank_csv = os.path.join(out_dir, "universe_rankings.csv")
    pd.DataFrame(scan["rankings"]).to_csv(rank_csv, index=False, encoding="utf-8-sig")
    print(f"บันทึกตารางจัดอันดับ Universe เรียบร้อย: {rank_csv}")
    return scan, bt


def main():
    p = argparse.ArgumentParser(description="AI Quant Backtesting Engine v7.0-A (Cross-Sectional Universe & Rolling WFO Gate)")
    p.add_argument("tickers", nargs="*", default=["^NDX"], help="รายชื่อหุ้น/ดัชนี เช่น ^NDX NVDA AAPL BTC-USD")
    p.add_argument("-p", "--period", default="2y", help="ช่วงเวลา: 6mo, 1y, 2y, 5y, max")
    p.add_argument("--fee", type=float, default=0.001, help="ค่าธรรมเนียมต่อครั้ง (0.001 = 0.1%%)")
    p.add_argument("--stop-loss", type=float, default=0.08, help="Fixed Trailing Stop-Loss (0.08 = 8%%)")
    p.add_argument("--atr-mult", type=float, default=3.2, help="ตัวคูณ ATR สำหรับ ATR Trailing Stop (เช่น 3.2)")
    p.add_argument("--target-vol", type=float, default=0.25, help="เป้าหมายความผันผวนพอร์ตต่อปี (0.25 = 25%%)")
    p.add_argument("--capital", type=float, default=100000.0, help="เงินทุนพอร์ตสำหรับคำนวณขนาดไม้ (เช่น 100000)")
    p.add_argument("--risk-pct", type=float, default=0.02, help="ความเสี่ยงสูงสุดต่อเทรด (0.02 = 2%% ของพอร์ต)")
    p.add_argument("--scan", action="store_true", help="แสดงตาราง Daily Signal Scanner & Position Sizing")
    p.add_argument("--universe-scan", action="store_true", help="สแกนตะกร้าหุ้นสภาพคล่องสูง 30 ตัวแบบ Cross-Sectional + Portfolio Backtest")
    p.add_argument("--top-n", type=int, default=5, help="จำนวนหุ้น Top Leaders ที่ถือในพอร์ต Cross-Sectional (ค่าเริ่มต้น 5)")
    p.add_argument("--split", type=float, default=None, help="สัดส่วน Train/Test เช่น 0.7 (70%% แรก vs 30%% หลัง)")
    p.add_argument("-o", "--out", default="output_backtest", help="โฟลเดอร์เก็บกราฟ PNG และไฟล์ CSV")
    p.add_argument("--csv", default=None, help="บันทึกตารางผล Backtest เป็นไฟล์ CSV")
    p.add_argument("--db", default="runs.db", help="ไฟล์ฐานข้อมูล SQLite (ตั้งเป็น '' หากไม่ต้องการบันทึก)")
    p.add_argument("--history", action="store_true", help="แสดงประวัติการรันจากฐานข้อมูล SQLite")
    p.add_argument("--ai", action="store_true", help="เปิดใช้งานการวิเคราะห์ด้วย Ollama AI")
    p.add_argument("--model", default="llama3.1-8b", help="คีย์โมเดลในโฟลเดอร์ /model")
    args = p.parse_args()

    if args.history:
        show_history(args.db)
        return

    if args.universe_scan:
        run_universe_scanner_cli(period=args.period, top_n=args.top_n, out_dir=args.out)
        return

    all_rows = []
    winners = []
    scan_rows = []
    all_trade_logs = []
    for t in args.tickers:
        try:
            rows, win_info, scan_info, t_logs = run_for_ticker(
                t,
                args.period,
                args.fee,
                args.stop_loss,
                args.atr_mult,
                args.target_vol,
                args.capital,
                args.risk_pct,
                args.split,
                args.out,
                db_path=args.db if args.db else None,
                use_ai=args.ai,
                model_key=args.model,
            )
            all_rows.extend(rows)
            winners.append(win_info)
            scan_rows.append(scan_info)
            all_trade_logs.extend(t_logs)
        except Exception as e:
            print(f"[Error] {t}: {e}", file=sys.stderr)

    print_cross_ticker_summary(winners)

    if args.scan or len(scan_rows) >= 1:
        try:
            import quant_v4_modules as qv4
            import hermes_bridge as hb
            close_map = {s["ticker"]: fetch_ohlcv(s["ticker"], args.period)["close"] for s in scan_rows}
            scan_rows = qv4.optimize_portfolio_weights(scan_rows, close_map, total_capital=args.capital)
            hb.sync_to_hermes_memory(scan_rows)
        except Exception:
            pass
        print_daily_scan_table(scan_rows, args.capital, args.risk_pct)
        os.makedirs(args.out, exist_ok=True)
        scan_csv_path = os.path.join(args.out, "daily_scan.csv")
        pd.DataFrame(scan_rows).to_csv(scan_csv_path, index=False, encoding="utf-8-sig")
        print(f"บันทึกตารางสัญญาณรายวัน (Daily Scanner) & ซิงก์ Hermes Agent เรียบร้อย: {scan_csv_path}")

    if all_trade_logs:
        os.makedirs(args.out, exist_ok=True)
        trade_csv_path = os.path.join(args.out, "trade_log.csv")
        pd.DataFrame(all_trade_logs).to_csv(trade_csv_path, index=False, encoding="utf-8-sig")
        print(f"บันทึกประวัติเทรดรายไม้ (Trade-by-Trade Log) เรียบร้อย: {trade_csv_path}")

    if args.csv and all_rows:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        pd.DataFrame(all_rows).to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"บันทึกตารางสรุปผล Backtest CSV เรียบร้อย: {args.csv}")

    if args.db and winners:
        print(f"บันทึกผลลงฐานข้อมูล SQLite เรียบร้อย: {args.db} (ดูย้อนหลังด้วย --history)")


if __name__ == "__main__":
    main()
