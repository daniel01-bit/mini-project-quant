#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hermes_bridge.py — ระบบเชื่อมต่อ 2 ทาง (2-Way Sync & Command Bus) ระหว่าง AI Quant Terminal v4.0 กับ Hermes Agent
ความสามารถหลัก:
  1) Auto-Sync Memory: อัปเดตสถานะพอร์ต, สัญญาณสแกนล่าสุด (Quant Score, ML Win%, Optimal Weight%) เข้าสู่:
       - C:\\Users\\ASUS\\Desktop\\mini-project-quant01\\memories\\MEMORY.md
       - C:\\Users\\ASUS\\AppData\\Local\\hermes\\memories\\MEMORY.md
       - C:\\Users\\ASUS\\AppData\\Local\\hermes\\profiles\\mini-project-quant01\\memories\\MEMORY.md
  2) Shared Command Bus (hermes_bus.json):
       - ให้ Hermes Agent ส่งคำสั่ง (เช่น สั่งสแกนหุ้นใหม่, สั่งปรับพอร์ต, หรือส่งข้อความแนะนำ) เข้ามายังหน้าต่าง GUI ได้สดๆ
  3) Hermes Skill Installer:
       - ติดตั้ง Skill 'quant-v4-copilot' ลงในโปรไฟล์ของ Hermes Agent เพื่อให้ Hermes รู้จักคำสั่งควบคุมโปรเจกต์ v4.0 ทันที
วิธีสั่งงานจากฝั่ง Hermes Agent หรือ CLI:
  python hermes_bridge.py status
  python hermes_bridge.py cmd --action scan --tickers "^NDX NVDA AAPL TSLA BTC-USD"
  python hermes_bridge.py cmd --action note --message "Hermes แนะนำให้ถือเงินสดสำรองเพิ่ม"
"""

import argparse
import json
import os
from datetime import datetime

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
BUS_PATH = os.path.join(WORK_DIR, "hermes_bus.json")
LOCAL_MEM_DIR = os.path.join(WORK_DIR, "memories")

HERMES_GLOBAL_MEM = r"C:\Users\ASUS\AppData\Local\hermes\memories\MEMORY.md"
HERMES_PROFILE_DIR = r"C:\Users\ASUS\AppData\Local\hermes\profiles\mini-project-quant01"
HERMES_PROFILE_MEM = os.path.join(HERMES_PROFILE_DIR, "memories", "MEMORY.md")
HERMES_SKILL_DIR = os.path.join(HERMES_PROFILE_DIR, "skills", "quant-v4-copilot")


def ensure_bus_file() -> dict:
    if os.path.exists(BUS_PATH):
        try:
            with open(BUS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    init_data = {
        "last_sync": datetime.now().isoformat(),
        "pending_commands": [],
        "messages": [
            {
                "sender": "Hermes Bridge",
                "time": datetime.now().strftime("%H:%M:%S"),
                "text": "เชื่อมต่อ 2-Way Sync กับ Hermes Agent (โปรไฟล์ mini-project-quant01) พร้อมทำงานแล้ว",
            }
        ],
        "latest_state": {},
    }
    with open(BUS_PATH, "w", encoding="utf-8") as f:
        json.dump(init_data, f, indent=2, ensure_ascii=False)
    return init_data


def install_hermes_skill() -> str:
    """ติดตั้งไฟล์ SKILL.md ลงในโปรไฟล์ของ Hermes Agent เพื่อให้ Hermes รู้วิธีสั่งงาน Quant v4.0"""
    skill_md_content = f"""---
name: quant-v4-copilot
description: สั่งงานและตรวจสอบสถานะของ AI Quant Terminal v4.0 (สแกนหุ้น, ดูพอร์ตจริง/จำลอง, คำนวณ ML Win Prob, จัดพอร์ต Risk Parity และส่งคำสั่งเข้าหน้า GUI)
---

# Quant Terminal — Hermes Co-Pilot Skill

