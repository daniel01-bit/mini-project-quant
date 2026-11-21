#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quant_v5_institutional.py — โมดูลยกระดับ AI Quant Workbench v5.0 (Institutional & Portfolio-Ready Edition):
  1) Dynamic Volatility-Adjusted Slippage & Commission Engine:
     - จำลองต้นทุนแฝงในการเทรดจริง (Base Commission + Volatility & Volume Impact Slippage)
  2) Institutional Benchmark Analytics (vs. S&P 500 ^GSPC / ^NDX):
     - คำนวณ Jensen's Alpha (α), Market Beta (β), Sortino Ratio, Omega Ratio และ Information Ratio
  3) Regime-Adaptive V5 Strategy (regime_adaptive_v5):
     - สลับโหมดอัตโนมัติระหว่าง Trend-Following (เมื่อ ADX มีเทรนด์ชัด), Mean-Reversion Pullback (เมื่อตลาด Sideways)
       และถือเงินสด 100% (เมื่อเป็นขาลงความผันผวนสูง) เพื่อแก้ปัญหา Whipsaw ในตลาด Sideways
  4) Explainable AI (XAI) Feature Attribution:
     - แยกส่วนประกอบน้ำหนัก (Feature Importance & Attribution) ของโมเดล L2 Logistic Meta-Model ทั้ง 7 ปัจจัย
  5) Pre-Trade Institutional Risk Gate:
     - ตรวจสอบเพดานความเสี่ยงก่อนส่งคำสั่งซื้อขายจริง (Max Single Allocation, Stop-Loss Distance, Earnings Warning, VIX Panic)
