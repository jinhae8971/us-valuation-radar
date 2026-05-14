"""
US Valuation Radar - Telegram Notifier
섹터별 TOP 5 저평가 종목을 HTML 포맷으로 전송
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "docs" / "data" / "latest.json"

KST = timezone(timedelta(hours=9))

# GitHub Pages URL (배포 후 채워질 자리)
PAGES_URL_DEFAULT = "https://jinhae8971.github.io/us-valuation-radar/"


# ---------------------------------------------------------------------------
def load_config() -> Dict[str, str]:
    cfg = {
        "telegram_token":   os.environ.get("TELEGRAM_TOKEN",   ""),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "pages_url":        os.environ.get("PAGES_URL", PAGES_URL_DEFAULT),
    }
    config_path = ROOT / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if not cfg.get(k):
                    cfg[k] = v
    return cfg


def send_telegram(message: str, token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    r.raise_for_status()


# ---------------------------------------------------------------------------
def format_number(v, fmt: str = ".1f") -> str:
    if v is None:
        return "N/A"
    try:
        return format(float(v), fmt)
    except (TypeError, ValueError):
        return "N/A"


def build_message(snapshot: Dict[str, Any], top_n: int = 5) -> str:
    """섹터별 TOP N 저평가 종목 메시지 빌드"""
    cfg = load_config()
    pages_url = cfg.get("pages_url", PAGES_URL_DEFAULT)

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    lines: List[str] = []
    lines.append(f"📊 <b>US Valuation Radar</b>")
    lines.append(f"🕐 {now}")
    lines.append(f"📈 Universe: {snapshot['universe_size']} stocks")

    # === Multi-factor 데이터 (있으면 함께 표시) ===
    mf_path = ROOT / "docs" / "data" / "multifactor.json"
    if mf_path.exists():
        try:
            with open(mf_path, "r", encoding="utf-8") as f:
                mf = json.load(f)
            regime = mf.get("regime", {})
            weights = mf.get("factor_weights", {})
            portfolio = mf.get("portfolio", {})

            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            lines.append("<b>🌐 Regime + Factor Weights</b>")
            if regime.get("ai_semi_phase"):
                lines.append(f"  AI/Semi: <b>{regime['ai_semi_phase']}</b> ({regime.get('ai_semi_score', 0):.1f})")
            if regime.get("crypto_phase"):
                lines.append(f"  Crypto:  <b>{regime['crypto_phase']}</b>")
            if regime.get("risk_regime"):
                lines.append(f"  Risk:    <b>{regime['risk_regime']}</b>")
            if weights:
                lines.append(
                    f"  Weights: V <b>{weights.get('value',0):.0%}</b> · "
                    f"Q <b>{weights.get('quality',0):.0%}</b> · "
                    f"M <b>{weights.get('momentum',0):.0%}</b>"
                )

            # Long-Short 포지션 — 상위 5씩
            if portfolio.get("positions"):
                longs = [p for p in portfolio["positions"] if p["side"] == "LONG"][:5]
                shorts = [p for p in portfolio["positions"] if p["side"] == "SHORT"][:5]
                lines.append("")
                lines.append("━━━━━━━━━━━━━━━━━━")
                lines.append("<b>🎯 Multi-Factor Long-Short TOP 5</b>")
                lines.append("📈 <b>LONG</b>:")
                for i, p in enumerate(longs, 1):
                    lines.append(f"  {i}. <b>{p['ticker']}</b> ({p['final_score']:+.3f})  <i>{p['sector'][:30]}</i>")
                lines.append("📉 <b>SHORT</b>:")
                for i, p in enumerate(shorts, 1):
                    lines.append(f"  {i}. <b>{p['ticker']}</b> ({p['final_score']:+.3f})  <i>{p['sector'][:30]}</i>")
        except Exception as e:
            print(f"⚠️ multifactor 로드 실패: {e}")

    # === 기존 섹터별 TOP 5 (Value Z 기준) ===
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("<b>💎 섹터별 저평가 TOP 5 (Value)</b>")
    lines.append("<i>composite Z-score 기준</i>")

    stocks_with_z = [
        s for s in snapshot["stocks"]
        if s.get("composite_z") is not None and s.get("super_sector")
    ]
    sectors = {}
    for s in stocks_with_z:
        sec = s["super_sector"]
        sectors.setdefault(sec, []).append(s)

    for sec, stocks in sectors.items():
        stocks.sort(key=lambda x: x["composite_z"])

    for sec in sorted(sectors.keys()):
        stocks = sectors[sec][:top_n]
        if not stocks:
            continue
        lines.append("")
        lines.append(f"🏷️ <b>{sec}</b>")
        for i, s in enumerate(stocks, 1):
            tk = s.get("ticker", "?")
            z = s.get("composite_z")
            pe = s.get("pe")
            quality = s.get("quality_z")

            if quality is not None and quality > 0:
                q_marker = "✨"
            elif quality is not None and quality < -1:
                q_marker = "⚠️"
            else:
                q_marker = "  "

            lines.append(
                f"  {i}. {q_marker}<b>{tk}</b>  "
                f"Z=<b>{format_number(z, '+.2f')}</b>  "
                f"PE={format_number(pe, '.1f')}"
            )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("✨ 우량  ⚠️ 가치함정 주의")
    lines.append(f"🔗 <a href='{pages_url}'>전체 대시보드</a>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
def main():
    cfg = load_config()
    token = cfg.get("telegram_token", "")
    chat_id = cfg.get("telegram_chat_id", "")

    if not token or not chat_id:
        print("⚠️  TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 미설정 — 발송 생략")
        # 콘솔에 메시지만 출력
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        msg = build_message(snapshot)
        print("\n--- 발송 예정 메시지 ---")
        print(msg)
        return

    if not DATA_PATH.exists():
        print(f"❌ 데이터 파일 없음: {DATA_PATH}")
        sys.exit(1)

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    msg = build_message(snapshot)
    print(f"발송 메시지 길이: {len(msg)} chars")

    # Telegram 메시지 최대 4096자 — 분할 필요 시
    if len(msg) > 4000:
        # 섹터별로 분할
        parts = msg.split("━━━━━━━━━━━━━━━━━━")
        current = ""
        for p in parts:
            if len(current) + len(p) > 3500:
                send_telegram(current, token, chat_id)
                current = p
            else:
                current += "━━━━━━━━━━━━━━━━━━" + p
        if current:
            send_telegram(current, token, chat_id)
    else:
        send_telegram(msg, token, chat_id)

    print("✓ Telegram 발송 완료")


if __name__ == "__main__":
    main()