## กฎเหล็กก่อนเริ่มงาน (Central Control Plane: `home-repo`)
ทุกครั้งที่เริ่ม Session หรือได้รับคำสั่งเกี่ยวกับโปรเจกต์ของ Daniel ต้องอ่านไฟล์ควบคุมกลางก่อนเสมอ:
- `C:\\Users\\ASUS\\Desktop\\home-repo\\AGENTS.md`
- `C:\\Users\\ASUS\\Desktop\\home-repo\\core_memory\\short_term_state.md`
- `C:\\Users\\ASUS\\Desktop\\home-repo\\project_registry\\routing_map.md`
- `{WORK_DIR}\\PROJECT_ROADMAP.md`

เมื่อผู้ใช้ถามเกี่ยวกับโปรเจกต์ Quant (`mini-project-quant01`) หรือสั่งให้สแกนหุ้น/ดูพอร์ต/ส่งข้อความเข้า Dashboard ให้รันคำสั่งในโฟลเดอร์ `{WORK_DIR}` ดังนี้:

## 1. ดูสถานะพอร์ตและผลสแกนล่าสุด (Instant Status)
```powershell
python "{os.path.join(WORK_DIR, 'hermes_bridge.py')}" status
```

## 2. สั่งให้หน้าต่าง GUI สแกนหุ้นชุดใหม่ทันที (Remote GUI Trigger)
```powershell
python "{os.path.join(WORK_DIR, 'hermes_bridge.py')}" cmd --action scan --tickers "^NDX NVDA AAPL BTC-USD" --period 2y
```

## 3. ส่งคำแนะนำหรือโน้ตจาก Hermes ไปแสดงบนหน้าจอ GUI
```powershell
python "{os.path.join(WORK_DIR, 'hermes_bridge.py')}" cmd --action note --message "สรุปมุมมองตลาดจาก Hermes..."
```