"""

import numpy as np
import pandas as pd

import quant_v4_modules as qv4

RISK_FREE_RATE = 0.02
_BENCHMARK_CACHE: dict[str, pd.Series] = {}

XAI_FEATURE_NAMES = [
    "Trend Dist (SMA20/ATR)",
    "RSI(14) Zone",
    "ADX(14) Trend Strength",
    "DI Spread (+DI/-DI)",
    "Bollinger %B Position",
    "Volume Surge (20D)",
    "Weekly MTF RSI",
]


# ==========================================
# 1. Dynamic Volatility-Adjusted Slippage Model
# ==========================================
def compute_dynamic_slippage_series(
    close: pd.Series,
    ind: dict[str, pd.Series],
    base_slippage_bps: float = 4.0,
) -> pd.Series:
    """
    คำนวณ Dynamic Slippage รายวันตามความผันผวน (ATR% / Rolling Volatility) และสภาพคล่อง (Volume Ratio):
      - Base Slippage = 4 bps (0.04%)
      - Volatility Penalty: เพิ่มตามสัดส่วน ATR(14)/Close
      - Liquidity Adjustment: ถ้าวอลุ่มบางกว่าค่าเฉลี่ย (vol_ratio < 0.8) Slippage จะสูงขึ้น
    คืนค่าเป็นสัดส่วนทศนิยม (เช่น 0.0006 = 0.06% ต่อธุรกรรม)
    """
    base_slip = base_slippage_bps / 10000.0
    c_safe = close.replace(0, np.nan).bfill()
    atr_pct = (ind["atr14"] / c_safe).fillna(0.02).clip(0.005, 0.10)
    vol_ratio = ind["vol_ratio"].fillna(1.0).clip(0.3, 3.0)

    # เมื่อ ATR สูง หรือ Volume บาง (vol_ratio ต่ำ) ต้นทุน Slippage จะเพิ่มขึ้นตามจริง
    vol_mult = (atr_pct / 0.02).clip(0.5, 3.0)
    liq_mult = (1.0 / np.sqrt(vol_ratio)).clip(0.7, 1.8)
    dyn_slip = (base_slip * vol_mult * liq_mult).clip(0.0002, 0.0035)
    return pd.Series(dyn_slip, index=close.index, dtype=float)


# ==========================================
# 2. Institutional Benchmark Analytics (S&P 500 Alpha, Beta, Sortino, Omega, IR)
# ==========================================
def get_benchmark_close(period: str = "2y", benchmark_ticker: str = "^GSPC") -> pd.Series | None:
    """ดึงราคาปิดของดัชนีมาตรฐาน S&P 500 (^GSPC) ผ่าน SQLite Cache"""
    cache_key = f"{benchmark_ticker}_{period}"
    if cache_key in _BENCHMARK_CACHE:
        return _BENCHMARK_CACHE[cache_key]
    try:
        ohlcv, _ = qv4.fetch_ohlcv_cached(benchmark_ticker, period, force_refresh=False)
        s = ohlcv["close"]
        _BENCHMARK_CACHE[cache_key] = s
        return s
    except Exception:
        return None


def compute_omega_ratio(returns: pd.Series, threshold_daily: float = 0.0) -> float:
    """
    คำนวณ Omega Ratio: อัตราส่วนของผลรวมกำไรส่วนเกิน (Probability-Weighted Gains)
    เทียบกับผลรวมขาดทุนส่วนเกิน (Probability-Weighted Losses)
    """
    if len(returns) < 5:
        return 1.0
    diff = returns - threshold_daily
    gains = diff[diff > 0].sum()
    losses = abs(diff[diff < 0].sum())
    if losses <= 1e-9:
        return 10.0 if gains > 0 else 1.0
    return float(np.clip(gains / losses, 0.0, 20.0))


def compute_benchmark_alpha_beta(
    strat_rets: pd.Series,
    asset_close: pd.Series,
    benchmark_close: pd.Series | None = None,
) -> dict:
    """
    คำนวณค่าสถิติระดับกองทุนเทียบกับ Benchmark (S&P 500 หรือ Buy & Hold ของสินทรัพย์หากดัชนีไม่มีข้อมูลตรงวัน):
      - Beta (β)            : Cov(R_p, R_b) / Var(R_b)
      - Jensen's Alpha (α%) : [R_p_annual - (R_f + β * (R_b_annual - R_f))] * 100
      - Information Ratio   : Active Return / Tracking Error
      - Omega Ratio         : สัดส่วนพื้นที่กำไรเทียบขาดทุนทั้งหมด
    """
    if benchmark_close is not None and len(benchmark_close) >= 20:
        b_aligned = benchmark_close.reindex(asset_close.index).ffill().bfill()
        if b_aligned.isna().all():
            b_aligned = asset_close
    else:
        b_aligned = asset_close

    b_rets = b_aligned.pct_change().fillna(0.0)
    s_rets = strat_rets.reindex(asset_close.index).fillna(0.0)

    b_equity = (1.0 + b_rets).cumprod() * 100.0
    b_total_ret = float((b_equity.iloc[-1] / 100.0 - 1.0) * 100.0) if len(b_equity) > 0 else 0.0

    var_b = float(np.var(b_rets.to_numpy()))
    if var_b > 1e-10 and len(s_rets) > 10:
        cov_sb = float(np.cov(s_rets.to_numpy(), b_rets.to_numpy())[0, 1])
        beta = float(np.clip(cov_sb / var_b, -3.0, 3.0))
    else:
        beta = 1.0

    ann_s = float(s_rets.mean() * 252.0)
    ann_b = float(b_rets.mean() * 252.0)
    alpha_ann_pct = float((ann_s - (RISK_FREE_RATE + beta * (ann_b - RISK_FREE_RATE))) * 100.0)

    active_diff = s_rets - b_rets
    tracking_err = float(active_diff.std() * np.sqrt(252.0))
    info_ratio = float((ann_s - ann_b) / tracking_err) if tracking_err > 1e-6 else 0.0
    omega = compute_omega_ratio(s_rets)

    return {
        "alpha_pct": alpha_ann_pct,
        "beta": beta,
        "information_ratio": info_ratio,
        "omega_ratio": omega,
        "benchmark_ret_pct": b_total_ret,
        "benchmark_equity": b_equity,
    }


# ==========================================
# 3. Regime-Adaptive V5 Strategy (แก้จุดอ่อนตลาด Sideways)
# ==========================================
def build_regime_adaptive_v5_signal(
    close: pd.Series,
    ind: dict[str, pd.Series],
    atr_mult: float = 3.0,
    target_vol: float = 0.26,
) -> pd.Series:
    """
    กลยุทธ์อัจฉริยะ v5.0 ('regime_adaptive_v5') สลับโหมดตามสภาวะตลาด 3 สถานะอัตโนมัติ:
      1) Trending Bull Regime (ADX >= 22 และ +DI > -DI):
         - รันเทรนด์เต็มตัวด้วย EMA12 > EMA26 หรือ Close > SMA20 พร้อมถือตามโครงสร้างใหญ่
      2) Sideways / Range Regime (ADX < 22 และโครงสร้างใหญ่ไม่พัง Close >= SMA200 * 0.94):
         - ปิดการใช้เส้นค่าเฉลี่ยตัดกัน (เพื่อป้องกัน Whipsaw ขาดทุนซ้ำซากในตลาดออกข้าง)
         - สลับเป็นโหมด Mean-Reversion: เข้าซื้อสะสมเฉพาะเมื่อย่อตัวลงโซนได้เปรียบ (Bollinger %B < 0.28 หรือ RSI < 42)
           และขายทำกำไรรอบสั้นทันทีเมื่อดีดขึ้นชนกรอบบน (Bollinger %B > 0.82 หรือ RSI > 67)
      3) High-Vol Bear / Downtrend Regime (ADX >= 22 และ -DI > +DI และ Close < SMA50):
         - ตัดเข้าถือเงินสดสำรอง 100% (Position = 0.0) ทันทีเพื่อรักษาเงินต้น
    """
    c_arr = close.to_numpy()
    n = len(c_arr)

    sma20 = ind["sma20"].to_numpy()
    sma50 = ind["sma50"].to_numpy()
    sma200 = ind["sma200"].to_numpy()
    ema12 = close.ewm(span=12, adjust=False).mean().to_numpy()
    ema26 = close.ewm(span=26, adjust=False).mean().to_numpy()

    adx = ind["adx14"].fillna(20.0).to_numpy()
    p_di = ind["plus_di"].fillna(20.0).to_numpy()
    m_di = ind["minus_di"].fillna(20.0).to_numpy()
    rsi = ind["rsi14"].fillna(50.0).to_numpy()
    bb_b = ind["bb_pct_b"].fillna(0.5).to_numpy()
    atr = ind["atr14"].to_numpy()
    r_vol = ind["roll_vol20"].to_numpy()
    wk_bull = ind["weekly_bull"].fillna(1.0).to_numpy()

    out_weights = np.zeros(n, dtype=float)
    in_pos = False
    mode_in_use = "none"
    peak_p = 0.0
    stop_p = 0.0

    for i in range(n):
        price = c_arr[i]
        cur_atr = atr[i] if atr[i] > 0 else price * 0.02
        cur_vol = r_vol[i] if r_vol[i] > 0.02 else target_vol
        vol_w = float(np.clip(target_vol / cur_vol, 0.40, 1.0))

        is_strong_trend = adx[i] >= 22.0
        is_bull_di = p_di[i] >= m_di[i] * 0.95
        is_bear_di = m_di[i] > p_di[i] * 1.08
        macro_ok = (price >= sma200[i] * 0.95) or (wk_bull[i] > 0.5)

        # กรณีถือสถานะอยู่ ตรวจจุดออกตามโหมด
        if in_pos:
            peak_p = max(peak_p, price)
            stop_p = max(stop_p, peak_p - atr_mult * cur_atr)

            # ตัดขาดทุน ATR Stop หรือเข้าสู่ Bear Downtrend รุนแรง
            if price <= stop_p or (is_strong_trend and is_bear_di and price < sma50[i]):
                in_pos = False
                mode_in_use = "none"
                out_weights[i] = 0.0
                continue

            if mode_in_use == "sideways_mr":
                # หากเข้าด้วยโหมด Sideways Mean-Reversion แล้วตลาดกลายเป็น Uptrend แรง ให้เลื่อนชั้นเป็น Trend-Following อัตโนมัติ!
                if is_strong_trend and is_bull_di and ema12[i] > ema26[i]:
                    mode_in_use = "trend"
                    out_weights[i] = vol_w
                elif bb_b[i] >= 0.82 or rsi[i] >= 67.0:
                    # ขายทำกำไรที่กรอบบนของ Sideways
                    in_pos = False
                    mode_in_use = "none"
                    out_weights[i] = 0.0
                else:
                    out_weights[i] = min(vol_w, 0.80)
            else:
                # โหมด Trend-Following: ถือรันเทรนด์จนกว่าจะหลุดทั้ง SMA50 และ EMA12 < EMA26
                if price < sma50[i] and ema12[i] < ema26[i] and rsi[i] < 46.0:
                    in_pos = False
                    mode_in_use = "none"
                    out_weights[i] = 0.0
                else:
                    out_weights[i] = vol_w
        else:
            # ยังไม่มีสถานะ: เช็กจังหวะเข้าซื้อแยกตามสภาวะตลาด
            if is_strong_trend and is_bull_di and macro_ok:
                if (ema12[i] > ema26[i] or price > sma20[i]) and rsi[i] < 76.0:
                    in_pos = True
                    mode_in_use = "trend"
                    peak_p = price
                    stop_p = price - atr_mult * cur_atr
                    out_weights[i] = vol_w
            elif not is_strong_trend and macro_ok:
                # ตลาด Sideways (ADX < 22): ซื้อเมื่อย่อตัวเข้าโซน Oversold / แนวรับกรอบล่าง
                if (bb_b[i] <= 0.28 or rsi[i] <= 42.0) and price >= sma200[i] * 0.93:
                    in_pos = True
                    mode_in_use = "sideways_mr"
                    peak_p = price
                    stop_p = price - (atr_mult * 0.9) * cur_atr
                    out_weights[i] = min(vol_w, 0.80)

    return pd.Series(np.clip(out_weights, 0.0, 1.0), index=close.index, dtype=float)


def build_cross_sectional_mom_signal(
    close: pd.Series,
    ind: dict[str, pd.Series],
    benchmark_close: pd.Series | None = None,
    atr_mult: float = 3.0,
    target_vol: float = 0.25,
) -> pd.Series:
    """
    กลยุทธ์แกนหลักที่ 4 (v6.0): 'cross_sectional_mom' (Relative Strength Leader & Risk-Adjusted Momentum)
      - คำนวณ Relative Strength (RS) 63 วัน และ 126 วัน เทียบกับดัชนีตลาด (^GSPC) ปรับด้วยความผันผวน (Risk-Adjusted RS)
      - เข้าถือเฉพาะช่วงที่สินทรัพย์แข็งแกร่งชนะตลาด (RS > 0 และ Momentum เป็นบวก) + โครงสร้าง Weekly MTF เป็นขาขึ้น
      - คุมความเสี่ยงด้วย ATR Chandelier Trailing Stop และ Volatility-Targeted Position Sizing (Clip [0.0, 1.0])
    """
    c_arr = close.to_numpy()
    n = len(c_arr)

    if benchmark_close is not None and len(benchmark_close) >= 20:
        bm = benchmark_close.reindex(close.index).ffill().bfill()
        if bm.isna().all():
            bm = close.rolling(100, min_periods=10).mean().bfill()
    else:
        bm = close.rolling(100, min_periods=10).mean().bfill()

    ret_21 = close.pct_change(21).fillna(0.0)
    ret_63 = close.pct_change(63).fillna(ret_21)
    ret_126 = close.pct_change(126).fillna(ret_63)

    bm_63 = bm.pct_change(63).fillna(0.0)
    bm_126 = bm.pct_change(126).fillna(0.0)

    # Relative Strength Excess Return (ชนะดัชนีตลาดทั้งระยะ 3 เดือน และ 6 เดือน)
    rs_excess = 0.60 * (ret_63 - bm_63) + 0.40 * (ret_126 - bm_126)
    abs_mom = 0.50 * ret_63 + 0.30 * ret_126 + 0.20 * ret_21

    sma20 = ind["sma20"].to_numpy()
    sma50 = ind["sma50"].to_numpy()
    rsi = ind["rsi14"].fillna(50.0).to_numpy()
    atr = ind["atr14"].to_numpy()
    r_vol = ind["roll_vol20"].to_numpy()
    wk_bull = ind["weekly_bull"].fillna(1.0).to_numpy()
    rs_arr = rs_excess.to_numpy()
    mom_arr = abs_mom.to_numpy()

    out_weights = np.zeros(n, dtype=float)
    in_pos = False
    peak_p = 0.0
    stop_p = 0.0

    for i in range(n):
        price = c_arr[i]
        cur_atr = atr[i] if atr[i] > 0 else price * 0.02
        cur_vol = r_vol[i] if r_vol[i] > 0.02 else target_vol
        vol_w = float(np.clip(target_vol / cur_vol, 0.35, 1.0))

        # หุ้นนำตลาด: RS ชนะดัชนี หรือมี Absolute Risk-Adjusted Momentum แข็งแกร่งในโครงสร้างขาขึ้น
        is_leader = (rs_arr[i] >= -0.005 and mom_arr[i] > 0.01) or (mom_arr[i] > 0.04 and wk_bull[i] > 0.5)
        trend_ok = (price >= sma50[i]) or (price >= sma20[i] and wk_bull[i] > 0.5)

        if in_pos:
            peak_p = max(peak_p, price)
            stop_p = max(stop_p, peak_p - atr_mult * cur_atr)
            if price <= stop_p or (rs_arr[i] < -0.06 and price < sma50[i]):
                in_pos = False
                out_weights[i] = 0.0
            else:
                # ปรับน้ำหนักเพิ่มเมื่อ RS โดดเด่น
                rs_boost = 1.0 if rs_arr[i] > 0.02 else 0.85
                out_weights[i] = float(np.clip(vol_w * rs_boost, 0.0, 1.0))
        else:
            if is_leader and trend_ok and rsi[i] < 78.0:
                in_pos = True
                peak_p = price
                stop_p = price - atr_mult * cur_atr
                out_weights[i] = float(np.clip(vol_w, 0.0, 1.0))

    return pd.Series(np.clip(out_weights, 0.0, 1.0), index=close.index, dtype=float)


def build_mode2_vwap_poc_signal(
    close: pd.Series,
    volume: pd.Series,
    ind: dict[str, pd.Series],
    atr_mult: float = 3.0,
    target_vol: float = 0.25,
) -> pd.Series:
    """
    สัญญาณใช้งานจริงของปุ่มที่ 2 (🏛 2. VWAP & Volume Profile POC):
      - คำนวณฐานต้นทุนสถาบัน Rolling POC (Volume-Weighted Median/Mode Price 60 วันย้อนหลังแบบไร้ Look-ahead Bias)
        คู่กับเส้น Rolling VWAP (20D)
      - ซื้อเมื่อโครงสร้างหลักไม่หลุดขาลง และราคายืนเหนือ VWAP20 หรือย่อตัวทดสอบฐาน POC แล้วดีดกลับ
      - ตัดออกเมื่อหลุด ATR Trailing Stop หรือหลุดฐานล่าง Value Area
    """
    c_arr = close.to_numpy()
    v_arr = volume.replace(0, 1.0).to_numpy()
    vwap20 = ind["vwap20"].to_numpy()
    sma50 = ind["sma50"].to_numpy()
    sma200 = ind["sma200"].to_numpy()
    rsi = ind["rsi14"].fillna(50.0).to_numpy()
    atr = ind["atr14"].to_numpy()
    r_vol = ind["roll_vol20"].to_numpy()
    n = len(c_arr)

    out_w = np.zeros(n, dtype=float)
    in_pos = False
    peak_p = 0.0
    stop_p = 0.0

    for i in range(n):
        price = c_arr[i]
        cur_atr = atr[i] if atr[i] > 0 else price * 0.02
        cur_vol = r_vol[i] if r_vol[i] > 0.02 else target_vol
        vol_w = float(np.clip(target_vol / cur_vol, 0.40, 1.0))

        # คำนวณ Rolling POC ย้อนหลังสูงสุด 60 วัน ณ วัน i (Causal 100%)
        lb_start = max(0, i - 60)
        win_c = c_arr[lb_start : i + 1]
        win_v = v_arr[lb_start : i + 1]
        poc_i = float(np.sum(win_c * win_v) / max(np.sum(win_v), 1.0))
        val_i = poc_i - 1.2 * cur_atr

        macro_bull = price >= sma200[i] * 0.95 or sma50[i] >= sma200[i]
        vwap_breakout = price >= vwap20[i] and price >= poc_i * 0.985
        poc_pullback_buy = (val_i <= price <= poc_i * 1.02) and (32.0 <= rsi[i] <= 55.0)

        if in_pos:
            peak_p = max(peak_p, price)
            stop_p = max(stop_p, peak_p - atr_mult * cur_atr)
            if price <= stop_p or (price < val_i and price < sma50[i]):
                in_pos = False
                out_w[i] = 0.0
            else:
                out_w[i] = vol_w
        else:
            if macro_bull and (vwap_breakout or poc_pullback_buy) and rsi[i] < 76.0:
                in_pos = True
                peak_p = price
                stop_p = price - atr_mult * cur_atr
                out_w[i] = vol_w

    return pd.Series(np.clip(out_w, 0.0, 1.0), index=close.index, dtype=float)


def build_mode3_var_shield_signal(
    close: pd.Series,
    base_signal: pd.Series,
    max_daily_var95_pct: float = 2.6,
) -> pd.Series:
    """
    สัญญาณใช้งานจริงของปุ่มที่ 3 (🎲 3. Monte Carlo & VaR Shield Sizing):
      - คำนวณ Rolling 20-Day Historical VaR 95% รายวันแบบไร้ Look-ahead Bias
      - เมื่อความเสี่ยงรายวัน (|VaR 95%|) สูงกว่าเพดานที่กำหนด (เช่น 2.6% ต่อวัน) ระบบจะลดขนาดไม้ลงตามสัดส่วนอัตโนมัติ
        เพื่อป้องกันพอร์ตเสียหายหนักในช่วงตลาดผันผวนรุนแรง (Tail-Risk Protection)
    """
    rets_pct = close.pct_change().fillna(0.0) * 100.0
    roll_var95 = rets_pct.rolling(25, min_periods=10).quantile(0.05).abs().bfill().fillna(2.0)
    var_scale = (max_daily_var95_pct / roll_var95.replace(0, max_daily_var95_pct)).clip(0.30, 1.0)
    shielded = (base_signal.astype(float) * var_scale).clip(0.0, 1.0)
    return pd.Series(shielded, index=close.index, dtype=float)


def build_mode6_xai_filtered_signal(
    close: pd.Series,
    ind: dict[str, pd.Series],
    base_signal: pd.Series,
) -> pd.Series:
    """
    สัญญาณใช้งานจริงของปุ่มที่ 6 (🤖 6. XAI Meta-Filter & Walk-Forward):
      - ใช้ความน่าจะเป็นชนะจากโมเดล L2 Logistic Meta-Model (ที่เทรนเฉพาะช่วง In-Sample 70% แรก)
        มาเป็นตัวกรองสัญญาณ (Meta-Labeling Filter)
      - หาก ML Win Prob < 44% จะตัดสัญญาณหลอกทิ้ง (หรือลดขนาดไม้ลงครึ่งหนึ่ง) และหาก >= 56% จะถือเต็มขนาดไม้
    """
    ml_info = qv4.compute_ml_meta_and_walk_forward(close, ind, base_signal)
    probs = ml_info["ml_prob_series"].to_numpy()
    base_arr = base_signal.to_numpy()
    out_w = np.zeros(len(close), dtype=float)

    for i in range(len(close)):
        if base_arr[i] <= 0:
            out_w[i] = 0.0
        elif probs[i] >= 54.0:
            out_w[i] = float(np.clip(base_arr[i], 0.0, 1.0))
        elif probs[i] >= 44.0:
            out_w[i] = float(np.clip(base_arr[i] * 0.65, 0.0, 1.0))
        else:
            out_w[i] = 0.0

    return pd.Series(out_w, index=close.index, dtype=float)


# ==========================================
# 4. Explainable AI (XAI) Feature Importance & Attribution
# ==========================================
def compute_xai_feature_importance(
    close: pd.Series,
    ind: dict[str, pd.Series],
    horizon: int = 10,
) -> dict:
    """
    สกัดน้ำหนักความสำคัญของตัวแปร (Feature Importance & Attribution) จากโมเดล L2 Logistic Regression:
      - คำนวณผลคูณ w_k * x_k ณ วันล่าสุดของทั้ง 7 ตัวแปร เพื่ออธิบายว่าทำไม AI/ML ถึงให้คะแนน Win Prob สูงหรือต่ำ
      - คืนค่ารายชื่อตัวแปรพร้อมคะแนนอิทธิพล (-100 ถึง +100) สำหรับพล็อตกราฟ Explainable AI (XAI)
    """
    n = len(close)
    c_arr = close.to_numpy()
    atr_arr = ind["atr14"].replace(0, np.nan).to_numpy()

    f1 = np.clip((c_arr - ind["sma20"].to_numpy()) / np.maximum(atr_arr, 1e-6), -4.0, 4.0) / 4.0
    f2 = (ind["rsi14"].to_numpy() - 50.0) / 50.0
    f3 = np.clip((ind["adx14"].to_numpy() - 20.0) / 30.0, -1.0, 1.0)
    f4 = np.clip((ind["plus_di"].to_numpy() - ind["minus_di"].to_numpy()) / 50.0, -1.0, 1.0)
    f5 = np.clip(ind["bb_pct_b"].to_numpy() - 0.5, -1.0, 1.0)
    f6 = np.clip(ind["vol_ratio"].to_numpy() - 1.0, -1.0, 2.0) / 2.0
    f7 = (ind["wk_rsi"].to_numpy() - 50.0) / 50.0

    X = np.column_stack([np.ones(n), f1, f2, f3, f4, f5, f6, f7])
    X = np.nan_to_num(X, nan=0.0)

    fwd_ret = close.shift(-horizon) / close - 1.0
    y = (fwd_ret.to_numpy() > 0.008).astype(float)

    train_end = max(40, int(n * 0.70) - horizon)
    X_train = X[:train_end]
    y_train = y[:train_end]

    w = np.zeros(X.shape[1], dtype=float)
    lr = 0.15
    reg = 0.05
    for _ in range(180):
        z = np.clip(X_train @ w, -30.0, 30.0)
        preds = 1.0 / (1.0 + np.exp(-z))
        grad = (X_train.T @ (preds - y_train)) / max(len(y_train), 1) + reg * w
        grad[0] -= reg * w[0]
        w -= lr * grad

    latest_x = X[-1, 1:]
    feat_weights = w[1:]

    # คำนวณทั้ง Global Magnitude (|w_i|) และ Local Attribution วันล่าสุด (w_i * x_i + ทิศทางตัวแปร)
    raw_impacts = feat_weights * latest_x + 0.35 * latest_x
    max_abs = float(np.max(np.abs(raw_impacts))) if np.max(np.abs(raw_impacts)) > 1e-6 else 1.0
    norm_impacts = [float(np.clip((val / max_abs) * 100.0, -100.0, 100.0)) for val in raw_impacts]

    items = list(zip(XAI_FEATURE_NAMES, norm_impacts))
    best_pos = max(items, key=lambda x: x[1])
    worst_neg = min(items, key=lambda x: x[1])

    return {
        "xai_features": XAI_FEATURE_NAMES,
        "xai_impacts": norm_impacts,
        "xai_weights": [float(v) for v in feat_weights],
        "top_bullish_driver": f"{best_pos[0]} ({best_pos[1]:+.0f})",
        "top_risk_driver": f"{worst_neg[0]} ({worst_neg[1]:+.0f})",
    }


# ==========================================
# 5. Pre-Trade Institutional Risk Gate
# ==========================================
def check_pre_trade_risk_gate(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    stop_loss: float,
    account_equity: float,
    macro_vix: float = 18.5,
    max_single_position_pct: float = 45.0,
) -> dict:
    """
    ตรวจสอบกฎความปลอดภัยระดับกองทุนก่อนส่งคำสั่งซื้อขาย (Pre-Trade Risk Gate):
      1) มูลค่าคำสั่งซื้อต่อไม้ต้องไม่เกินเพดานสูงสุดต่อสินทรัพย์ (เช่น 45% ของพอร์ตรวม)
      2) หากเป็นฝั่ง BUY ในช่วงตลาดตื่นตระหนกสุดขีด (VIX >= 38) จะแจ้งเตือนความเสี่ยงมหภาค
      3) ตรวจสอบระยะ Stop-Loss ไม่ให้กว้างเกิน 25% ของราคาเข้าซื้อ
    """
    if side.upper() != "BUY" or qty <= 0 or price <= 0:
        return {"passed": True, "warnings": [], "order_pct": 0.0}

    order_val = qty * price
    eq_safe = max(account_equity, 1.0)
    order_pct = (order_val / eq_safe) * 100.0
    warnings = []

    if order_pct > max_single_position_pct:
        warnings.append(
            f"ขนาดคำสั่งซื้อ ({order_pct:.1f}% ของพอร์ต) สูงกว่าเกณฑ์กระจายความเสี่ยงแนะนำ ({max_single_position_pct:.0f}%)"
        )

    if stop_loss > 0 and stop_loss < price:
        stop_dist_pct = ((price - stop_loss) / price) * 100.0
        if stop_dist_pct > 25.0:
            warnings.append(f"ระยะตัดขาดทุน Stop-Loss กว้างเกินไป (-{stop_dist_pct:.1f}%) เสี่ยงกระทบพอร์ตรวม")

    if macro_vix >= 35.0:
        warnings.append(f"ดัชนีความกลัวมหภาคอยู่ในโซนตื่นตระหนก (VIX = {macro_vix:.1f}) ควรลดขนาดไม้ลงครึ่งหนึ่ง")

    return {
        "passed": len(warnings) == 0,
        "warnings": warnings,
        "order_pct": order_pct,
    }


def evaluate_six_button_modes(
    close: pd.Series,
    volume: pd.Series,
    ind: dict[str, pd.Series],
    core_signals: dict[str, pd.Series],
    evaluate_fn,
    best_is_strat: str,
    fee: float = 0.001,
    benchmark_close: pd.Series | None = None,
) -> dict[str, dict]:
    """
    คำนวณผล Backtest จริงของการใช้กลยุทธ์ในแต่ละปุ่มทั้ง 6 โหมดบน GUI (1..6)
    พร้อมวัดผลทั้งช่วง Full Period และช่วง Out-of-Sample (30% หลัง) เพื่อพิสูจน์ว่าแต่ละปุ่มใช้งานทำกำไรได้จริง
    """
    base_sig = core_signals.get(best_is_strat, core_signals.get("trend_atr_vol"))

    sig_m1 = core_signals.get("trend_atr_vol", base_sig)
    sig_m2 = build_mode2_vwap_poc_signal(close, volume, ind)
    sig_m3 = build_mode3_var_shield_signal(close, base_sig)
    # ปุ่มที่ 4: ผสาน 3 กลยุทธ์หลักแบบ Risk-Parity Ensemble Weighting
    sig_m4 = pd.Series(
        np.clip(
            0.40 * core_signals["trend_atr_vol"].to_numpy()
            + 0.35 * core_signals["regime_adaptive_v5"].to_numpy()
            + 0.25 * core_signals["cross_sectional_mom"].to_numpy(),
            0.0,
            1.0,
        ),
        index=close.index,
        dtype=float,
    )
    sig_m5 = base_sig
    sig_m6 = build_mode6_xai_filtered_signal(close, ind, base_sig)

    mode_defs = [
        ("mode_1_atr_sniper", "🎯 ปุ่ม 1: ATR Trailing & Sniper", sig_m1),
        ("mode_2_vwap_poc", "🏛 ปุ่ม 2: VWAP & Volume Profile POC", sig_m2),
        ("mode_3_mc_var_shield", "🎲 ปุ่ม 3: Monte Carlo VaR-Shield Sizing", sig_m3),
        ("mode_4_risk_parity", "⚖ ปุ่ม 4: Risk-Parity Portfolio Blend", sig_m4),
        ("mode_5_is_winner", f"📈 ปุ่ม 5: Best IS Core ({best_is_strat})", sig_m5),
        ("mode_6_xai_filter", "🤖 ปุ่ม 6: XAI Meta-Filtered Signal", sig_m6),
    ]

    cut = max(30, int(len(close) * 0.70))
    out_map = {}
    for m_key, m_title, m_sig in mode_defs:
        full_res = evaluate_fn(close, m_sig, fee=fee, shift_signal=True, ind=ind, benchmark_close=benchmark_close)
        if len(close) - cut >= 15:
            oos_res = evaluate_fn(
                close.iloc[cut:],
                m_sig.iloc[cut:],
                fee=fee,
                shift_signal=True,
                ind={k: v.iloc[cut:] for k, v in ind.items()},
                benchmark_close=benchmark_close.iloc[cut:] if benchmark_close is not None and len(benchmark_close) > cut else None,
            )
            oos_ret = float(oos_res["total_ret_pct"])
            oos_shp = float(oos_res["sharpe"])
            oos_dd = float(oos_res["max_dd_pct"])
        else:
            oos_ret = float(full_res["total_ret_pct"])
            oos_shp = float(full_res["sharpe"])
            oos_dd = float(full_res["max_dd_pct"])

        out_map[m_key] = {
            "title": m_title,
            "signal": m_sig,
            "full": full_res,
            "oos_ret_pct": oos_ret,
            "oos_sharpe": oos_shp,
            "oos_max_dd_pct": oos_dd,
        }
    return out_map


# ==========================================
# 6. Sprint A (v7.0): Cross-Sectional Universe Scanner & Rolling Walk-Forward Gate
# ==========================================
LIQUID_UNIVERSE_30 = [
    "AAPL", "MSFT", "NVDA", "AVGO", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX",
    "JPM", "V", "MA", "UNH", "LLY", "XOM", "CVX", "COST", "WMT", "HD",
    "PG", "JNJ", "ORCL", "CRM", "ADBE", "QCOM", "TXN", "LIN", "CAT", "GE",
]
SAFE_HAVEN_ASSETS = ["GLD", "SHY"]  # ทองคำ (Gold ETF) และพันธบัตรรัฐบาลสหรัฐฯ ระยะสั้น 1-3 ปี (Treasury ETF)


def _check_go_no_go_gate(sharpe: float, profit_factor: float, max_dd_pct: float) -> dict:
    """
    Go/No-Go Gate มาตรฐานตาม PROJECT_ROADMAP.md:
      - OOS Sharpe Ratio > 1.20
      - OOS Profit Factor > 1.35
      - OOS Max Drawdown < 15.0% (abs(max_dd_pct) < 15.0)
    """
    pass_sharpe = sharpe > 1.20
    pass_pf = profit_factor > 1.35
    pass_dd = abs(max_dd_pct) < 15.0
    passed = pass_sharpe and pass_pf and pass_dd
    failed_reasons = []
    if not pass_sharpe:
        failed_reasons.append(f"Sharpe {sharpe:.2f} <= 1.20")
    if not pass_pf:
        failed_reasons.append(f"PF {profit_factor:.2f} <= 1.35")
    if not pass_dd:
        failed_reasons.append(f"MaxDD {max_dd_pct:.2f}% >= -15.0%")
    return {
        "gate_passed": passed,
        "gate_status": "PASS" if passed else "FAIL",
        "pass_sharpe": pass_sharpe,
        "pass_pf": pass_pf,
        "pass_dd": pass_dd,
        "failed_reasons": failed_reasons,
    }


def scan_cross_sectional_universe(
    close_map: dict[str, pd.Series],
    spy_close: pd.Series,
    top_n: int = 5,
    hold_buffer: int = 15,
    safe_haven_map: dict[str, pd.Series] | None = None,
) -> dict:
    """
    คัดกรองหุ้นนำตลาดแบบ Cross-Sectional + Dual-Momentum Safe-Haven Rotation (GLD / SHY):
      1) Market Regime Filter: SPY Close > SPY SMA200
         - ถ้า Bullish -> จัดสรรเงินให้ Top N หุ้นนำตลาด (Inverse-Volatility)
         - ถ้า Bearish (SPY <= SMA200) -> หมุนเงินไปพักในสินทรัพย์หลบภัย (GLD เมื่อทองขาขึ้น + SHY พันธบัตรสั้น) แทนถือเงินสด 0%
      2) Risk-Adjusted Momentum Score = (0.60 * Ret_126D + 0.40 * Ret_63D) / max(Vol_20D, 0.12)
    """
    spy_clean = spy_close.dropna()
    spy_sma200 = spy_clean.rolling(200, min_periods=50).mean()
    spy_last = float(spy_clean.iloc[-1])
    spy_ma_last = float(spy_sma200.iloc[-1])
    market_bull = spy_last > spy_ma_last
    spy_ret_126 = float(spy_clean.iloc[-1] / spy_clean.iloc[max(0, len(spy_clean) - 127)] - 1.0)

    ranked = []
    for ticker, ser in close_map.items():
        c = ser.dropna()
        if len(c) < 70:
            continue
        last_p = float(c.iloc[-1])
        sma50 = float(c.rolling(50, min_periods=20).mean().iloc[-1])
        ret_63 = float(c.iloc[-1] / c.iloc[max(0, len(c) - 64)] - 1.0)
        ret_126 = float(c.iloc[-1] / c.iloc[max(0, len(c) - 127)] - 1.0)
        vol_20 = float(c.pct_change().rolling(20, min_periods=10).std().iloc[-1] * np.sqrt(252.0))
        if np.isnan(vol_20) or vol_20 < 0.08:
            vol_20 = 0.12

        blend_ret = 0.60 * ret_126 + 0.40 * ret_63
        risk_adj_mom = blend_ret / max(vol_20, 0.12)
        rs_vs_spy_pct = (ret_126 - spy_ret_126) * 100.0
        above_sma50 = last_p > sma50

        ranked.append({
            "ticker": ticker,
            "close": last_p,
            "sma50": sma50,
            "above_sma50": above_sma50,
            "ret_63_pct": ret_63 * 100.0,
            "ret_126_pct": ret_126 * 100.0,
            "vol_20_pct": vol_20 * 100.0,
            "rs_vs_spy_pct": rs_vs_spy_pct,
            "risk_adj_mom": risk_adj_mom,
            "target_weight_pct": 0.0,
            "status": "ROTATE_OUT",
        })

    ranked.sort(key=lambda r: r["risk_adj_mom"], reverse=True)

    # จัดอันดับและคำนวณน้ำหนัก Inverse-Volatility ให้เฉพาะ Top N ที่ผ่านเกณฑ์ทั้งหมด
    eligible = []
    for idx, r in enumerate(ranked, start=1):
        r["rank"] = idx
        if not market_bull:
            r["status"] = "CASH_REGIME (SPY<SMA200)"
        elif idx <= top_n and r["above_sma50"] and r["risk_adj_mom"] > 0.0:
            r["status"] = "ALLOCATE (TOP LEADER)"
            eligible.append(r)
        elif idx <= hold_buffer and r["above_sma50"] and r["risk_adj_mom"] > 0.0:
            r["status"] = "HOLD_BUFFER"
        else:
            r["status"] = "ROTATE_OUT"

    if market_bull and eligible:
        inv_vols = [1.0 / max(r["vol_20_pct"] / 100.0, 0.12) for r in eligible]
        total_iv = sum(inv_vols)
        for r, iv in zip(eligible, inv_vols):
            r["target_weight_pct"] = float(np.clip((iv / total_iv) * 100.0, 0.0, 35.0))
        # Normalize ถ้าน้ำหนักรวมเกิน 100%
        w_sum = sum(r["target_weight_pct"] for r in eligible)
        if w_sum > 100.0:
            for r in eligible:
                r["target_weight_pct"] = r["target_weight_pct"] / w_sum * 100.0

    # จัดสรรเงินที่เหลือ (หรือ 100% ช่วง Bearish) เข้า Dual-Momentum Safe-Haven Rotation (GLD / SHY)
    equity_alloc_sum = sum(r["target_weight_pct"] for r in ranked)
    defensive_budget = max(0.0, 100.0 - equity_alloc_sum)
    safe_haven_alloc: dict[str, float] = {}
    if defensive_budget > 0.5 and safe_haven_map:
        gld_ser = safe_haven_map.get("GLD")
        shy_ser = safe_haven_map.get("SHY")
        gld_bull = False
        if gld_ser is not None and len(gld_ser.dropna()) >= 65:
            gc = gld_ser.dropna()
            g_sma50 = float(gc.rolling(50, min_periods=20).mean().iloc[-1])
            g_ret63 = float(gc.iloc[-1] / gc.iloc[-64] - 1.0)
            gld_bull = (float(gc.iloc[-1]) > g_sma50) and (g_ret63 > 0.0)

        if gld_bull and shy_ser is not None:
            safe_haven_alloc["GLD"] = round(defensive_budget * 0.50, 2)
            safe_haven_alloc["SHY"] = round(defensive_budget * 0.50, 2)
        elif gld_bull:
            safe_haven_alloc["GLD"] = round(defensive_budget * 0.50, 2)
        elif shy_ser is not None:
            safe_haven_alloc["SHY"] = round(defensive_budget, 2)

    sh_sum = sum(safe_haven_alloc.values())
    sh_label = (
        " + ".join(f"{k} {v:.0f}%" for k, v in safe_haven_alloc.items())
        if safe_haven_alloc
        else "CASH 100%"
    )
    regime_lbl = (
        f"BULLISH (SPY {spy_last:,.2f} > SMA200 {spy_ma_last:,.2f})"
        if market_bull
        else f"BEARISH_DEFENSIVE (SPY {spy_last:,.2f} <= SMA200 {spy_ma_last:,.2f} -> {sh_label})"
    )

    return {
        "market_bull": market_bull,
        "spy_close": spy_last,
        "spy_sma200": spy_ma_last,
        "spy_regime_label": regime_lbl,
        "universe_count": len(ranked),
        "allocated_count": len(eligible),
        "safe_haven_alloc": safe_haven_alloc,
        "cash_weight_pct": max(0.0, 100.0 - equity_alloc_sum - sh_sum),
        "rankings": ranked,
    }


def backtest_cross_sectional_portfolio(
    close_map: dict[str, pd.Series],
    spy_close: pd.Series,
    top_n: int = 5,
    hold_buffer: int = 15,
    rebalance_days: int = 21,
    fee: float = 0.001,
    slip_bps: float = 5.0,
    catastrophic_stop_pct: float = 0.15,
    target_port_vol: float = 0.18,
    safe_haven_map: dict[str, pd.Series] | None = None,
) -> dict:
    """
    ทดสอบพอร์ต Cross-Sectional Momentum + Dual-Momentum Safe-Haven Rotation (GLD/SHY) แบบไร้ Look-ahead Bias:
      - ช่วงตลาดขาขึ้น (SPY > SMA200): ถือหุ้นนำตลาด Top N + ถ่วงน้ำหนัก Inverse-Volatility
      - ช่วงตลาดขาลง (SPY <= SMA200) หรือเงินสดสำรองที่เหลือจาก Vol Cap:
        หมุนไปพักใน GLD (50% เมื่อทองขาขึ้น > SMA50 & Ret63 > 0) และ SHY (พันธบัตรสั้น) แทนการถือเงินสด 0%
      - บังคับ Shift 1 Bar (Zero Look-ahead) และหัก Fee 0.1% + Slippage 5 bps ทุกครั้งที่มีการสลับพอร์ต
    """
    df_prices = pd.DataFrame(close_map).sort_index().ffill().dropna(how="all")
    spy_al = spy_close.reindex(df_prices.index).ffill().bfill()
    if len(df_prices) < 150 or df_prices.shape[1] < 2:
        raise ValueError("ข้อมูลไม่เพียงพอสำหรับ Cross-Sectional Portfolio Backtest (ต้องการ >= 150 วัน และ >= 2 หุ้น)")

    eq_tickers = list(df_prices.columns)
    sh_tickers: list[str] = []
    all_prices = df_prices.copy()
    if safe_haven_map:
        for sh_sym in SAFE_HAVEN_ASSETS:
            if sh_sym in safe_haven_map and sh_sym not in all_prices.columns:
                all_prices[sh_sym] = safe_haven_map[sh_sym].reindex(df_prices.index).ffill().bfill()
                sh_tickers.append(sh_sym)

    all_tickers = list(all_prices.columns)
    rets_df = all_prices.pct_change().fillna(0.0)
    spy_rets = spy_al.pct_change().fillna(0.0)
    spy_sma200 = spy_al.rolling(200, min_periods=50).mean()
    spy_vol20 = (spy_rets.rolling(20, min_periods=10).std() * np.sqrt(252.0)).bfill().fillna(0.16).clip(lower=0.08)

    sma50_df = df_prices.rolling(50, min_periods=20).mean()
    ret63_df = df_prices.pct_change(63)
    ret126_df = df_prices.pct_change(126)
    vol20_df = (df_prices.pct_change().fillna(0.0).rolling(20, min_periods=10).std() * np.sqrt(252.0)).clip(lower=0.12)
    score_df = (0.60 * ret126_df + 0.40 * ret63_df) / vol20_df

    gld_sma50 = all_prices["GLD"].rolling(50, min_periods=20).mean() if "GLD" in all_prices.columns else None
    gld_ret63 = all_prices["GLD"].pct_change(63).fillna(0.0) if "GLD" in all_prices.columns else None

    dates = df_prices.index
    n_days = len(dates)
    weights_df = pd.DataFrame(0.0, index=dates, columns=all_tickers)

    warmup = min(130, max(65, n_days // 4))
    held: set[str] = set()
    peak_prices: dict[str, float] = {}
    cur_eq_weights = pd.Series(0.0, index=eq_tickers)

    for i in range(warmup, n_days):
        spy_p = float(spy_al.iloc[i])
        spy_ma200 = float(spy_sma200.iloc[i])
        spy_ok = spy_p > spy_ma200

        # 1) รอบ Rebalance รายเดือน
        if (i - warmup) % rebalance_days == 0:
            if not spy_ok:
                held = set()
                peak_prices = {}
                cur_eq_weights = pd.Series(0.0, index=eq_tickers)
            else:
                day_scores = score_df.iloc[i].dropna().sort_values(ascending=False)
                day_above50 = df_prices.iloc[i] > sma50_df.iloc[i]
                rank_map = {t: r_idx for r_idx, t in enumerate(day_scores.index, start=1)}

                new_held = [
                    t for t in held
                    if t in rank_map and rank_map[t] <= hold_buffer and bool(day_above50.get(t, False)) and float(day_scores[t]) > 0.0
                ]
                for t in day_scores.index:
                    if len(new_held) >= top_n:
                        break
                    if t not in new_held and bool(day_above50.get(t, False)) and float(day_scores[t]) > 0.0:
                        new_held.append(t)

                held = set(new_held)
                peak_prices = {
                    t: max(peak_prices.get(t, float(df_prices.iloc[i][t])), float(df_prices.iloc[i][t]))
                    for t in held
                }
                cur_eq_weights = pd.Series(0.0, index=eq_tickers)
                if held:
                    inv_v = pd.Series({t: 1.0 / max(float(vol20_df.iloc[i][t]), 0.12) for t in held})
                    w_norm = (inv_v / inv_v.sum()).clip(0.0, 0.35)
                    w_norm = w_norm / max(w_norm.sum(), 1.0)
                    vol_scale = float(np.clip(target_port_vol / float(spy_vol20.iloc[i]), 0.55, 1.0))
                    for t, w_val in w_norm.items():
                        cur_eq_weights[t] = float(w_val * vol_scale)

        # 2) เกราะฉุกเฉินระหว่างเดือน (SPY < SMA200 หรือหุ้นรายตัวร่วงเกิน -15%)
        if not spy_ok:
            held = set()
            peak_prices = {}
            cur_eq_weights = pd.Series(0.0, index=eq_tickers)
        elif held:
            for t in list(held):
                cur_p = float(df_prices.iloc[i][t])
                peak_prices[t] = max(peak_prices.get(t, cur_p), cur_p)
                if cur_p <= peak_prices[t] * (1.0 - catastrophic_stop_pct):
                    held.discard(t)
                    peak_prices.pop(t, None)
                    cur_eq_weights[t] = 0.0

        # 3) หมุนเงินส่วนที่ไม่ได้ถือหุ้นไปพักใน Safe-Haven (GLD / SHY) เพื่อสร้างผลตอบแทนช่วงตลาดขาลง
        row_w = pd.Series(0.0, index=all_tickers)
        for t in eq_tickers:
            row_w[t] = float(cur_eq_weights[t])

        defensive_w = max(0.0, 1.0 - float(cur_eq_weights.sum()))
        if defensive_w > 0.01 and sh_tickers:
            gld_bull = (
                "GLD" in sh_tickers
                and float(all_prices["GLD"].iloc[i]) > float(gld_sma50.iloc[i])
                and float(gld_ret63.iloc[i]) > 0.0
            )
            if gld_bull and "SHY" in sh_tickers:
                row_w["GLD"] = defensive_w * 0.50
                row_w["SHY"] = defensive_w * 0.50
            elif gld_bull:
                row_w["GLD"] = defensive_w * 0.50
            elif "SHY" in sh_tickers:
                row_w["SHY"] = defensive_w

        weights_df.iloc[i] = row_w

    # บังคับ Shift 1 Bar (Zero Look-ahead Bias) และ Clip [0.0, 1.0]
    eff_weights = weights_df.shift(1).fillna(0.0).clip(0.0, 1.0)
    row_sums = eff_weights.sum(axis=1)
    over_mask = row_sums > 1.0
    if over_mask.any():
        eff_weights.loc[over_mask] = eff_weights.loc[over_mask].div(row_sums[over_mask], axis=0)

    turnover = eff_weights.diff().abs().fillna(0.0).sum(axis=1)
    unit_cost = fee + (slip_bps / 10000.0)

    eval_slice = slice(warmup, n_days)
    gross_rets = (eff_weights.iloc[eval_slice] * rets_df.iloc[eval_slice]).sum(axis=1)
    net_rets = gross_rets - (turnover.iloc[eval_slice] * unit_cost)
    spy_eval_rets = spy_rets.iloc[eval_slice]

    gross_eq = (1.0 + gross_rets).cumprod() * 100.0
    net_eq = (1.0 + net_rets).cumprod() * 100.0
    spy_eq = (1.0 + spy_eval_rets).cumprod() * 100.0

    gross_ret_pct = float((gross_eq.iloc[-1] / 100.0 - 1.0) * 100.0)
    total_ret_pct = float((net_eq.iloc[-1] / 100.0 - 1.0) * 100.0)
    spy_ret_pct = float((spy_eq.iloc[-1] / 100.0 - 1.0) * 100.0)
    cost_drag_pct = float(max(0.0, gross_ret_pct - total_ret_pct))

    n_eval = max(len(net_rets), 1)
    cagr_pct = float(((net_eq.iloc[-1] / 100.0) ** (252.0 / n_eval) - 1.0) * 100.0) if net_eq.iloc[-1] > 0 else -100.0
    ann_ret = float(net_rets.mean() * 252.0)
    ann_vol = float(net_rets.std() * np.sqrt(252.0))
    sharpe = float((ann_ret - RISK_FREE_RATE) / ann_vol) if ann_vol > 1e-9 else 0.0

    down = net_rets[net_rets < 0]
    down_vol = float(down.std() * np.sqrt(252.0)) if len(down) > 1 else 0.0
    sortino = float((ann_ret - RISK_FREE_RATE) / down_vol) if down_vol > 1e-9 else 0.0

    dd = (net_eq - net_eq.cummax()) / net_eq.cummax() * 100.0
    max_dd_pct = float(dd.min())

    # คำนวณ Profit Factor จากผลตอบแทนรายรอบ Rebalance (ทุก rebalance_days)
    period_rets = net_rets.groupby(np.arange(len(net_rets)) // rebalance_days).apply(lambda r: (1.0 + r).prod() - 1.0)
    wins = period_rets[period_rets > 0]
    losses = period_rets[period_rets < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 1e-9 else (99.99 if wins.sum() > 0 else 0.0)
    win_rate_pct = float((len(wins) / max(len(period_rets), 1)) * 100.0)

    gate = _check_go_no_go_gate(sharpe, pf, max_dd_pct)
    return {
        "start_date": dates[warmup].strftime("%Y-%m-%d"),
        "end_date": dates[-1].strftime("%Y-%m-%d"),
        "eval_days": n_eval,
        "total_ret_pct": total_ret_pct,
        "spy_ret_pct": spy_ret_pct,
        "excess_ret_pct": total_ret_pct - spy_ret_pct,
        "cagr_pct": cagr_pct,
        "max_dd_pct": max_dd_pct,
        "sharpe": sharpe,
        "sortino": sortino,
        "profit_factor": pf,
        "period_win_rate_pct": win_rate_pct,
        "cost_drag_pct": cost_drag_pct,
        "avg_exposure_pct": float(eff_weights.iloc[eval_slice].sum(axis=1).mean() * 100.0),
        "equity": net_eq,
        "spy_equity": spy_eq,
        **gate,
    }


def run_rolling_walk_forward_gate(
    close: pd.Series,
    ind: dict[str, pd.Series],
    core_signals: dict[str, pd.Series],
    evaluate_fn,
    train_days: int = 252,
    test_days: int = 63,
    fee: float = 0.001,
    benchmark_close: pd.Series | None = None,
) -> dict:
    """
    Rolling Walk-Forward Optimization & Go/No-Go Validation Gate (12M Train -> 3M OOS -> Roll Forward):
      - ในแต่ละ Fold: เลือกกลยุทธ์ที่ชนะ (จาก 3 แกนหลัก Active) เฉพาะบนช่วง Train (252 วัน) เท่านั้น
      - ล็อกผู้ชนะนั้นแล้วนำไปรันวัดผลจริงบนช่วง Test ที่ไม่เคยเห็นมาก่อน (63 วันถัดไป) รวม Commission + Dynamic Slippage
      - เย็บผลตอบแทนทุก OOS Fold ต่อเนื่องเป็น Stitched OOS Equity Curve แล้วตรวจผ่านเกณฑ์ Go/No-Go Gate:
        (OOS Sharpe > 1.2, Profit Factor > 1.35, Max Drawdown < 15%)
    """
    n = len(close)
    candidates = [k for k in core_signals.keys() if k != "buy_hold"]
    if not candidates:
        candidates = list(core_signals.keys())

    # ปรับขนาดหน้าต่างอัตโนมัติหากข้อมูลสั้นกว่า 15 เดือน แต่ยังคงโครงสร้าง Rolling OOS เหมือนเดิม
    eff_train = min(train_days, max(80, int(n * 0.50)))
    eff_test = min(test_days, max(21, int((n - eff_train) / 3))) if n > eff_train + 30 else max(15, n - eff_train)

    stitched_rets_parts = []
    fold_details = []
    pos_start = eff_train

    while pos_start + 10 <= n:
        tr_start = max(0, pos_start - eff_train)
        tr_end = pos_start
        te_start = pos_start
        te_end = min(n, pos_start + eff_test)

        c_tr = close.iloc[tr_start:tr_end]
        ind_tr = {k: v.iloc[tr_start:tr_end] for k, v in ind.items()}

        # เลือกผู้ชนะเฉพาะบนหน้าต่าง Train เท่านั้น (Zero Selection Bias)
        best_k = candidates[0]
        best_score = -1e9
        for k in candidates:
            r_tr = evaluate_fn(c_tr, core_signals[k].iloc[tr_start:tr_end], fee=fee, shift_signal=True, ind=ind_tr)
            sc = r_tr["sharpe"] + 0.30 * r_tr["calmar"]
            if sc > best_score:
                best_score = sc
                best_k = k

        # รันวัดผล Out-of-Sample บนช่วง Test ที่ไม่เคยเห็นมาก่อน (Shift 1 Bar + Dynamic Slippage)
        c_te = close.iloc[te_start:te_end]
        ind_te = {k: v.iloc[te_start:te_end] for k, v in ind.items()}
        sig_te = core_signals[best_k].iloc[te_start:te_end].clip(0.0, 1.0)
        rets_te = c_te.pct_change().fillna(0.0)
        pos_te = sig_te.shift(1).fillna(float(core_signals[best_k].iloc[te_start - 1]) if te_start > 0 else 0.0)
        trades_te = pos_te.diff().abs().fillna(0.0)
        slip_te = compute_dynamic_slippage_series(c_te, ind_te)
        net_te = (pos_te * rets_te) - (trades_te * (fee + slip_te))

        stitched_rets_parts.append(net_te)
        fold_ret_pct = float(((1.0 + net_te).prod() - 1.0) * 100.0)
        fold_details.append({
            "fold": len(fold_details) + 1,
            "train_range": f"{close.index[tr_start].strftime('%Y-%m-%d')}..{close.index[tr_end - 1].strftime('%Y-%m-%d')}",
            "test_range": f"{c_te.index[0].strftime('%Y-%m-%d')}..{c_te.index[-1].strftime('%Y-%m-%d')}",
            "locked_strategy": best_k,
            "oos_ret_pct": fold_ret_pct,
        })
        pos_start += eff_test

    if not stitched_rets_parts:
        raise ValueError("ข้อมูลสั้นเกินไปสำหรับการรัน Rolling Walk-Forward Validation")

    stitched_rets = pd.concat(stitched_rets_parts)
    stitched_eq = (1.0 + stitched_rets).cumprod() * 100.0
    oos_total_ret = float((stitched_eq.iloc[-1] / 100.0 - 1.0) * 100.0)
    oos_days = max(len(stitched_rets), 1)
    oos_cagr = float(((stitched_eq.iloc[-1] / 100.0) ** (252.0 / oos_days) - 1.0) * 100.0) if stitched_eq.iloc[-1] > 0 else -100.0

    ann_r = float(stitched_rets.mean() * 252.0)
    ann_v = float(stitched_rets.std() * np.sqrt(252.0))
    oos_sharpe = float((ann_r - RISK_FREE_RATE) / ann_v) if ann_v > 1e-9 else 0.0

    down = stitched_rets[stitched_rets < 0]
    down_v = float(down.std() * np.sqrt(252.0)) if len(down) > 1 else 0.0
    oos_sortino = float((ann_r - RISK_FREE_RATE) / down_v) if down_v > 1e-9 else 0.0

    dd = (stitched_eq - stitched_eq.cummax()) / stitched_eq.cummax() * 100.0
    oos_max_dd = float(dd.min())

    # คำนวณ Profit Factor ของช่วง OOS (ราย Fold หรือรายวัน)
    pos_r = stitched_rets[stitched_rets > 0].sum()
    neg_r = abs(stitched_rets[stitched_rets < 0].sum())
    oos_pf = float(pos_r / neg_r) if neg_r > 1e-9 else (99.99 if pos_r > 0 else 0.0)

    gate = _check_go_no_go_gate(oos_sharpe, oos_pf, oos_max_dd)
    return {
        "n_folds": len(fold_details),
        "train_days": eff_train,
        "test_days": eff_test,
        "oos_days": oos_days,
        "oos_total_ret_pct": oos_total_ret,
        "oos_cagr_pct": oos_cagr,
        "oos_sharpe": oos_sharpe,
        "oos_sortino": oos_sortino,
        "oos_profit_factor": oos_pf,
        "oos_max_dd_pct": oos_max_dd,
        "fold_details": fold_details,
        "stitched_equity": stitched_eq,
        **gate,
    }


