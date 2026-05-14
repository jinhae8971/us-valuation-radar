"""
Momentum Factor — Jegadeesh & Titman (1993) 학계 표준

핵심 지표:
- 12-1M Momentum: 12개월 전 ~ 1개월 전 까지의 수익률
  (가장 최근 1개월 제외 = 단기 reversal 효과 제거)
- 3M Momentum: 단기 모멘텀 보조지표
- 52W High Proximity: 52주 최고가 대비 현재 위치 (0~1)
- Volatility: 252일 일일 수익률 표준편차 (annualized)

NaN-safe; 최소 250일 데이터 필요.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, List
import math

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class MomentumScore:
    ticker: str
    mom_12_1m: Optional[float]      # 12-1 month return (decimal, e.g. 0.25 = +25%)
    mom_3m: Optional[float]         # 3-month return
    mom_1m: Optional[float]         # 1-month return (reversal 신호)
    high_52w_proximity: Optional[float]  # 0~1 (1 = 52W high 도달)
    volatility_annual: Optional[float]   # annualized σ
    sharpe_proxy: Optional[float]   # 12-1M / vol (간이 Sharpe)
    n_days: int                     # 사용 가능 거래일 수

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
def compute_momentum(ticker: str, lookback_days: int = 270) -> MomentumScore:
    """
    yf.history()로 일별 종가 가져와 모멘텀 산출.
    """
    try:
        t = yf.Ticker(ticker)
        # 270일 = 약 13개월 (12-1M 계산 위해 약간 여유)
        hist = t.history(period=f"{lookback_days}d", auto_adjust=True)
        if hist is None or hist.empty:
            return _empty(ticker)
    except Exception as e:
        return _empty(ticker)

    closes = hist["Close"].dropna()
    n = len(closes)
    if n < 50:  # 최소 50일은 필요
        return _empty(ticker, n=n)

    price_now = float(closes.iloc[-1])

    # --- 12-1M Momentum (학계 표준) ---
    # 12개월 전 가격 / 1개월 전 가격 - 1
    mom_12_1m = None
    if n >= 252:
        p_12m_ago = float(closes.iloc[-252])
        p_1m_ago  = float(closes.iloc[-21]) if n >= 21 else None
        if p_12m_ago and p_1m_ago and p_12m_ago > 0:
            mom_12_1m = (p_1m_ago / p_12m_ago) - 1.0

    # --- 3M Momentum ---
    mom_3m = None
    if n >= 63:
        p_3m_ago = float(closes.iloc[-63])
        if p_3m_ago > 0:
            mom_3m = (price_now / p_3m_ago) - 1.0

    # --- 1M (단기 reversal) ---
    mom_1m = None
    if n >= 21:
        p_1m_ago = float(closes.iloc[-21])
        if p_1m_ago > 0:
            mom_1m = (price_now / p_1m_ago) - 1.0

    # --- 52W High Proximity ---
    high_52w_proximity = None
    window = min(n, 252)
    high_52w = float(closes.iloc[-window:].max())
    if high_52w > 0:
        high_52w_proximity = price_now / high_52w  # 0~1

    # --- Annualized Volatility (252일) ---
    volatility_annual = None
    if n >= 60:
        returns = closes.pct_change().dropna()
        win_ret = returns.iloc[-min(252, len(returns)):]
        if len(win_ret) >= 30:
            volatility_annual = float(win_ret.std() * math.sqrt(252))

    # --- Sharpe proxy ---
    sharpe_proxy = None
    if mom_12_1m is not None and volatility_annual is not None and volatility_annual > 0:
        sharpe_proxy = mom_12_1m / volatility_annual

    return MomentumScore(
        ticker=ticker,
        mom_12_1m=mom_12_1m,
        mom_3m=mom_3m,
        mom_1m=mom_1m,
        high_52w_proximity=high_52w_proximity,
        volatility_annual=volatility_annual,
        sharpe_proxy=sharpe_proxy,
        n_days=n,
    )


def _empty(ticker: str, n: int = 0) -> MomentumScore:
    return MomentumScore(
        ticker=ticker, mom_12_1m=None, mom_3m=None, mom_1m=None,
        high_52w_proximity=None, volatility_annual=None,
        sharpe_proxy=None, n_days=n,
    )


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for tk in ["NVDA", "DIS", "INTC", "PLTR", "DBX"]:
        r = compute_momentum(tk)
        print(f"{tk}:")
        print(f"  12-1M Mom:    {r.mom_12_1m:+.2%}" if r.mom_12_1m is not None else "  12-1M: N/A")
        print(f"  3M Mom:       {r.mom_3m:+.2%}"  if r.mom_3m   is not None else "  3M: N/A")
        print(f"  1M Mom:       {r.mom_1m:+.2%}"  if r.mom_1m   is not None else "  1M: N/A")
        print(f"  52W Prox:     {r.high_52w_proximity:.2%}" if r.high_52w_proximity else "")
        print(f"  Vol (ann):    {r.volatility_annual:.2%}"  if r.volatility_annual else "")
        print(f"  Sharpe proxy: {r.sharpe_proxy:.2f}"       if r.sharpe_proxy      else "")
        print()
