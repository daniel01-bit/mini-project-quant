#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
broker_bridge.py — ระบบเชื่อมต่อบัญชีเทรดจริงและพอร์ตจำลอง (Broker & Exchange Execution Bridge)
รองรับ 3 โหมดเชื่อมต่อ (สลับได้จากหน้า GUI พร้อมระบบ Semi-Auto 1-Click Confirm):
  1) local_paper : พอร์ตจำลองในเครื่อง (SQLite runs.db) รองรับทั้งหุ้นและคริปโตทันทีโดยไม่ต้องใช้ API Key
  2) alpaca      : Alpaca Markets REST API สำหรับเทรดหุ้นสหรัฐฯ (เช่น NVDA, AAPL, QQQ) รองรับทั้ง Paper & Live
  3) binance     : Binance Spot REST API (HMAC-SHA256) สำหรับดึงพอร์ตคริปโตจริง (เช่น BTCUSDT) และส่งคำสั่งซื้อขาย
"""

import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(WORK_DIR, "broker_config.json")
DB_PATH = os.path.join(WORK_DIR, "runs.db")


DEFAULT_BROKER_CONFIG = {
    "active_broker": "local_paper",  # local_paper | alpaca | binance
    "environment": "paper",          # paper (Testnet/Paper) | live (เงินจริง)
    "local_initial_cash": 100000.0,
    "alpaca": {
        "api_key": "",
        "api_secret": "",
        "paper_url": "https://paper-api.alpaca.markets",
        "live_url": "https://api.alpaca.markets",
    },
    "binance": {
        "api_key": "",
        "api_secret": "",
        "testnet_url": "https://testnet.binance.vision",
        "live_url": "https://api.binance.com",
    },
}


def load_broker_config() -> dict:
    """โหลดการตั้งค่าโบรกเกอร์และ API Key จากไฟล์ broker_config.json"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            merged = DEFAULT_BROKER_CONFIG.copy()
            merged.update(cfg)
            return merged
        except Exception:
            pass
    return DEFAULT_BROKER_CONFIG.copy()


def save_broker_config(cfg: dict):
    """บันทึกการตั้งค่าโบรกเกอร์ลงไฟล์ broker_config.json"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ==========================================
# 1. SQLite Tables สำหรับ Local Paper Portfolio & Order Audit Log
# ==========================================
def ensure_broker_tables(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS broker_account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL NOT NULL,
            initial_cash REAL NOT NULL,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS broker_positions (
            symbol TEXT PRIMARY KEY,
            qty REAL NOT NULL,
            avg_price REAL NOT NULL,
            stop_loss REAL,
            last_price REAL,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS broker_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broker TEXT,
            env_mode TEXT,
            symbol TEXT,
            side TEXT,
            qty REAL,
            price REAL,
            stop_loss REAL,
            notional REAL,
            status TEXT,
            raw_response TEXT,
            created_at TEXT
        )
    """)
    row = conn.execute("SELECT cash FROM broker_account WHERE id = 1").fetchone()
    if not row:
        cfg = load_broker_config()
        init_c = float(cfg.get("local_initial_cash", 100000.0))
        conn.execute(
            "INSERT INTO broker_account (id, cash, initial_cash, updated_at) VALUES (1, ?, ?, ?)",
            (init_c, init_c, datetime.now().isoformat()),
        )
    # อัปเกรดคอลัมน์ peak_equity อัตโนมัติสำหรับ Portfolio Circuit Breaker (v7.0 Final)
    acc_cols = {r[1] for r in conn.execute("PRAGMA table_info(broker_account)").fetchall()}
    if "peak_equity" not in acc_cols:
        conn.execute("ALTER TABLE broker_account ADD COLUMN peak_equity REAL")
        conn.execute("UPDATE broker_account SET peak_equity = MAX(cash, initial_cash) WHERE id = 1")
    conn.commit()
    conn.close()


