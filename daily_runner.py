#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_runner.py — Headless Production Daily Execution Script (AI Quant v7.0 Final)
ออกแบบสำหรับรันอัตโนมัติวันละ 1 รอบ (Windows Task Scheduler หรือ AWS EC2 Ubuntu Cron) โดยไม่ต้องเปิดหน้าต่าง GUI:
  1) สแกนตะกร้าหุ้นสภาพคล่องสูง 30 ตัว (LIQUID_UNIVERSE_30) + กรองสภาวะตลาด SPY > SMA200
  2) ตรวจเกราะ Portfolio Circuit Breaker (-5% ลดขนาดไม้ครึ่งหนึ่ง, -8% ล็อกห้ามเปิดไม้ซื้อใหม่)
  3) คำนวณคำสั่ง Rebalance แบบ Smart Limit Order (ขายตัวหลุดอันดับก่อน แล้วค่อยซื้อ Top Leaders)
  4) แสดงสถานะ Live Capital Readiness Gate (เช็กครบ 30 ไม้ Paper Trade ก่อนลงเงินจริง)
  5) บันทึก Log ลง logs/daily_runner.log และซิงก์ความจำให้ Hermes Agent

วิธีรันทดสอบด้วยตัวเอง (ปลอดภัย ไม่ส่งออเดอร์จริง):
  python daily_runner.py --dry-run

วิธีรันส่งคำสั่งจริง (เข้าพอร์ตที่ตั้งค่าใน broker_bridge: Local Paper หรือ Alpaca Paper/Live):
  python daily_runner.py --execute --top-n 5

ตัวอย่างตั้ง Cron บน AWS EC2 Ubuntu (รัน จ.-ศ. เวลา 21:35 น. ตามเวลาไทย / หลังตลาดสหรัฐเปิด 5 นาที):
  35 14 * * 1-5 cd /home/ubuntu/mini-project-quant01 && /usr/bin/python3 daily_runner.py --execute >> logs/cron.log 2>&1
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime

import backtest_engine as be
import broker_bridge as bb
import quant_v5_institutional as qv5

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(WORK_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "daily_runner.log")