## 4. รันสแกนและอัปเดตตารางผ่าน CLI โดยตรง
```powershell
cd "{WORK_DIR}"
python backtest_engine.py "^NDX" NVDA AAPL BTC-USD --period 2y --split 0.7 --scan --capital 100000
```
"""
    os.makedirs(LOCAL_MEM_DIR, exist_ok=True)
    local_skill_path = os.path.join(LOCAL_MEM_DIR, "HERMES_SKILL.md")
    with open(local_skill_path, "w", encoding="utf-8") as f:
        f.write(skill_md_content)

    try:
        os.makedirs(HERMES_SKILL_DIR, exist_ok=True)
        ext_skill_path = os.path.join(HERMES_SKILL_DIR, "SKILL.md")
        with open(ext_skill_path, "w", encoding="utf-8") as f:
            f.write(skill_md_content)
        return ext_skill_path
    except Exception:
        return local_skill_path


def sync_to_hermes_memory(
    scan_rows: list[dict],
    account_summary: dict | None = None,
    extra_note: str | None = None,
) -> dict:
    """
    ซิงก์ข้อมูลผลสแกน v4.0 และสถานะพอร์ตล่าสุดเข้าสู่ไฟล์ MEMORY.md ของ Hermes และ hermes_bus.json
    """
    bus = ensure_bus_file()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    scan_summary_lines = []
    for s in scan_rows:
        t = s.get("ticker", "")
        sc = float(s.get("quant_score", 0))
        gr = s.get("grade", "-")
        ml_p = float(s.get("ml_win_prob_pct", 50.0))
        act = s.get("action", "-")
        opt_w = float(s.get("opt_alloc_pct", s.get("alloc_pct", 0.0)))
        close_p = float(s.get("close", 0.0))
        stop_p = float(s.get("stop_price", 0.0))
        poc_p = float(s.get("poc_price", 0.0))
        scan_summary_lines.append(
            f"  * {t}: Score {sc:.0f}({gr}) | ML WinProb {ml_p:.0f}% | {act} | Close {close_p:,.2f} (Stop {stop_p:,.2f}, POC {poc_p:,.2f}) | แนะนำพอร์ต {opt_w:.1f}%"
        )

    acc_line = "พอร์ตจำลอง Local Paper: $100,000"
    if account_summary:
        acc_line = (
            f"Broker={account_summary.get('broker', 'local_paper')} ({account_summary.get('env_mode', 'paper')}) | "
            f"Equity=${account_summary.get('equity', 0):,.2f} | Cash=${account_summary.get('cash', 0):,.2f} | "
            f"Positions={len(account_summary.get('positions', []))}"
        )

    macro_vix = scan_rows[0].get("macro_vix_label", "Normal") if scan_rows else "Normal"

    roadmap_path = os.path.join(WORK_DIR, "PROJECT_ROADMAP.md")
    roadmap_text = ""
    if os.path.exists(roadmap_path):
        try:
            with open(roadmap_path, encoding="utf-8") as rf:
                roadmap_text = "\n\n---\n" + rf.read().strip() + "\n"
        except Exception:
            pass

    mem_block = (
        f"env: Ollama 0.40.16 running on 127.0.0.1:11434; Windows 11 PowerShell.\n"
        f"§\n"
        f"central_hub: C:\\Users\\ASUS\\Desktop\\home-repo (Control Plane — อ่าน AGENTS.md, core_memory/*.md, project_registry/routing_map.md ก่อนเริ่มงานทุกครั้ง)\n"
        f"project: mini-project-quant01 (AI Quant System — Lean Live Profitability Edition & Hermes 2-Way Sync)\n"
        f"- ตำแหน่ง: {WORK_DIR}\n"
        f"- กฎเหล็ก (STRICT GUARDRAILS): อ่าน C:\\Users\\ASUS\\Desktop\\home-repo\\AGENTS.md และ {WORK_DIR}\\PROJECT_ROADMAP.md ก่อนเสมอ\n"
        f"- อัปเดตล่าสุด: {now_str} | สภาวะตลาดมหภาค: {macro_vix}\n"
        f"- สถานะบัญชี ({acc_line})\n"
        f"- ผลสแกน Watchlist ล่าสุด:\n"
        + ("\n".join(scan_summary_lines) if scan_summary_lines else "  * (รอการสแกน)")
        + "\n"
        f"- วิธีเปิด GUI: python quant_gui.py หรือดับเบิลคลิก run_dashboard.bat\n"
        f"- วิธีที่ Hermes ใช้สั่งงาน GUI: python hermes_bridge.py cmd --action scan --tickers \"^NDX NVDA AAPL BTC-USD\"\n"
        + roadmap_text
    )

    # 1. บันทึกลง memories/MEMORY.md ในโปรเจกต์
    os.makedirs(LOCAL_MEM_DIR, exist_ok=True)
    with open(os.path.join(LOCAL_MEM_DIR, "MEMORY.md"), "w", encoding="utf-8") as f:
        f.write(mem_block)

    # 2. ซิงก์ไปยัง Hermes Global & Profile MEMORY.md และ SOUL.md
    synced_paths = [os.path.join(LOCAL_MEM_DIR, "MEMORY.md")]
    for target_path in (HERMES_GLOBAL_MEM, HERMES_PROFILE_MEM):
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(mem_block)
            synced_paths.append(target_path)
        except Exception:
            pass

    for mem_filename in ("SOUL.md", "USER.md"):
        local_m_path = os.path.join(LOCAL_MEM_DIR, mem_filename)
        if os.path.exists(local_m_path):
            try:
                with open(local_m_path, encoding="utf-8") as sf:
                    m_content = sf.read()
                for m_target in (
                    os.path.join(r"C:\Users\ASUS\AppData\Local\hermes\memories", mem_filename),
                    os.path.join(HERMES_PROFILE_DIR, "memories", mem_filename),
                ):
                    try:
                        os.makedirs(os.path.dirname(m_target), exist_ok=True)
                        with open(m_target, "w", encoding="utf-8") as stf:
                            stf.write(m_content)
                        synced_paths.append(m_target)
                    except Exception:
                        pass
            except Exception:
                pass

    # 3. อัปเดต hermes_bus.json
    bus["last_sync"] = now_str
    bus["latest_state"] = {
        "updated_at": now_str,
        "macro_vix": macro_vix,
        "account": acc_line,
        "watchlist": [
            {
                "ticker": s.get("ticker"),
                "quant_score": s.get("quant_score"),
                "grade": s.get("grade"),
                "ml_win_prob_pct": s.get("ml_win_prob_pct"),
                "action": s.get("action"),
                "close": s.get("close"),
                "stop_price": s.get("stop_price"),
                "opt_alloc_pct": s.get("opt_alloc_pct", s.get("alloc_pct")),
            }
            for s in scan_rows
        ],
    }
    if extra_note:
        bus.setdefault("messages", []).append({
            "sender": "Quant Terminal v4",
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": extra_note,
        })
        bus["messages"] = bus["messages"][-30:]

    with open(BUS_PATH, "w", encoding="utf-8") as f:
        json.dump(bus, f, indent=2, ensure_ascii=False)

    install_hermes_skill()
    return {"ok": True, "synced_at": now_str, "paths": synced_paths}


def send_command_to_bus(action: str, tickers: str = "", period: str = "2y", message: str = "") -> dict:
    """ส่งคำสั่งจาก Hermes Agent CLI เข้าไปในคิวของหน้าต่าง GUI"""
    bus = ensure_bus_file()
    cmd_obj = {
        "id": int(datetime.now().timestamp() * 1000),
        "action": action,
        "tickers": tickers,
        "period": period,
        "message": message,
        "created_at": datetime.now().strftime("%H:%M:%S"),
    }
    bus.setdefault("pending_commands", []).append(cmd_obj)
    if message:
        bus.setdefault("messages", []).append({
            "sender": "Hermes Agent",
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": message,
        })
    with open(BUS_PATH, "w", encoding="utf-8") as f:
        json.dump(bus, f, indent=2, ensure_ascii=False)
    return cmd_obj


def poll_pending_commands() -> tuple[list[dict], list[dict]]:
    """หน้าต่าง GUI เรียกฟังก์ชันนี้เพื่อดึงคำสั่งใหม่ที่ส่งมาจาก Hermes Agent"""
    if not os.path.exists(BUS_PATH):
        return [], []
    try:
        with open(BUS_PATH, encoding="utf-8") as f:
            bus = json.load(f)
        cmds = bus.get("pending_commands", [])
        msgs = bus.get("messages", [])
        if cmds:
            bus["pending_commands"] = []
            with open(BUS_PATH, "w", encoding="utf-8") as f:
                json.dump(bus, f, indent=2, ensure_ascii=False)
        return cmds, msgs
    except Exception:
        return [], []


def append_copilot_chat(sender: str, text: str):
    bus = ensure_bus_file()
    bus.setdefault("messages", []).append({
        "sender": sender,
        "time": datetime.now().strftime("%H:%M:%S"),
        "text": text,
    })
    bus["messages"] = bus["messages"][-30:]
    with open(BUS_PATH, "w", encoding="utf-8") as f:
        json.dump(bus, f, indent=2, ensure_ascii=False)


def main():
    p = argparse.ArgumentParser(description="Hermes Agent 2-Way Bridge for AI Quant Terminal v4.0")
    sub = p.add_subparsers(dest="subcmd")

    sub.add_parser("status", help="แสดงสถานะล่าสุดของพอร์ตและผลสแกนใน hermes_bus.json")
    sub.add_parser("install-skill", help="ติดตั้ง Skill ลงในโปรไฟล์ Hermes Agent")

    cmd_p = sub.add_parser("cmd", help="ส่งคำสั่งเข้าหน้าต่าง GUI สดๆ")
    cmd_p.add_argument("--action", required=True, choices=["scan", "note", "sync"], help="ประเภทคำสั่ง")
    cmd_p.add_argument("--tickers", default="", help="รายชื่อหุ้น เช่น 'NVDA AAPL TSLA'")
    cmd_p.add_argument("--period", default="2y", help="ช่วงเวลา เช่น 1y, 2y")
    cmd_p.add_argument("--message", default="", help="ข้อความหรือคำแนะนำจาก Hermes")

    args = p.parse_args()
    if args.subcmd == "install-skill":
        path = install_hermes_skill()
        print(f"ติดตั้ง Hermes Skill เรียบร้อยที่: {path}")
    elif args.subcmd == "cmd":
        obj = send_command_to_bus(args.action, args.tickers, args.period, args.message)
        print(f"ส่งคำสั่งไปยัง Quant Terminal v4.0 เรียบร้อย: {json.dumps(obj, ensure_ascii=False)}")
    else:
        bus = ensure_bus_file()
        print(json.dumps(bus.get("latest_state", {}), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