def reset_local_paper_account(initial_cash: float = 100000.0, db_path: str = DB_PATH):
    """รีเซ็ตพอร์ตจำลอง Local Paper กลับเป็นเงินสดเริ่มต้น"""
    ensure_broker_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE broker_account SET cash = ?, initial_cash = ?, peak_equity = ?, updated_at = ? WHERE id = 1",
        (initial_cash, initial_cash, initial_cash, datetime.now().isoformat()),
    )
    conn.execute("DELETE FROM broker_positions")
    conn.commit()
    conn.close()


def evaluate_circuit_breaker(
    current_equity: float,
    peak_equity: float,
    half_size_dd_pct: float = -5.0,
    halt_dd_pct: float = -8.0,
) -> dict:
    """
    ระบบตัดวงจรพอร์ตรวม (Portfolio-Level Circuit Breaker v7.0 Final):
      - Drawdown > -5.0%          -> NORMAL        (size_mult = 1.0, อนุญาตเปิดไม้ปกติ)
      - -8.0% < Drawdown <= -5.0% -> HALF_SIZE     (size_mult = 0.5, ลดขนาดไม้ซื้อลงครึ่งหนึ่งอัตโนมัติ)
      - Drawdown <= -8.0%         -> HALT_NEW_BUYS (size_mult = 0.0, ห้ามเปิดไม้ซื้อใหม่ ยอมให้ขายออกเท่านั้น)
    """
    eff_peak = max(float(peak_equity), float(current_equity), 1.0)
    dd_pct = ((float(current_equity) - eff_peak) / eff_peak) * 100.0
    if dd_pct <= halt_dd_pct:
        return {
            "status": "HALT_NEW_BUYS",
            "size_multiplier": 0.0,
            "drawdown_pct": dd_pct,
            "peak_equity": eff_peak,
            "allow_buy": False,
            "reason": f"Circuit Breaker ทำงาน! พอร์ต Drawdown แตะ {dd_pct:.2f}% (<= {halt_dd_pct:.1f}%) ล็อกการเปิดไม้ซื้อใหม่ทันที",
        }
    elif dd_pct <= half_size_dd_pct:
        return {
            "status": "HALF_SIZE",
            "size_multiplier": 0.5,
            "drawdown_pct": dd_pct,
            "peak_equity": eff_peak,
            "allow_buy": True,
            "reason": f"Circuit Breaker เตือนภัย: พอร์ต Drawdown {dd_pct:.2f}% (<= {half_size_dd_pct:.1f}%) ลดขนาดไม้ซื้อลง 50%",
        }
    return {
        "status": "NORMAL",
        "size_multiplier": 1.0,
        "drawdown_pct": dd_pct,
        "peak_equity": eff_peak,
        "allow_buy": True,
        "reason": f"พอร์ตปกติ (Live Drawdown {dd_pct:.2f}%)",
    }