def _load_dotenv_if_present():
    """โหลดตัวแปรจากไฟล์ .env (ถ้ามี) แบบไม่ต้องลงไลบรารีเสริม"""
    env_path = os.path.join(WORK_DIR, ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


def send_webhook_alert(message: str) -> dict:
    """
    ส่งแจ้งเตือน 1 ข้อความสรุปเข้า Discord หรือ Telegram (1-Channel Alert):
      - ใช้ DISCORD_WEBHOOK_URL หรือ (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) จาก Environment / .env
      - หากยังไม่ได้ตั้งค่า จะข้ามอย่างปลอดภัยโดยไม่ทำให้บอทพัง
    """
    _load_dotenv_if_present()
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    sent_channels = []
    if discord_url and discord_url.startswith("http"):
        try:
            payload = json.dumps({"content": message[:1900]}).encode("utf-8")
            req = urllib.request.Request(
                discord_url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "AI-Quant-v7/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                sent_channels.append("discord")
        except Exception as e:
            _log(f"[Alert Warn] ส่ง Discord ไม่สำเร็จ: {e}")

    if tg_token and tg_chat and "your_" not in tg_token:
        try:
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = json.dumps({"chat_id": tg_chat, "text": message[:3900]}).encode("utf-8")
            req = urllib.request.Request(
                tg_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10):
                sent_channels.append("telegram")
        except Exception as e:
            _log(f"[Alert Warn] ส่ง Telegram ไม่สำเร็จ: {e}")

    return {"sent": len(sent_channels) > 0, "channels": sent_channels}


def _log(msg: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def build_rebalance_plan(
    scan: dict,
    account_summary: dict,
    circuit_breaker: dict,
    latest_prices: dict[str, float] | None = None,
    min_trade_notional: float = 250.0,
) -> list[dict]:
    """คำนวณชุดคำสั่ง Rebalance (SELL ตัวหลุดอันดับก่อน -> BUY หุ้นนำตลาด Top Leaders หรือ Safe-Haven GLD/SHY)"""
    equity = float(account_summary.get("equity", 100000.0))
    positions = {p["symbol"]: p for p in account_summary.get("positions", [])}
    rank_map = {r["ticker"]: r for r in scan["rankings"]}
    sh_alloc = scan.get("safe_haven_alloc", {})
    price_map = latest_prices or {}

    orders = []
    # 1) ขายปิดสถานะหุ้นที่หลุดเกณฑ์ (และไม่ใช่อยู่ในรายการ Safe-Haven ที่กำลังต้องถือ)
    for sym, pos in positions.items():
        r_info = rank_map.get(sym)
        cur_p = float(pos.get("current_price") or price_map.get(sym, 0.0) or pos.get("avg_price") or 0.0)
        qty = float(pos.get("qty", 0.0))
        if qty <= 1e-6 or cur_p <= 0:
            continue

        if sym in sh_alloc and sh_alloc[sym] > 0:
            continue
        should_exit = (
            (sym in qv5.SAFE_HAVEN_ASSETS and sh_alloc.get(sym, 0.0) <= 0)
            or (not scan["market_bull"])
            or (r_info is None)
            or (r_info["status"] not in ("ALLOCATE (TOP LEADER)", "HOLD_BUFFER"))
        )
        if should_exit:
            orders.append({
                "symbol": sym,
                "side": "SELL",
                "qty": qty,
                "price": cur_p,
                "stop_loss": 0.0,
                "reason": "Market Bearish -> Safe-Haven Rotation" if not scan["market_bull"] else "Rotated Out of Top Buffer",
            })

    # 2) ซื้อหุ้นนำตลาด Top Leaders (เฉพาะช่วง Bullish & ผ่าน Circuit Breaker)
    cb_mult = float(circuit_breaker["size_multiplier"]) if circuit_breaker["allow_buy"] else 0.0
    if scan["market_bull"] and cb_mult > 0:
        for r in scan["rankings"]:
            if r["status"] != "ALLOCATE (TOP LEADER)" or r["target_weight_pct"] <= 0:
                continue
            sym = r["ticker"]
            price = float(r["close"])
            if price <= 0:
                continue
            target_val = equity * (r["target_weight_pct"] / 100.0) * cb_mult
            cur_val = float(positions[sym]["qty"]) * price if sym in positions else 0.0
            diff_val = target_val - cur_val
            if diff_val >= min_trade_notional:
                qty = diff_val / price
                stop_p = round(price * 0.85, 2)  # Catastrophic -15% Stop
                orders.append({
                    "symbol": sym,
                    "side": "BUY",
                    "qty": qty,
                    "price": price,
                    "stop_loss": stop_p,
                    "reason": f"Top #{r['rank']} Leader (Weight {r['target_weight_pct'] * cb_mult:.1f}%)",
                })

    # 3) หมุนเงินส่วนป้องกันความเสี่ยงเข้า Safe-Haven (GLD / SHY) เมื่อตลาดเป็น Bearish หรือมีเงินพัก
    if sh_alloc and cb_mult > 0:
        for sh_sym, w_pct in sh_alloc.items():
            price = float(price_map.get(sh_sym, 0.0))
            if price <= 0 or w_pct <= 0:
                continue
            target_val = equity * (w_pct / 100.0) * cb_mult
            cur_val = float(positions[sh_sym]["qty"]) * price if sh_sym in positions else 0.0
            diff_val = target_val - cur_val
            if diff_val >= min_trade_notional:
                orders.append({
                    "symbol": sh_sym,
                    "side": "BUY",
                    "qty": diff_val / price,
                    "price": price,
                    "stop_loss": 0.0,
                    "reason": f"Safe-Haven Rotation ({w_pct * cb_mult:.1f}%)",
                })

    return orders


def run_daily_cycle(period: str = "2y", top_n: int = 5, hold_buffer: int = 15, execute: bool = False) -> dict:
    mode_lbl = "LIVE/PAPER EXECUTE" if execute else "DRY-RUN (จำลองปลอดภัย)"
    _log(f"=== เริ่มรอบ Daily Runner v7.0 Final [{mode_lbl}] ===")

    # 1. โหลดข้อมูล SPY, Safe-Haven (GLD/SHY) และตะกร้า 30 หุ้นผ่าน SQLite Cache
    spy_close = be.fetch_ohlcv("SPY", period)["close"]
    safe_haven_map = {}
    latest_prices = {}
    for sh_sym in qv5.SAFE_HAVEN_ASSETS:
        try:
            sh_s = be.fetch_ohlcv(sh_sym, period)["close"]
            safe_haven_map[sh_sym] = sh_s
            latest_prices[sh_sym] = float(sh_s.iloc[-1])
        except Exception as e:
            _log(f"[Warn] ข้าม Safe-Haven {sh_sym}: {e}")

    close_map = {}
    for sym in qv5.LIQUID_UNIVERSE_30:
        try:
            s_close = be.fetch_ohlcv(sym, period)["close"]
            close_map[sym] = s_close
            latest_prices[sym] = float(s_close.iloc[-1])
        except Exception as e:
            _log(f"[Warn] ข้าม {sym}: {e}")

    # 2. สแกน Cross-Sectional Universe & เช็กสถานะพอร์ต + Circuit Breaker
    scan = qv5.scan_cross_sectional_universe(
        close_map, spy_close, top_n=top_n, hold_buffer=hold_buffer, safe_haven_map=safe_haven_map
    )
    acc = bb.get_account_summary(latest_prices)
    readiness = bb.get_live_readiness_report(latest_prices)
    cb = readiness["circuit_breaker"]

    _log(f"Market Regime   : {scan['spy_regime_label']}")
    _log(f"Account Equity  : ${acc['equity']:,.2f} | Cash: ${acc['cash']:,.2f} | Open Positions: {len(acc['positions'])}")
    _log(f"Circuit Breaker : [{cb['status']}] {cb['reason']} (Size Mult: {cb['size_multiplier']:.1f}x)")

    top5_str = ", ".join(f"#{r['rank']} {r['ticker']}({r['target_weight_pct']:.1f}%)" for r in scan["rankings"][:top_n])
    sh_str = ", ".join(f"{k}({v:.0f}%)" for k, v in scan.get("safe_haven_alloc", {}).items()) or "None"
    _log(f"Top {top_n} Ranked   : {top5_str} | Safe-Haven: {sh_str} | Cash: {scan['cash_weight_pct']:.1f}%")

    # 3. คำนวณแผน Rebalance และส่งคำสั่ง (เฉพาะเมื่อระบุ --execute)
    orders = build_rebalance_plan(scan, acc, cb, latest_prices=latest_prices)
    executed_results = []
    if not orders:
        _log("ไม่มีรายการ Rebalance ที่ต้องส่งคำสั่งในรอบนี้ (พอร์ตสอดคล้องกับเป้าหมายแล้ว)")
    else:
        _log(f"พบแผนคำสั่ง Smart Limit Order จำนวน {len(orders)} รายการ:")
        for o in orders:
            lim_p = o["price"] * 1.002 if o["side"] == "BUY" else o["price"] * 0.998
            _log(
                f"  -> {o['side']:<4} {o['symbol']:<6} | Qty: {o['qty']:,.4f} | Ref: {o['price']:,.2f} | "
                f"Limit: {lim_p:,.2f} | Stop: {o['stop_loss']:,.2f} | เหตุผล: {o['reason']}"
            )
            if execute:
                res = bb.execute_confirmed_order(
                    symbol=o["symbol"],
                    side=o["side"],
                    qty=o["qty"],
                    price=o["price"],
                    stop_loss=o["stop_loss"],
                    order_type="limit",
                )
                executed_results.append(res)
                _log(f"     [Result] {res['message']}")

    # 4. แสดงสถานะใบผ่านทางสู่เงินจริง + ส่ง 1-Channel Webhook Alert (Discord / Telegram ถ้าตั้งค่าไว้)
    chk = readiness["checks"]
    _log(
        f"Live Readiness  : [{readiness['status_label']}] "
        f"Closed Trades {readiness['closed_sells']}/{readiness['target_closed_trades']} "
        f"({'OK' if chk['min_30_closed_trades'] else 'WAIT'}) | "
        f"Live DD {readiness['live_drawdown_pct']:.2f}% ({'OK' if chk['drawdown_within_10pct'] else 'FAIL'}) | "
        f"Paper Ret {readiness['live_return_pct']:+.2f}%"
    )
    alert_text = (
        f"⚡ AI Quant v7.0 [{mode_lbl}]\n"
        f"• Regime: {scan['spy_regime_label']}\n"
        f"• Equity: ${acc['equity']:,.2f} | CB: {cb['status']} ({cb['drawdown_pct']:.2f}%)\n"
        f"• Safe-Haven: {sh_str} | Orders: {len(orders)}\n"
        f"• Paper Gate: {readiness['closed_sells']}/{readiness['target_closed_trades']} trades"
    )
    alert_res = send_webhook_alert(alert_text)
    if alert_res["sent"]:
        _log(f"ส่งแจ้งเตือน Webhook สำเร็จ ({', '.join(alert_res['channels'])})")
    _log("=== จบรอบ Daily Runner v7.0 Final ===\n")
    return {"scan": scan, "account": acc, "readiness": readiness, "orders": orders, "executed": executed_results, "alert": alert_res}


def main():
    p = argparse.ArgumentParser(description="Headless Daily Production Runner (AI Quant v7.0 Final)")
    p.add_argument("-p", "--period", default="2y", help="ช่วงข้อมูลย้อนหลังสำหรับคำนวณ Momentum (ค่าเริ่มต้น 2y)")
    p.add_argument("--top-n", type=int, default=5, help="จำนวนหุ้น Top Leaders สูงสุดที่จะถือครอง (ค่าเริ่มต้น 5)")
    p.add_argument("--hold-buffer", type=int, default=15, help="อันดับกันชนไม่ขายออกก่อนเวลา (ค่าเริ่มต้น 15)")
    p.add_argument("--dry-run", action="store_true", help="โหมดจำลองปลอดภัย (คำนวณและแสดงแผนคำสั่งโดยไม่ส่งออเดอร์)")
    p.add_argument("--execute", action="store_true", help="ส่งคำสั่ง Smart Limit Order จริงเข้าสู่โบรกเกอร์ที่ตั้งค่าไว้")
    args = p.parse_args()

    do_execute = bool(args.execute) and not bool(args.dry_run)
    run_daily_cycle(period=args.period, top_n=args.top_n, hold_buffer=args.hold_buffer, execute=do_execute)


if __name__ == "__main__":
    main()
