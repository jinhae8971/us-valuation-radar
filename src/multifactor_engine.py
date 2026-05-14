"""
Multi-Factor Integration + Sector-Neutral Long-Short Portfolio

구성:
1. fetch_fundamentals.py의 Value Z-score (composite_z)
2. factor_quality.py의 F-score (0~9)
3. factor_momentum.py의 12-1M momentum
4. regime_aware.py의 phase별 가중치

→ 종목별 final_score (정규화) 산출
→ Long Top Quintile / Short Bottom Quintile (sector-neutral)
→ Bayesian shrinkage 적용 (작은 섹터 안정화)

출력: docs/data/multifactor.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from universe import get_all_tickers, get_ticker_to_super_sector
from fetch_fundamentals import (
    fetch_ticker_data, assign_sectors, compute_sector_zscores,
    compute_quality_score, _safe_float,
)
from factor_quality import compute_fscore
from factor_momentum import compute_momentum
from regime_aware import fetch_regime, get_factor_weights


# ---------------------------------------------------------------------------
KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
HISTORY_DIR = DATA_DIR / "history"


# ---------------------------------------------------------------------------
def to_rank_pct(series: pd.Series) -> pd.Series:
    """
    Rank-based 0~1 변환 (학계의 RankIC 표준).
    Z-score보다 outlier에 강건.
    NaN은 NaN 유지.
    """
    return series.rank(pct=True, na_option="keep")


def bayesian_shrinkage(
    sector_values: pd.Series,
    universe_mean: float,
    n: int,
    tau: int = 10,
) -> pd.Series:
    """
    섹터별 점수를 전체 유니버스 평균 방향으로 shrink.
    n / (n + tau) 가중치.
    
    예: n=5, tau=10 → 33% 섹터 / 67% 전체 → 작은 섹터의 과적합 방지
    """
    alpha = n / (n + tau)
    return alpha * sector_values + (1 - alpha) * universe_mean


# ---------------------------------------------------------------------------
def fetch_all_factors(tickers: List[str], verbose: bool = True) -> pd.DataFrame:
    """
    유니버스 전체에 대해 Value + Quality + Momentum 데이터 수집.
    """
    rows = []
    n = len(tickers)
    for i, tk in enumerate(tickers, 1):
        if verbose:
            print(f"  [{i:3d}/{n}] {tk:8s}", end="", flush=True)

        # Value (fundamental)
        val = fetch_ticker_data(tk)

        # Momentum
        mom = compute_momentum(tk)

        # F-score (Quality) — 가장 느림 (분기재무 fetch 필요)
        try:
            fs = compute_fscore(tk)
        except Exception as e:
            fs = None

        row = dict(val)
        row.update({
            "mom_12_1m":   mom.mom_12_1m,
            "mom_3m":      mom.mom_3m,
            "mom_1m":      mom.mom_1m,
            "high_52w":    mom.high_52w_proximity,
            "volatility":  mom.volatility_annual,
            "sharpe_proxy": mom.sharpe_proxy,
        })
        if fs:
            row.update({
                "f_score":     fs.f_score,
                "f_n_valid":   fs.n_valid,
                "f_profit":    fs.profitability,
                "f_leverage":  fs.leverage_liquidity,
                "f_operating": fs.operating_efficiency,
            })
        rows.append(row)

        if verbose:
            zinfo = []
            if val.get("pe"): zinfo.append(f"PE={val['pe']:.1f}")
            if fs and fs.f_score is not None: zinfo.append(f"F={fs.f_score}")
            if mom.mom_12_1m is not None: zinfo.append(f"Mom={mom.mom_12_1m:+.0%}")
            print(f"  {' '.join(zinfo)}")

        # rate limit (yfinance 무료티어 보호)
        time.sleep(0.2)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
def compute_factor_scores(
    df: pd.DataFrame,
    factor_weights: Dict[str, float],
    sector_col: str = "super_sector",
    min_sector_size: int = 5,
    shrinkage_tau: int = 10,
) -> pd.DataFrame:
    """
    Multi-factor 종합 점수 산출 (학계 표준 방식).
    
    1. Value:    sector-neutral robust Z (-composite_z, 큰값이 좋음)
    2. Quality:  F-score를 [-1, 1] 스케일 (5점이 중립)
    3. Momentum: sector-neutral rank (큰값이 좋음)
    4. Shrinkage 적용 (작은 섹터 안정화)
    5. regime 기반 가중 결합
    
    출력 컬럼:
    - value_rank, quality_rank, momentum_rank: 0~1 정규화
    - final_score: -1 ~ +1 (sector-neutral)
    - long_short_signal: "LONG_TOP" / "LONG" / "NEUTRAL" / "SHORT" / "SHORT_BOTTOM"
    """
    out = df.copy()

    # 섹터별 종목 수
    sector_sizes = out.groupby(sector_col).size()
    valid_sectors = set(sector_sizes[sector_sizes >= min_sector_size].index)
    valid_mask = out[sector_col].isin(valid_sectors)

    # === [1] Value Rank (composite_z가 작을수록 좋음 → 부호 반전) ===
    # 섹터 내 rank, 0=고평가 1=저평가
    out["value_rank"] = np.nan
    if valid_mask.any():
        # composite_z 부호반전 후 rank
        neg_z = -out["composite_z"]
        out.loc[valid_mask, "value_rank"] = (
            out.loc[valid_mask].assign(_neg_z=neg_z)
              .groupby(sector_col)["_neg_z"]
              .transform(lambda x: x.rank(pct=True, na_option="keep"))
        )

    # === [2] Quality Rank (F-score 클수록 좋음) ===
    # F-score는 0~9 이산이므로 전 유니버스 rank로 부드럽게
    out["quality_rank"] = out["f_score"].rank(pct=True, na_option="keep")

    # === [3] Momentum Rank (12-1M 클수록 좋음) ===
    out["momentum_rank"] = np.nan
    if valid_mask.any():
        out.loc[valid_mask, "momentum_rank"] = (
            out.loc[valid_mask]
              .groupby(sector_col)["mom_12_1m"]
              .transform(lambda x: x.rank(pct=True, na_option="keep"))
        )

    # === [4] Bayesian Shrinkage ===
    # 작은 섹터(N<10)는 전체 유니버스 평균으로 shrink
    for col in ["value_rank", "quality_rank", "momentum_rank"]:
        universe_mean = out[col].mean(skipna=True)
        if pd.isna(universe_mean):
            continue
        for sec in valid_sectors:
            mask_sec = out[sector_col] == sec
            n_sec = int(sector_sizes.get(sec, 0))
            shrunk = bayesian_shrinkage(out.loc[mask_sec, col], universe_mean, n_sec, shrinkage_tau)
            out.loc[mask_sec, col] = shrunk

    # === [5] Final Score (regime weights) ===
    wv = factor_weights.get("value", 0.4)
    wq = factor_weights.get("quality", 0.35)
    wm = factor_weights.get("momentum", 0.25)
    # 모든 rank가 0~1이므로 가중평균도 0~1
    # 중심을 0으로 이동 → -0.5 ~ +0.5 (음수=숏, 양수=롱)
    raw_score = (
        wv * out["value_rank"] +
        wq * out["quality_rank"] +
        wm * out["momentum_rank"]
    )
    out["final_score"] = raw_score - 0.5  # center

    # 가용 팩터 수 (신뢰도)
    out["factor_n_valid"] = (
        out["value_rank"].notna().astype(int) +
        out["quality_rank"].notna().astype(int) +
        out["momentum_rank"].notna().astype(int)
    )

    # === [6] Long-Short Signal (sector-neutral quintile) ===
    out["long_short_signal"] = "NEUTRAL"
    for sec in valid_sectors:
        mask_sec = (out[sector_col] == sec) & out["final_score"].notna()
        if mask_sec.sum() < 5:
            continue
        scores = out.loc[mask_sec, "final_score"]
        q80 = scores.quantile(0.80)
        q60 = scores.quantile(0.60)
        q40 = scores.quantile(0.40)
        q20 = scores.quantile(0.20)

        for idx in out.loc[mask_sec].index:
            s = out.at[idx, "final_score"]
            if   s >= q80: out.at[idx, "long_short_signal"] = "LONG_TOP"
            elif s >= q60: out.at[idx, "long_short_signal"] = "LONG"
            elif s >= q40: out.at[idx, "long_short_signal"] = "NEUTRAL"
            elif s >= q20: out.at[idx, "long_short_signal"] = "SHORT"
            else:           out.at[idx, "long_short_signal"] = "SHORT_BOTTOM"

    return out


# ---------------------------------------------------------------------------
def build_portfolio(df: pd.DataFrame, target_n_long: int = 12, target_n_short: int = 12) -> Dict[str, Any]:
    """
    sector-neutral long-short 포트폴리오 구성.
    각 섹터에서 동일 비중씩 뽑아 sector exposure 최소화.
    """
    longs = df[df["long_short_signal"] == "LONG_TOP"].copy()
    shorts = df[df["long_short_signal"] == "SHORT_BOTTOM"].copy()

    # 점수순 정렬
    longs = longs.sort_values("final_score", ascending=False)
    shorts = shorts.sort_values("final_score", ascending=True)

    # 동일 가중 (단순)
    n_l = min(len(longs), target_n_long)
    n_s = min(len(shorts), target_n_short)
    longs = longs.head(n_l)
    shorts = shorts.head(n_s)

    long_weight = 1.0 / n_l if n_l > 0 else 0
    short_weight = -1.0 / n_s if n_s > 0 else 0

    positions = []
    for _, r in longs.iterrows():
        positions.append({
            "ticker": r["ticker"], "side": "LONG",
            "weight": round(long_weight, 4),
            "final_score": round(float(r["final_score"]), 4),
            "sector": r["super_sector"],
        })
    for _, r in shorts.iterrows():
        positions.append({
            "ticker": r["ticker"], "side": "SHORT",
            "weight": round(short_weight, 4),
            "final_score": round(float(r["final_score"]), 4),
            "sector": r["super_sector"],
        })

    return {
        "n_long": n_l,
        "n_short": n_s,
        "long_weight_per_position": round(long_weight, 4),
        "short_weight_per_position": round(short_weight, 4),
        "gross_exposure": 2.0,  # |1| + |1|
        "net_exposure": 0.0,     # 시장중립
        "positions": positions,
    }


# ---------------------------------------------------------------------------
def build_snapshot(df: pd.DataFrame, regime, factor_weights, portfolio) -> Dict[str, Any]:
    now_kst = datetime.now(KST)

    # NaN-safe JSON
    stocks = []
    for _, row in df.iterrows():
        stock = {}
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                stock[k] = None
            elif pd.isna(v):
                stock[k] = None
            elif isinstance(v, (np.integer, np.int64)):
                stock[k] = int(v)
            elif isinstance(v, (np.floating, np.float64)):
                stock[k] = float(v)
            else:
                stock[k] = v
        stocks.append(stock)

    return {
        "generated_at_kst": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
        "generated_at_iso": now_kst.isoformat(),
        "regime": {
            "ai_semi_phase":  regime.ai_semi_phase,
            "ai_semi_score":  regime.ai_semi_score,
            "crypto_phase":   regime.crypto_phase,
            "risk_regime":    regime.risk_regime,
            "risk_score":     regime.risk_score,
        },
        "factor_weights": factor_weights,
        "portfolio": portfolio,
        "stocks": stocks,
    }


# ---------------------------------------------------------------------------
def main():
    print("=" * 72)
    print("Multi-Factor Pipeline (Value + Quality + Momentum + Regime)")
    print("=" * 72)

    # 1) Regime 먼저 가져와서 가중치 결정
    regime = fetch_regime()
    weights = get_factor_weights(regime)
    print(f"\n[Regime]")
    print(f"  AI/Semi: {regime.ai_semi_phase} (score: {regime.ai_semi_score})")
    print(f"  Crypto:  {regime.crypto_phase}")
    print(f"  Risk:    {regime.risk_regime}")
    print(f"\n[Factor Weights]")
    print(f"  Value:    {weights['value']:.0%}")
    print(f"  Quality:  {weights['quality']:.0%}")
    print(f"  Momentum: {weights['momentum']:.0%}")

    # 2) 데이터 수집
    print(f"\n[Fetching {len(get_all_tickers())} tickers]")
    df = fetch_all_factors(get_all_tickers(), verbose=True)

    # 3) 섹터 + Value Z-score
    df = assign_sectors(df)
    df = compute_sector_zscores(df, sector_col="super_sector", min_sector_size=5)
    df = compute_quality_score(df)

    # 4) Multi-factor score
    df = compute_factor_scores(df, weights, sector_col="super_sector", min_sector_size=5)

    # 5) Long-Short 포트폴리오
    portfolio = build_portfolio(df, target_n_long=12, target_n_short=12)

    # 6) 저장
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    df_sorted = df.sort_values("final_score", ascending=False, na_position="last")
    snapshot = build_snapshot(df_sorted, regime, weights, portfolio)

    mf_path = DATA_DIR / "multifactor.json"
    with open(mf_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✓ Saved: {mf_path}")

    today = datetime.now(KST).strftime("%Y-%m-%d")
    hist_path = HISTORY_DIR / f"multifactor_{today}.json"
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)

    # 7) 콘솔 미리보기
    print("\n=== LONG TOP 12 (시장 대비 매수 우위) ===")
    longs = [p for p in portfolio["positions"] if p["side"] == "LONG"]
    for i, p in enumerate(longs, 1):
        print(f"  {i:2d}. {p['ticker']:6s} score={p['final_score']:+.3f}  {p['sector']}")

    print("\n=== SHORT BOTTOM 12 (시장 대비 매도 우위) ===")
    shorts = [p for p in portfolio["positions"] if p["side"] == "SHORT"]
    for i, p in enumerate(shorts, 1):
        print(f"  {i:2d}. {p['ticker']:6s} score={p['final_score']:+.3f}  {p['sector']}")

    return df_sorted, snapshot


if __name__ == "__main__":
    main()