def get_live_readiness_report(latest_prices: dict[str, float] | None = None, db_path: str = DB_PATH) -> dict:
    """
    ตรวจสอบใบผ่านทางสู่เงินจริง (Live Capital Readiness Gate — Phase 3):
      1) จำนวนคำสั่งขายปิดสถานะ (Paper Closed Trades) >= 30 ไม้
      2) Live Paper Drawdown > -10.0%
      3) Portfolio Circuit Breaker พร้อมทำงาน
    """
    ensure_broker_tables(db_path)
    summary = get_account_summary(latest_prices) if db_path == DB_PATH else {"equity": 100000.0}
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT initial_cash, peak_equity FROM broker_account WHERE id = 1").fetchone()
    init_c = float(row[0]) if row else 100000.0
    peak_eq = float(row[1]) if (row and row[1]) else init_c
    cur_eq = float(summary.get("equity", init_c))
    if cur_eq > peak_eq:
        peak_eq = cur_eq
        conn.execute("UPDATE broker_account SET peak_equity = ? WHERE id = 1", (peak_eq,))
        conn.commit()

    orders = conn.execute(
        "SELECT side, status FROM broker_orders WHERE status IN ('FILLED', 'filled', 'ACCEPTED', 'accepted', 'NEW', 'SUBMITTED')"
    ).fetchall()
    conn.close()

    total_orders = len(orders)
    closed_sells = sum(1 for side, _ in orders if str(side).upper() == "SELL")
    cb = evaluate_circuit_breaker(cur_eq, peak_eq)
    ret_pct = ((cur_eq / max(init_c, 1.0)) - 1.0) * 100.0

    chk_trades = closed_sells >= 30
    chk_dd = cb["drawdown_pct"] > -10.0
    chk_pnl = ret_pct >= 0.0
    ready = chk_trades and chk_dd and chk_pnl

    return {
        "ready_for_live": ready,
        "status_label": "READY_FOR_LIVE" if ready else "PAPER_VALIDATION_IN_PROGRESS",
        "total_orders": total_orders,
        "closed_sells": closed_sells,
        "target_closed_trades": 30,
        "live_return_pct": ret_pct,
        "live_drawdown_pct": cb["drawdown_pct"],
        "peak_equity": peak_eq,
        "circuit_breaker": cb,
        "checks": {
            "min_30_closed_trades": chk_trades,
            "drawdown_within_10pct": chk_dd,
            "non_negative_paper_return": chk_pnl,
            "circuit_breaker_armed": True,
        },
    }


def log_order_audit(
    broker: str,
    env_mode: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    stop_loss: float,
    status: str,
    raw_resp: str = "",
    db_path: str = DB_PATH,
):
    ensure_broker_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO broker_orders (
            broker, env_mode, symbol, side, qty, price, stop_loss, notional, status, raw_response, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            broker,
            env_mode,
            symbol,
            side,
            qty,
            price,
            stop_loss,
            qty * price,
            status,
            raw_resp[:500],
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_order_history(limit: int = 30, db_path: str = DB_PATH) -> list[dict]:
    ensure_broker_tables(db_path)
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT id, broker, env_mode, symbol, side, qty, price, stop_loss, notional, status, created_at
        FROM broker_orders ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "broker": r[1],
            "env_mode": r[2],
            "symbol": r[3],
            "side": r[4],
            "qty": r[5],
            "price": r[6],
            "stop_loss": r[7],
            "notional": r[8],
            "status": r[9],
            "created_at": r[10],
        }
        for r in rows
    ]


# ==========================================
# 2. ดึงสถานะบัญชีและพอร์ตถือครอง (Account & Positions Sync)
# ==========================================
def normalize_binance_symbol(ticker: str) -> str:
    """แปลงชื่อ Ticker มาตรฐาน เช่น BTC-USD -> BTCUSDT สำหรับ Binance"""
    t = ticker.upper().replace("^", "").strip()
    if t.endswith("-USD"):
        return t.replace("-USD", "USDT")
    if not t.endswith("USDT") and t in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"):
        return t + "USDT"
    return t


def get_account_summary(latest_prices: dict[str, float] | None = None) -> dict:
    """
    ดึงข้อมูลยอดเงินสด, มูลค่าพอร์ตรวม (Equity), กำไร/ขาดทุน และรายการสินทรัพย์ที่ถืออยู่จริง
    ตามโบรกเกอร์ที่เลือกไว้ใน broker_config.json
    """
    cfg = load_broker_config()
    broker = cfg.get("active_broker", "local_paper")
    env_mode = cfg.get("environment", "paper")
    latest_prices = latest_prices or {}

    if broker == "alpaca":
        return _fetch_alpaca_account(cfg, env_mode)
    elif broker == "binance":
        return _fetch_binance_account(cfg, env_mode, latest_prices)
    else:
        return _fetch_local_paper_account(latest_prices)


