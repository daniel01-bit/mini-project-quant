# ⚡ AI Quant Workbench v7.0 Final — Production & Portfolio Standard

ระบบวิเคราะห์หลักทรัพย์เชิงปริมาณ (Quantitative Research), คัดกรองหุ้นนำตลาดแบบ Cross-Sectional (30 หุ้นสภาพคล่องสูง), ทดสอบย้อนหลังแบบไร้ Look-ahead Bias (Dynamic Slippage + Rolling Walk-Forward Gate), เกราะตัดวงจรพอร์ตรวม (Portfolio Circuit Breaker) และระบบส่งคำสั่งอัตโนมัติแบบ Headless (`daily_runner.py`) พร้อมหน้าต่าง GUI สไตล์ VS Code Dark

---

## 🏗️ 1. สถาปัตยกรรมระบบ (Lean Modular Architecture)

```mermaid
flowchart TD
    subgraph Entrypoints["🚀 Execution Entrypoints"]
        GUI["quant_gui.py\n(VS Code Dark Workbench + 6 Actionable Chart Modes)"]
        CLI["backtest_engine.py\n(CLI Backtest, 30-Stock Universe Scan & WFO Gate)"]
        HEADLESS["daily_runner.py\n(Headless Daily Cron / Task Scheduler Runner)"]
    end

    subgraph Core_Quant["📐 Quantitative & Validation Core"]
        QV5["quant_v5_institutional.py\n(4 Core Strategies, Cross-Sectional Scanner, Rolling WFO Gate & Slippage)"]
        QV4["quant_v4_modules.py\n(SQLite Price Cache runs.db, ML Meta-Model & Risk Parity)"]
    end

    subgraph Broker_Agent["🏦 Execution & Co-Pilot Bridge"]
        BB["broker_bridge.py\n(Portfolio Circuit Breaker -5%/-8%, Smart Limit Orders, Alpaca & Local Paper)"]
        HB["hermes_bridge.py\n(Hermes Agent & home-repo Memory Sync)"]
    end

    subgraph QA["🧪 Automated Tests (8/8 OK)"]
        TEST["tests/test_quant_v5.py"]
    end

    GUI --> CLI
    CLI --> QV5
    CLI --> QV4
    HEADLESS --> CLI
    HEADLESS --> QV5
    HEADLESS --> BB
    GUI --> BB
    GUI --> HB
    TEST --> CLI
    TEST --> QV5
    TEST --> BB
```

### 4 กลยุทธ์แกนหลักที่ผ่านการคัดกรอง (Pruned from 13 $\rightarrow$ 4 Cores)
1. **`buy_hold`**: Benchmark มาตรฐาน
2. **`trend_atr_vol`**: Trend-Following + ATR Chandelier Trailing Stop (`3.2x`) + Volatility-Targeted Sizing
3. **`regime_adaptive_v5`**: All-Weather Switching (Trending $\rightarrow$ รันเทรนด์ / Sideways $\rightarrow$ ซื้อย่อกรอบล่างขายกรอบบน / Bear $\rightarrow$ เงินสด 100%)
4. **`cross_sectional_mom`**: Relative Strength Leader เทียบดัชนีตลาด (`^GSPC` / `SPY`) + Weekly MTF

---

## 🛡️ 2. มาตรฐานการคุมความเสี่ยงระดับ Production (v7.0 Final)
- **Zero Look-Ahead & Zero Selection Bias:** Shift สัญญาณ 1 แท่ง (`shift(1)`), Clip น้ำหนัก `[0.0, 1.0]`, คัดผู้ชนะเฉพาะช่วง In-Sample (70% แรก) และ Rolling Walk-Forward (`252d Train -> 63d OOS`)
- **Realistic Cost Modeling:** หัก Commission (`0.1%`) + Dynamic Volatility-Adjusted Slippage (`ATR/Volume` & `5 bps` Limit Fill)
- **Portfolio-Level Circuit Breaker:**
  - Live Drawdown แตะ **`-5.0%`** $\rightarrow$ ลดขนาดไม้ซื้อใหม่ลง **50% (`HALF_SIZE`)** อัตโนมัติ
  - Live Drawdown แตะ **`-8.0%`** $\rightarrow$ ล็อกห้ามเปิดไม้ซื้อใหม่ (**`HALT_NEW_BUYS`**) ยอมให้ขายออกเท่านั้น
- **Smart Limit Execution:** ส่งคำสั่งเข้า Alpaca / Local Paper เป็น **`Limit Order`** (`±0.2%` Buffer) แทนการเคาะ Market Order มืดบอด
- **Live Capital Readiness Gate:** ติดตามความคืบหน้า Paper Trade อัตโนมัติ (ต้องครบ **30 ไม้ปิดสถานะ**, `Live DD > -10%`, และ `Paper Return >= 0%` ก่อนย้ายสู่เงินจริง)

---

## 🚀 3. คู่มือรันและทดสอบด้วยตัวเอง (Self-Test Commands)

### 1) ติดตั้งแพ็กเกจ (ครั้งแรกครั้งเดียว)
```powershell
pip install -r requirements.txt
```

### 2) รันชุด Unit Test ทั้งหมด (`8/8 Tests`)
```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

### 3) ทดสอบสแกนตะกร้า 30 หุ้น + Cross-Sectional Backtest + Go/No-Go Gate
```powershell
python backtest_engine.py --universe-scan --period 2y --top-n 5
```

### 4) ทดสอบ Headless Daily Runner (โหมดปลอดภัย Dry-Run — ยังไม่ส่งออเดอร์)
```powershell
python daily_runner.py --dry-run
```
*(เมื่อพร้อมส่งคำสั่งเข้าพอร์ตจำลอง Local Paper หรือ Alpaca Paper ให้เปลี่ยน `--dry-run` เป็น `--execute`)*

### 5) เปิดหน้าต่าง GUI Dashboard (`v7.0 Final`)
ดับเบิลคลิก **`run_dashboard.bat`** หรือรัน:
```powershell
python quant_gui.py
```

### 6) ตัวอย่างตั้งรันอัตโนมัติวันละครั้งบน AWS EC2 Ubuntu (Cron)
```bash
35 14 * * 1-5 cd /home/ubuntu/mini-project-quant01 && /usr/bin/python3 daily_runner.py --execute >> logs/cron.log 2>&1
```
