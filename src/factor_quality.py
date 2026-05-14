"""
Piotroski F-Score (1999, "Value Investing: The Use of Historical Financial
Statement Information to Separate Winners from Losers from Losers")

9가지 이진 지표 합계 (0~9). 7점 이상 = High Quality.
Joseph Piotroski 원논문: 저PBR 종목 중 F-score≥7 종목은 시장 대비 연 +7.5% 알파.

본 구현은 yfinance의 quarterly_financials / quarterly_balance_sheet /
quarterly_cashflow 을 사용한다. 최근 2개 회계연도 비교 필요.

카테고리:
[Profitability] 1. ROA > 0
                2. CFO > 0
                3. ΔROA > 0
                4. Accruals: CFO > Net Income
[Leverage/Liq]  5. ΔLong-term debt / Assets < 0
                6. ΔCurrent Ratio > 0
                7. No new share issuance (shares outstanding unchanged or down)
[Operating]     8. ΔGross Margin > 0
                9. ΔAsset Turnover > 0
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import math

import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
@dataclass
class FScoreBreakdown:
    ticker: str
    f_score: Optional[int]            # 0~9 (None if uncomputable)
    n_valid: int                      # 9 중 계산된 개수
    profitability: int                # 0~4
    leverage_liquidity: int           # 0~3
    operating_efficiency: int         # 0~2
    components: Dict[str, Optional[int]]   # 각 9개 항목 (1/0/None)
    raw: Dict[str, Any]               # 디버깅용 raw 값

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    try:
        return a / b
    except (TypeError, ZeroDivisionError):
        return None


def _get(df: pd.DataFrame, candidates: List[str], col_idx: int = 0):
    """
    DataFrame에서 후보 키들 중 처음 발견되는 행의 값을 반환.
    yfinance는 회계연도별로 컬럼이 다르고, 행 이름이 자주 바뀜.
    """
    if df is None or df.empty:
        return None
    if col_idx >= len(df.columns):
        return None
    for cand in candidates:
        if cand in df.index:
            v = df.iloc[df.index.get_loc(cand), col_idx]
            if pd.isna(v):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
def compute_fscore(ticker: str) -> FScoreBreakdown:
    """
    단일 종목의 Piotroski F-score 계산.
    yfinance의 annual financials (최근 2년치) 사용.

    return: FScoreBreakdown (계산 불가 항목은 None으로 처리)
    """
    components: Dict[str, Optional[int]] = {
        "f1_roa_positive":        None,
        "f2_cfo_positive":        None,
        "f3_delta_roa_positive":  None,
        "f4_accruals_cfo_gt_ni":  None,
        "f5_leverage_decrease":   None,
        "f6_current_ratio_up":    None,
        "f7_no_dilution":         None,
        "f8_gross_margin_up":     None,
        "f9_asset_turnover_up":   None,
    }
    raw: Dict[str, Any] = {}

    try:
        t = yf.Ticker(ticker)
        # yfinance annual (3~4년치 보장)
        inc = t.financials                  # Income Statement (annual)
        bs  = t.balance_sheet               # Balance Sheet (annual)
        cf  = t.cashflow                    # Cash Flow Statement (annual)

        if inc is None or inc.empty or bs is None or bs.empty:
            return _empty_result(ticker, raw)

        # 컬럼 0 = 최신 회계연도, 1 = 직전 회계연도
        if len(inc.columns) < 2 or len(bs.columns) < 2:
            return _empty_result(ticker, raw)

        # === 최신 (t=0) / 직전 (t=1) 핵심 항목 ===
        # yfinance 행 이름이 버전마다 다름 → 후보 다수 시도
        ni_t  = _get(inc, ["Net Income", "Net Income From Continuing Operation Net Minority Interest", "Net Income Common Stockholders"], 0)
        ni_t1 = _get(inc, ["Net Income", "Net Income From Continuing Operation Net Minority Interest", "Net Income Common Stockholders"], 1)

        rev_t  = _get(inc, ["Total Revenue", "Operating Revenue"], 0)
        rev_t1 = _get(inc, ["Total Revenue", "Operating Revenue"], 1)

        cogs_t  = _get(inc, ["Cost Of Revenue", "Cost of Revenue", "Reconciled Cost Of Revenue"], 0)
        cogs_t1 = _get(inc, ["Cost Of Revenue", "Cost of Revenue", "Reconciled Cost Of Revenue"], 1)

        ta_t  = _get(bs, ["Total Assets"], 0)
        ta_t1 = _get(bs, ["Total Assets"], 1)

        ltd_t  = _get(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 0)
        ltd_t1 = _get(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 1)

        ca_t  = _get(bs, ["Current Assets", "Total Current Assets"], 0)
        ca_t1 = _get(bs, ["Current Assets", "Total Current Assets"], 1)

        cl_t  = _get(bs, ["Current Liabilities", "Total Current Liabilities"], 0)
        cl_t1 = _get(bs, ["Current Liabilities", "Total Current Liabilities"], 1)

        shares_t  = _get(bs, ["Share Issued", "Ordinary Shares Number", "Common Stock"], 0)
        shares_t1 = _get(bs, ["Share Issued", "Ordinary Shares Number", "Common Stock"], 1)

        if cf is not None and not cf.empty and len(cf.columns) >= 1:
            cfo_t = _get(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Cash Flowsfromusedin Operating Activities Direct"], 0)
        else:
            cfo_t = None

        raw.update({
            "ni_t": ni_t, "ni_t1": ni_t1,
            "rev_t": rev_t, "rev_t1": rev_t1,
            "ta_t": ta_t, "ta_t1": ta_t1,
            "cfo_t": cfo_t,
            "shares_t": shares_t, "shares_t1": shares_t1,
        })

        # === Component 1: ROA > 0 ===
        roa_t = _safe_div(ni_t, ta_t)
        if roa_t is not None:
            components["f1_roa_positive"] = int(roa_t > 0)

        # === Component 2: CFO > 0 ===
        if cfo_t is not None:
            components["f2_cfo_positive"] = int(cfo_t > 0)

        # === Component 3: ΔROA > 0 ===
        roa_t1 = _safe_div(ni_t1, ta_t1)
        if roa_t is not None and roa_t1 is not None:
            components["f3_delta_roa_positive"] = int(roa_t > roa_t1)

        # === Component 4: Accruals (CFO > Net Income) ===
        if cfo_t is not None and ni_t is not None:
            components["f4_accruals_cfo_gt_ni"] = int(cfo_t > ni_t)

        # === Component 5: ΔLeverage (Long-term debt / Assets) < 0 ===
        lev_t  = _safe_div(ltd_t, ta_t)
        lev_t1 = _safe_div(ltd_t1, ta_t1)
        if lev_t is not None and lev_t1 is not None:
            components["f5_leverage_decrease"] = int(lev_t < lev_t1)
        # 부채가 아예 없는 회사는 가산점
        elif (ltd_t is None or ltd_t == 0) and (ltd_t1 is None or ltd_t1 == 0):
            components["f5_leverage_decrease"] = 1

        # === Component 6: ΔCurrent Ratio > 0 ===
        cr_t  = _safe_div(ca_t, cl_t)
        cr_t1 = _safe_div(ca_t1, cl_t1)
        if cr_t is not None and cr_t1 is not None:
            components["f6_current_ratio_up"] = int(cr_t > cr_t1)

        # === Component 7: No share issuance (희석 없음) ===
        if shares_t is not None and shares_t1 is not None:
            # 1% 이내 변동은 자사주 매입/소각 흔들림으로 무시
            components["f7_no_dilution"] = int(shares_t <= shares_t1 * 1.01)

        # === Component 8: ΔGross Margin > 0 ===
        gm_t  = None
        gm_t1 = None
        if rev_t is not None and cogs_t is not None and rev_t > 0:
            gm_t = (rev_t - cogs_t) / rev_t
        if rev_t1 is not None and cogs_t1 is not None and rev_t1 > 0:
            gm_t1 = (rev_t1 - cogs_t1) / rev_t1
        if gm_t is not None and gm_t1 is not None:
            components["f8_gross_margin_up"] = int(gm_t > gm_t1)

        # === Component 9: ΔAsset Turnover > 0 ===
        at_t  = _safe_div(rev_t,  ta_t)
        at_t1 = _safe_div(rev_t1, ta_t1)
        if at_t is not None and at_t1 is not None:
            components["f9_asset_turnover_up"] = int(at_t > at_t1)

    except Exception as e:
        raw["error"] = str(e)[:300]

    # 합산
    valid_vals = [v for v in components.values() if v is not None]
    n_valid = len(valid_vals)
    f_score = sum(valid_vals) if n_valid > 0 else None

    # 카테고리별 점수 (디스플레이용)
    profit_keys   = ["f1_roa_positive", "f2_cfo_positive", "f3_delta_roa_positive", "f4_accruals_cfo_gt_ni"]
    leverage_keys = ["f5_leverage_decrease", "f6_current_ratio_up", "f7_no_dilution"]
    op_keys       = ["f8_gross_margin_up", "f9_asset_turnover_up"]

    profitability        = sum(v for k, v in components.items() if k in profit_keys   and v is not None)
    leverage_liquidity   = sum(v for k, v in components.items() if k in leverage_keys and v is not None)
    operating_efficiency = sum(v for k, v in components.items() if k in op_keys       and v is not None)

    return FScoreBreakdown(
        ticker=ticker,
        f_score=f_score,
        n_valid=n_valid,
        profitability=profitability,
        leverage_liquidity=leverage_liquidity,
        operating_efficiency=operating_efficiency,
        components=components,
        raw=raw,
    )


def _empty_result(ticker: str, raw: Dict[str, Any]) -> FScoreBreakdown:
    return FScoreBreakdown(
        ticker=ticker,
        f_score=None,
        n_valid=0,
        profitability=0,
        leverage_liquidity=0,
        operating_efficiency=0,
        components={k: None for k in [
            "f1_roa_positive","f2_cfo_positive","f3_delta_roa_positive","f4_accruals_cfo_gt_ni",
            "f5_leverage_decrease","f6_current_ratio_up","f7_no_dilution",
            "f8_gross_margin_up","f9_asset_turnover_up",
        ]},
        raw=raw,
    )


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 빠른 검증
    for tk in ["MSFT", "DIS", "INTC", "PLTR"]:
        result = compute_fscore(tk)
        print(f"{tk}: F={result.f_score}/9 (n_valid={result.n_valid})")
        print(f"    Profitability: {result.profitability}/4, Leverage: {result.leverage_liquidity}/3, Op: {result.operating_efficiency}/2")
        for k, v in result.components.items():
            mark = "✓" if v == 1 else ("✗" if v == 0 else "?")
            print(f"    {mark} {k}")
        print()