def _fetch_local_paper_account(latest_prices: dict[str, float]) -> dict:
    ensure_broker_tables()
    conn = sqlite3.connect(DB_PATH)
    acc = conn.execute("SELECT cash, initial_cash FROM broker_account WHERE id = 1").fetchone()
    cash = float(acc[0]) if acc else 100000.0
    init_cash = float(acc[1]) if acc else 100000.0

    pos_rows = conn.execute(
        "SELECT symbol, qty, avg_price, stop_loss, last_price FROM broker_positions WHERE qty > 0"
    ).fetchall()

    positions = []
    market_val = 0.0
    for sym, qty, avg_p, stop_p, last_p in pos_rows:
        cur_p = float(latest_prices.get(sym, last_p if last_p else avg_p))
        if sym in latest_prices:
            conn.execute("UPDATE broker_positions SET last_price = ? WHERE symbol = ?", (cur_p, sym))
        m_val = qty * cur_p
        market_val += m_val
        pnl = (cur_p - avg_p) * qty
        pnl_pct = ((cur_p / avg_p) - 1.0) * 100.0 if avg_p > 0 else 0.0
        positions.append({
            "symbol": sym,
            "qty": float(qty),
            "avg_price": float(avg_p),
            "current_price": cur_p,
            "stop_loss": float(stop_p or 0.0),
            "market_value": m_val,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
        })
    conn.commit()
    conn.close()

    equity = cash + market_val
    total_pnl = equity - init_cash
    total_pnl_pct = ((equity / init_cash) - 1.0) * 100.0 if init_cash > 0 else 0.0

    return {
        "ok": True,
        "broker": "local_paper",
        "env_mode": "paper",
        "status_text": "เชื่อมต่อ Local Paper Portfolio (SQLite) สำเร็จ",
        "cash": cash,
        "market_value": market_val,
        "equity": equity,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "positions": positions,
    }


def _fetch_alpaca_account(cfg: dict, env_mode: str) -> dict:
    alp = cfg.get("alpaca", {})
    key = alp.get("api_key", "").strip()
    sec = alp.get("api_secret", "").strip()
    base_url = alp.get("live_url") if env_mode == "live" else alp.get("paper_url")

    if not key or not sec:
        return {
            "ok": False,
            "broker": "alpaca",
            "env_mode": env_mode,
            "status_text": "⚠️ ยังไม่ได้ตั้งค่า Alpaca API Key / Secret (กดปุ่ม '⚙ ตั้งค่าบัญชี/API')",
            "cash": 0.0,
            "market_value": 0.0,
            "equity": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "positions": [],
        }

    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": sec,
        "Accept": "application/json",
    }
    try:
        req_acc = urllib.request.Request(f"{base_url}/v2/account", headers=headers, method="GET")
        with urllib.request.urlopen(req_acc, timeout=10) as r:
            acc_data = json.loads(r.read().decode("utf-8"))

        req_pos = urllib.request.Request(f"{base_url}/v2/positions", headers=headers, method="GET")
        with urllib.request.urlopen(req_pos, timeout=10) as r:
            pos_data = json.loads(r.read().decode("utf-8"))

        cash = float(acc_data.get("cash", 0.0))
        equity = float(acc_data.get("equity", 0.0))
        last_eq = float(acc_data.get("last_equity", equity))
        market_val = float(acc_data.get("long_market_value", equity - cash))
        pnl = equity - last_eq
        pnl_pct = ((equity / last_eq) - 1.0) * 100.0 if last_eq > 0 else 0.0

        positions = []
        for p in pos_data:
            positions.append({
                "symbol": p.get("symbol"),
                "qty": float(p.get("qty", 0.0)),
                "avg_price": float(p.get("avg_entry_price", 0.0)),
                "current_price": float(p.get("current_price", 0.0)),
                "stop_loss": 0.0,
                "market_value": float(p.get("market_value", 0.0)),
                "unrealized_pnl": float(p.get("unrealized_pl", 0.0)),
                "unrealized_pnl_pct": float(p.get("unrealized_plpc", 0.0)) * 100.0,
            })

        return {
            "ok": True,
            "broker": "alpaca",
            "env_mode": env_mode,
            "status_text": f"✅ เชื่อมต่อ Alpaca ({env_mode.upper()}) สำเร็จ | Status: {acc_data.get('status')}",
            "cash": cash,
            "market_value": market_val,
            "equity": equity,
            "total_pnl": pnl,
            "total_pnl_pct": pnl_pct,
            "positions": positions,
        }
    except Exception as e:
        return {
            "ok": False,
            "broker": "alpaca",
            "env_mode": env_mode,
            "status_text": f"❌ เชื่อมต่อ Alpaca ไม่สำเร็จ: {e}",
            "cash": 0.0,
            "market_value": 0.0,
            "equity": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "positions": [],
        }


