"""
Regime Awareness - 기존 Younggil 생태계와 연동

데이터 소스 (GitHub Pages JSON):
- risk-regime-monitor:        34-indicator Risk On/Off composite (5-tier)
- ai-semi-cycle-intelligence: AI/Semi cycle score (Deep Bottom ~ Distribution)
- crypto-cycle-intelligence:  CCS (참고용)

연동이 안 되거나 형식이 다르면 graceful fallback (Neutral regime 가정).

이 모듈의 핵심 출력:
- regime: "RiskOn" / "Neutral" / "RiskOff"
- factor_weights: {value, quality, momentum} 합=1.0
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import json
import requests


# 외부 시스템 GitHub Pages URL (실제 운영 중인 것들)
REGIME_SOURCES = {
    "risk_regime":  "https://jinhae8971.github.io/risk-regime-monitor/data/latest.json",
    "ai_semi":      "https://jinhae8971.github.io/ai-semi-cycle-intelligence/data/latest.json",
    "crypto":       "https://jinhae8971.github.io/crypto-cycle-intelligence/data/latest.json",
}


@dataclass
class RegimeSnapshot:
    risk_regime: Optional[str]      # "RiskOn" / "Neutral" / "RiskOff"
    risk_score: Optional[float]     # -100 ~ +100 또는 시스템별 스케일
    ai_semi_phase: Optional[str]
    ai_semi_score: Optional[float]
    crypto_phase: Optional[str]
    raw: Dict[str, Any]

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
def _safe_fetch(url: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_regime() -> RegimeSnapshot:
    """
    외부 시스템에서 regime 정보 fetch.
    실제 구조 (확인됨):
    - ai-semi-cycle: {ascs: {composite, phase}, ...}
    - crypto-cycle:  {ccs:  {composite, phase}, ...}
    - risk-regime:   현재 latest.json 경로 미운영 (404) → score 부재 시 ai_semi로 proxy
    """
    raw: Dict[str, Any] = {}

    # ---- 1) Risk Regime Monitor ----
    risk_regime, risk_score = None, None
    rr = _safe_fetch(REGIME_SOURCES["risk_regime"])
    if rr:
        raw["risk_regime_raw"] = rr
        for key in ("regime", "current_regime", "label", "state", "risk_state"):
            if key in rr:
                risk_regime = str(rr[key])
                break
        for key in ("score", "composite_score", "risk_score", "value"):
            if key in rr:
                try: risk_score = float(rr[key])
                except (TypeError, ValueError): pass
                break
        if risk_regime is None and risk_score is not None:
            risk_regime = _classify_by_score(risk_score)

    # ---- 2) AI/Semi Cycle (ascs) ----
    ai_semi_phase, ai_semi_score = None, None
    aisem = _safe_fetch(REGIME_SOURCES["ai_semi"])
    if aisem:
        raw["ai_semi_generated_at"] = aisem.get("generated_at")
        ascs = aisem.get("ascs") or {}
        ai_semi_phase = ascs.get("phase")
        comp = ascs.get("composite")
        if isinstance(comp, (int, float)):
            ai_semi_score = float(comp)

    # ---- 3) Crypto Cycle (ccs) ----
    crypto_phase = None
    cc = _safe_fetch(REGIME_SOURCES["crypto"])
    if cc:
        raw["crypto_generated_at"] = cc.get("generated_at")
        ccs = cc.get("ccs") or {}
        crypto_phase = ccs.get("phase")

    # ---- Risk regime proxy: ai_semi가 있으면 그것으로 보정 ----
    # ascs는 0~100 스케일 (Deep Bottom → Distribution)
    if risk_regime is None and ai_semi_score is not None:
        if ai_semi_score > 75:
            risk_regime = "Late Bull (RiskOn but caution)"
        elif ai_semi_score > 50:
            risk_regime = "RiskOn"
        elif ai_semi_score > 30:
            risk_regime = "Neutral"
        else:
            risk_regime = "RiskOff"
        risk_score = ai_semi_score

    return RegimeSnapshot(
        risk_regime=risk_regime,
        risk_score=risk_score,
        ai_semi_phase=ai_semi_phase,
        ai_semi_score=ai_semi_score,
        crypto_phase=crypto_phase,
        raw=raw,
    )


def _classify_by_score(score: float) -> str:
    """일반적인 risk score → regime 매핑 (-100~+100 스케일 가정)"""
    if score > 30:
        return "RiskOn"
    elif score < -30:
        return "RiskOff"
    else:
        return "Neutral"


# ---------------------------------------------------------------------------
def get_factor_weights(regime: RegimeSnapshot) -> Dict[str, float]:
    """
    Regime에 따른 multi-factor 가중치. 합 = 1.0
    
    학계 근거:
    - Asness, Frazzini, Pedersen (2014): Quality-Minus-Junk는 모든 cycle에서 알파
    - Daniel & Moskowitz (2016): Momentum crash는 Risk-Off 직후 reversal 구간
    - Late Bull → Quality + 신중한 Value, Momentum 약화
    - Deep Bottom → Value 매우 강력, Momentum 위험
    
    ai_semi_phase 우선, 없으면 risk_regime fallback.
    """
    # ai_semi phase가 가장 직접적인 신호 (AI/반도체 사이클 = 우리 유니버스 핵심)
    phase = (regime.ai_semi_phase or "").lower()

    if "deep bottom" in phase or "bottom" in phase:
        # 시장 바닥 — Value 최강, Momentum은 위험
        return {"value": 0.55, "quality": 0.35, "momentum": 0.10}
    elif "accumulation" in phase or "early" in phase:
        # 초기 회복 — Value + Quality
        return {"value": 0.45, "quality": 0.35, "momentum": 0.20}
    elif "mid" in phase or "expansion" in phase:
        # 중기 — 균형, Momentum 가산
        return {"value": 0.35, "quality": 0.25, "momentum": 0.40}
    elif "late bull" in phase or "late" in phase:
        # 후기 — Quality 중시, Value는 함정 위험, Momentum도 단기엔 유효
        return {"value": 0.25, "quality": 0.45, "momentum": 0.30}
    elif "distribution" in phase or "top" in phase or "euphoria" in phase:
        # 천장 부근 — Quality 절대 우선
        return {"value": 0.20, "quality": 0.60, "momentum": 0.20}

    # ai_semi가 없을 때 risk_regime fallback
    rg = (regime.risk_regime or "Neutral").lower()
    if "off" in rg:
        return {"value": 0.25, "quality": 0.55, "momentum": 0.20}
    elif "on" in rg:
        return {"value": 0.45, "quality": 0.25, "momentum": 0.30}
    else:
        return {"value": 0.40, "quality": 0.35, "momentum": 0.25}


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    snap = fetch_regime()
    print("=== Regime Snapshot ===")
    print(f"  Risk Regime:   {snap.risk_regime}  (score: {snap.risk_score})")
    print(f"  AI/Semi Phase: {snap.ai_semi_phase}  (score: {snap.ai_semi_score})")
    print(f"  Crypto Phase:  {snap.crypto_phase}")
    print()
    w = get_factor_weights(snap)
    print("=== Factor Weights ===")
    print(f"  Value:    {w['value']:.0%}")
    print(f"  Quality:  {w['quality']:.0%}")
    print(f"  Momentum: {w['momentum']:.0%}")