def _fetch_binance_account(cfg: dict, env_mode: str, latest_prices: dict[str, float]) -> dict:
    bnc = cfg.get("binance", {})
    key = bnc.get("api_key", "").strip()
    sec = bnc.get("api_secret", "").strip()
    base_url = bnc.get("live_url") if env_mode == "live" else bnc.get("testnet_url")

    if not key or not sec:
        return {
            "ok": False,
            "broker": "binance",
            "env_mode": env_mode,
            "status_text": "⚠️ ยังไม่ได้ตั้งค่า Binance API Key / Secret (กดปุ่ม '⚙ ตั้งค่าบัญชี/API')",
            "cash": 0.0,
            "market_value": 0.0,
            "equity": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "positions": [],
        }

    try:
        ts = int(time.time() * 1000)
        qs = f"timestamp={ts}&recvWindow=10000"
        sig = hmac.new(sec.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"{base_url}/api/v3/account?{qs}&signature={sig}"
        req = urllib.request.Request(url, headers={"X-MBX-APIKEY": key}, method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            acc_data = json.loads(r.read().decode("utf-8"))

        # ดึงราคาคริปโตทั้งหมดเพื่อตีมูลค่าเป็น USDT
        req_p = urllib.request.Request(f"{base_url}/api/v3/ticker/price", method="GET")
        with urllib.request.urlopen(req_p, timeout=10) as rp:
            price_list = json.loads(rp.read().decode("utf-8"))
        price_map = {item["symbol"]: float(item["price"]) for item in price_list}

        usdt_cash = 0.0
        market_val = 0.0
        positions = []

        for b in acc_data.get("balances", []):
            asset = b.get("asset", "")
            total_qty = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
            if total_qty <= 0:
                continue
            if asset in ("USDT", "USDC", "BUSD", "FDUSD"):
                usdt_cash += total_qty
            else:
                pair = f"{asset}USDT"
                cur_p = price_map.get(pair, latest_prices.get(f"{asset}-USD", 0.0))
                m_val = total_qty * cur_p
                if m_val < 1.0:
                    continue
                market_val += m_val
                positions.append({
                    "symbol": f"{asset}USDT",
                    "qty": total_qty,
                    "avg_price": cur_p,
                    "current_price": cur_p,
                    "stop_loss": 0.0,
                    "market_value": m_val,
                    "unrealized_pnl": 0.0,
                    "unrealized_pnl_pct": 0.0,
                })

        equity = usdt_cash + market_val
        return {
            "ok": True,
            "broker": "binance",
            "env_mode": env_mode,
            "status_text": f"✅ เชื่อมต่อ Binance Spot ({env_mode.upper()}) สำเร็จ",
            "cash": usdt_cash,
            "market_value": market_val,
            "equity": equity,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "positions": positions,
        }
    except Exception as e:
        return {
            "ok": False,
            "broker": "binance",
            "env_mode": env_mode,
            "status_text": f"❌ เชื่อมต่อ Binance ไม่สำเร็จ: {e}",
            "cash": 0.0,
            "market_value": 0.0,
            "equity": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "positions": [],
        }


# ==========================================
# 3. ส่งคำสั่งซื้อขายแบบ Semi-Auto (Confirm Order Execution)
# ==========================================
def execute_confirmed_order(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    stop_loss: float = 0.0,
    order_type: str = "limit",
    limit_buffer_pct: float = 0.002,
    enforce_circuit_breaker: bool = True,
) -> dict:
    """
    ส่งคำสั่งซื้อขาย v7.0 Final (Smart Limit Order + Portfolio Circuit Breaker Protection):
      - ค่าเริ่มต้นส่งเป็น Limit Order (เผื่อ Buffer 0.2% เพื่อกัน Slippage เหวี่ยงตอนตลาดเปิด แทนการเคาะ Market Order มืดบอด)
      - บังคับตรวจสอบ Portfolio Circuit Breaker ก่อนสั่ง BUY (-5% ลดขนาดไม้ครึ่งหนึ่ง, -8% ล็อกการซื้อใหม่ทันที)
    """
    cfg = load_broker_config()
    broker = cfg.get("active_broker", "local_paper")
    env_mode = cfg.get("environment", "paper")
    side = side.upper().strip()

    if qty <= 0 or price <= 0:
        return {"ok": False, "message": "จำนวน (Qty) และราคาต้องมากกว่า 0"}

    # บังคับตรวจ Portfolio Circuit Breaker ก่อนส่งคำสั่ง BUY
    cb_note = ""
    if enforce_circuit_breaker and side == "BUY":
        readiness = get_live_readiness_report({symbol: price})
        cb = readiness["circuit_breaker"]
        if not cb["allow_buy"]:
            return {"ok": False, "message": f"🛑 {cb['reason']}"}
        if cb["size_multiplier"] < 1.0:
            qty = qty * cb["size_multiplier"]
            cb_note = f" [Circuit Breaker {cb['status']}: ลดไม้เหลือ {cb['size_multiplier']*100:.0f}%]"

    if broker == "alpaca":
        res = _execute_alpaca_order(
            cfg, env_mode, symbol, side, qty, price, stop_loss, order_type=order_type, limit_buffer_pct=limit_buffer_pct
        )
    elif broker == "binance":
        res = _execute_binance_order(cfg, env_mode, symbol, side, qty, price, stop_loss)
    else:
        res = _execute_local_paper_order(symbol, side, qty, price, stop_loss, order_type=order_type)

    if cb_note and res.get("ok"):
        res["message"] = res["message"] + cb_note
    return res


def _execute_local_paper_order(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    stop_loss: float,
    order_type: str = "limit",
    db_path: str = DB_PATH,
) -> dict:
    ensure_broker_tables(db_path)
    conn = sqlite3.connect(db_path)
    acc_row = conn.execute("SELECT cash, peak_equity FROM broker_account WHERE id = 1").fetchone()
    cash = float(acc_row[0])
    peak_eq = float(acc_row[1]) if acc_row[1] else cash
    pos = conn.execute("SELECT qty, avg_price FROM broker_positions WHERE symbol = ?", (symbol,)).fetchone()
    cur_qty = float(pos[0]) if pos else 0.0
    cur_avg = float(pos[1]) if pos else 0.0

    # จำลอง Slippage จริง 0.05% สำหรับ Limit Order (5 bps) + Commission 0.1%
    slip = 0.0005 if order_type.lower() == "limit" else 0.0012
    exec_price = price * (1.0 + slip) if side == "BUY" else price * (1.0 - slip)
    notional = qty * exec_price
    fee = notional * 0.001  # ค่าธรรมเนียมจำลอง 0.1%

    if side == "BUY":
        if cash < notional + fee:
            conn.close()
            return {"ok": False, "message": f"เงินสดในพอร์ตไม่พอ (ต้องการ {notional+fee:,.2f} แต่มี {cash:,.2f})"}
        new_cash = cash - notional - fee
        new_qty = cur_qty + qty
        new_avg = ((cur_qty * cur_avg) + notional) / new_qty if new_qty > 0 else exec_price
        conn.execute("UPDATE broker_account SET cash = ?, updated_at = ? WHERE id = 1", (new_cash, datetime.now().isoformat()))
        conn.execute(
            """
            INSERT INTO broker_positions (symbol, qty, avg_price, stop_loss, last_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                qty = excluded.qty,
                avg_price = excluded.avg_price,
                stop_loss = excluded.stop_loss,
                last_price = excluded.last_price,
                updated_at = excluded.updated_at
            """,
            (symbol, new_qty, new_avg, stop_loss, price, datetime.now().isoformat()),
        )
        msg = f"✅ [Local Paper {order_type.upper()}] ซื้อ (BUY) {symbol} จำนวน {qty:,.4f} หน่วย @ {exec_price:,.2f} (รวม {notional:,.2f}, Stop-Loss {stop_loss:,.2f})"
    else:
        if cur_qty <= 0:
            conn.close()
            return {"ok": False, "message": f"ไม่มีสถานะถือครองของ {symbol} ให้ขาย"}
        sell_qty = min(qty, cur_qty)
        sell_notional = sell_qty * exec_price
        sell_fee = sell_notional * 0.001
        new_cash = cash + sell_notional - sell_fee
        rem_qty = cur_qty - sell_qty
        conn.execute("UPDATE broker_account SET cash = ?, updated_at = ? WHERE id = 1", (new_cash, datetime.now().isoformat()))
        if rem_qty <= 1e-6:
            conn.execute("DELETE FROM broker_positions WHERE symbol = ?", (symbol,))
        else:
            if stop_loss > 0:
                conn.execute(
                    "UPDATE broker_positions SET qty = ?, stop_loss = ?, last_price = ? WHERE symbol = ?",
                    (rem_qty, stop_loss, price, symbol),
                )
            else:
                conn.execute("UPDATE broker_positions SET qty = ?, last_price = ? WHERE symbol = ?", (rem_qty, price, symbol))
        msg = f"✅ [Local Paper {order_type.upper()}] ขาย (SELL) {symbol} จำนวน {sell_qty:,.4f} หน่วย @ {exec_price:,.2f} (รับเงินสุทธิ {sell_notional-sell_fee:,.2f})"

    # อัปเดต Peak Equity เพื่อใช้คำนวณ Portfolio Drawdown Circuit Breaker
    pos_val = conn.execute("SELECT COALESCE(SUM(qty * last_price), 0) FROM broker_positions").fetchone()[0]
    new_eq = new_cash + float(pos_val or 0.0)
    if new_eq > peak_eq:
        conn.execute("UPDATE broker_account SET peak_equity = ? WHERE id = 1", (new_eq,))

    conn.commit()
    conn.close()
    log_order_audit("local_paper", "paper", symbol, side, qty, exec_price, stop_loss, "FILLED", msg, db_path=db_path)
    return {"ok": True, "message": msg}


def _execute_alpaca_order(
    cfg: dict,
    env_mode: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    stop_loss: float,
    order_type: str = "limit",
    limit_buffer_pct: float = 0.002,
) -> dict:
    alp = cfg.get("alpaca", {})
    key = alp.get("api_key", "").strip()
    sec = alp.get("api_secret", "").strip()
    base_url = alp.get("live_url") if env_mode == "live" else alp.get("paper_url")
    if not key or not sec:
        return {"ok": False, "message": "ยังไม่ได้กรอก Alpaca API Key / Secret"}

    clean_sym = symbol.replace("^", "")
    is_limit = order_type.lower() == "limit" and price > 0
    payload = {
        "symbol": clean_sym,
        "qty": str(round(qty, 4)),
        "side": side.lower(),
        "type": "limit" if is_limit else "market",
        "time_in_force": "day",
    }
    if is_limit:
        lim_p = price * (1.0 + limit_buffer_pct) if side == "BUY" else price * (1.0 - limit_buffer_pct)
        payload["limit_price"] = str(round(lim_p, 2))
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": sec,
        "Content-Type": "application/json",
    }
    try:
        req = urllib.request.Request(
            f"{base_url}/v2/orders",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            resp = json.loads(r.read().decode("utf-8"))
        status = resp.get("status", "SUBMITTED")
        ord_lbl = f"LIMIT @{payload.get('limit_price')}" if is_limit else "MARKET"
        log_order_audit("alpaca", env_mode, clean_sym, side, qty, price, stop_loss, status, json.dumps(resp))
        return {"ok": True, "message": f"✅ [Alpaca {env_mode.upper()} {ord_lbl}] ส่งคำสั่ง {side} {clean_sym} ({qty:.4f}) สำเร็จ | Status: {status}"}
    except urllib.error.HTTPError as he:
        err_body = he.read().decode("utf-8", errors="ignore")
        log_order_audit("alpaca", env_mode, clean_sym, side, qty, price, stop_loss, "REJECTED", err_body)
        return {"ok": False, "message": f"❌ Alpaca ปฏิเสธคำสั่ง: {err_body}"}
    except Exception as e:
        return {"ok": False, "message": f"❌ ส่งคำสั่ง Alpaca ล้มเหลว: {e}"}


def _execute_binance_order(cfg: dict, env_mode: str, symbol: str, side: str, qty: float, price: float, stop_loss: float) -> dict:
    bnc = cfg.get("binance", {})
    key = bnc.get("api_key", "").strip()
    sec = bnc.get("api_secret", "").strip()
    base_url = bnc.get("live_url") if env_mode == "live" else bnc.get("testnet_url")
    if not key or not sec:
        return {"ok": False, "message": "ยังไม่ได้กรอก Binance API Key / Secret"}

    b_sym = normalize_binance_symbol(symbol)
    params = {
        "symbol": b_sym,
        "side": side.upper(),
        "type": "MARKET",
        "quantity": f"{qty:.5f}".rstrip("0").rstrip("."),
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000,
    }
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(sec.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base_url}/api/v3/order?{qs}&signature={sig}"

    try:
        req = urllib.request.Request(url, headers={"X-MBX-APIKEY": key}, method="POST")
        with urllib.request.urlopen(req, timeout=12) as r:
            resp = json.loads(r.read().decode("utf-8"))
        status = resp.get("status", "FILLED")
        log_order_audit("binance", env_mode, b_sym, side, qty, price, stop_loss, status, json.dumps(resp))
        return {"ok": True, "message": f"✅ [Binance {env_mode.upper()}] ส่งคำสั่ง {side} {b_sym} ({qty:.5f}) สำเร็จ | Status: {status}"}
    except urllib.error.HTTPError as he:
        err_body = he.read().decode("utf-8", errors="ignore")
        log_order_audit("binance", env_mode, b_sym, side, qty, price, stop_loss, "REJECTED", err_body)
        return {"ok": False, "message": f"❌ Binance ปฏิเสธคำสั่ง: {err_body}"}
    except Exception as e:
        return {"ok": False, "message": f"❌ ส่งคำสั่ง Binance ล้มเหลว: {e}"}


def close_all_positions_panic(latest_prices: dict[str, float] | None = None) -> list[dict]:
    """
    ปุ่มฉุกเฉิน (Panic Close All Positions):
    ดึงรายการสินทรัพย์ที่ถืออยู่ทั้งหมดและสั่งขาย (SELL) ปิดสถานะเข้าเงินสดทันที
    """
    summary = get_account_summary(latest_prices)
    positions = summary.get("positions", [])
    results = []
    for p in positions:
        sym = p["symbol"]
        qty = float(p["qty"])
        cur_p = float(p["current_price"] or p["avg_price"])
        if qty > 0 and cur_p > 0:
            res = execute_confirmed_order(sym, "SELL", qty, cur_p, 0.0)
            results.append(res)
    return results
