"""
US Valuation Radar - Fundamentals fetcher & Composite Z-score engine

핵심 로직:
1. yfinance로 종목별 펀더멘털 5개 지표 수집
   - P/E (trailingPE)
   - P/S (priceToSalesTrailing12Months)
   - P/B (priceToBook)
   - EV/EBITDA (enterpriseToEbitda)
   - EV/Sales (enterpriseToRevenue)

2. 섹터별 Robust Z-score 산출
   - z = (x - median) / (1.4826 * MAD)
   - 5개 지표 평균 → Composite Valuation Z-score
   - 음수일수록 "섹터 대비 저평가"

3. Quality Screen (가치 함정 방지)
   - profitMargin > 0 (적자 종목 제외 또는 별도 표기)
   - ROE 양수 (또는 N/A)

4. 결과를 docs/data/latest.json 으로 저장 (Git as DB)
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd
import numpy as np
import yfinance as yf

# universe.py 가 src/ 폴더에 있을 때 둘 다 지원
sys.path.insert(0, str(Path(__file__).parent))
from universe import (
    UNIVERSE, get_all_tickers, get_ticker_to_sector,
    get_ticker_to_super_sector, get_super_sector,
)


# ---------------------------------------------------------------------------
KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
HISTORY_DIR = DATA_DIR / "history"

METRIC_FIELDS = {
    "pe":         "trailingPE",
    "ps":         "priceToSalesTrailing12Months",
    "pb":         "priceToBook",
    "ev_ebitda":  "enterpriseToEbitda",
    "ev_sales":   "enterpriseToRevenue",
}

QUALITY_FIELDS = {
    "profit_margin":   "profitMargins",
    "roe":             "returnOnEquity",
    "revenue_growth":  "revenueGrowth",
    "gross_margin":    "grossMargins",
}

INFO_FIELDS = {
    "name":         "longName",
    "price":        "currentPrice",
    "market_cap":   "marketCap",
    "currency":     "currency",
    "industry":     "industry",
    "sector_gics":  "sector",
}

# ---------------------------------------------------------------------------
# 지표별 허용 범위 (이 범위 밖이면 무효 처리)
# - 음수 멀티플 = 적자 기업 → 의미 없음
# - 비현실적 고배수 = 데이터 오류 또는 비교 불가
METRIC_BOUNDS = {
    "pe":         (0.5,  500),    # P/E 0.5~500
    "ps":         (0.05, 100),    # P/S 0.05~100 (양자 종목 등 비현실 멀티플 제외)
    "pb":         (0.1,  100),    # P/B 0.1~100 (음수 자본 제외)
    "ev_ebitda":  (1.0,  200),    # EV/EBITDA 1~200 (적자 EBITDA 제외)
    "ev_sales":   (0.1,  100),    # EV/Sales 0.1~100
}


def _safe_float(v: Any) -> Optional[float]:
    """yfinance 결과를 안전하게 float 변환 (None / NaN / 이상치 처리)"""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _bounded_metric(v: Any, metric_key: str) -> Optional[float]:
    """
    펀더멘털 지표용 - 범위 밖이면 None.
    음수 멀티플(적자) / 비현실적 값을 제거하여 비교의 신뢰성 확보.
    """
    f = _safe_float(v)
    if f is None:
        return None
    lo, hi = METRIC_BOUNDS.get(metric_key, (None, None))
    if lo is not None and f < lo:
        return None
    if hi is not None and f > hi:
        return None
    return f


def fetch_ticker_data(ticker: str, retries: int = 2) -> Dict[str, Any]:
    """단일 종목의 펀더멘털 데이터 수집"""
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(ticker)
            info = t.info
            if not info or "symbol" not in info:
                if attempt < retries:
                    time.sleep(0.5)
                    continue
                return {"ticker": ticker, "error": "no_info"}

            row: Dict[str, Any] = {"ticker": ticker}
            for key, yf_field in INFO_FIELDS.items():
                row[key] = info.get(yf_field)

            for key, yf_field in METRIC_FIELDS.items():
                row[key] = _bounded_metric(info.get(yf_field), key)

            for key, yf_field in QUALITY_FIELDS.items():
                row[key] = _safe_float(info.get(yf_field))

            return row
        except Exception as e:
            if attempt < retries:
                time.sleep(1.0)
                continue
            return {"ticker": ticker, "error": str(e)[:200]}

    return {"ticker": ticker, "error": "exhausted_retries"}


def fetch_all(tickers: List[str], verbose: bool = True) -> pd.DataFrame:
    """전체 유니버스 데이터 수집"""
    rows = []
    n = len(tickers)
    for i, t in enumerate(tickers, 1):
        if verbose:
            print(f"  [{i:3d}/{n}] {t:8s}", end="", flush=True)
        row = fetch_ticker_data(t)
        rows.append(row)
        if verbose:
            err = row.get("error")
            if err:
                print(f"  ERR: {err}")
            else:
                pe = row.get("pe")
                ps = row.get("ps")
                print(f"  P/E={pe!s:>7} P/S={ps!s:>7}")
        time.sleep(0.15)  # yfinance rate limit 회피
    df = pd.DataFrame(rows)
    return df


# ---------------------------------------------------------------------------
def robust_zscore(series: pd.Series, winsorize_z: float = 5.0) -> pd.Series:
    """
    Robust Z-score using median + MAD (Median Absolute Deviation)
    이상치에 강건. winsorize_z 로 극단값 제한 (default ±5σ).
    MAD 가 0이면 NaN 반환.
    """
    s = series.dropna()
    if len(s) < 3:
        return pd.Series([np.nan] * len(series), index=series.index)

    med = s.median()
    mad = (s - med).abs().median()
    if mad == 0 or pd.isna(mad):
        return pd.Series([np.nan] * len(series), index=series.index)

    # 1.4826 ≈ 1/Phi^-1(0.75), MAD를 std 스케일로 변환
    z = (series - med) / (1.4826 * mad)
    # Winsorization: 극단치를 ±winsorize_z 로 clip
    z = z.clip(lower=-winsorize_z, upper=winsorize_z)
    return z


def compute_sector_zscores(
    df: pd.DataFrame,
    sector_col: str = "super_sector",
    min_sector_size: int = 5,
) -> pd.DataFrame:
    """
    섹터(super_sector)별로 5개 지표의 Robust Z-score 계산.
    낮을수록 저평가 → 그대로 사용 (음수가 저평가).
    섹터 종목 수가 min_sector_size 미만이면 Z-score 계산하지 않음.
    """
    out = df.copy()
    z_cols = []

    # 섹터별 종목 수 체크
    sector_sizes = out.groupby(sector_col).size()
    valid_sectors = set(sector_sizes[sector_sizes >= min_sector_size].index)

    # 유효 섹터만 마스킹
    valid_mask = out[sector_col].isin(valid_sectors)

    for metric in METRIC_FIELDS.keys():
        z_col = f"z_{metric}"
        z_cols.append(z_col)
        out[z_col] = np.nan
        # 유효 섹터에 대해서만 그룹별 robust_zscore 적용
        if valid_mask.any():
            z_values = (
                out.loc[valid_mask]
                .groupby(sector_col)[metric]
                .transform(robust_zscore)
            )
            out.loc[valid_mask, z_col] = z_values

    # Composite Z-score = 가용한 z 점수들의 평균
    # 최소 3개 이상 지표가 있어야 신뢰 (5개 중 3개)
    MIN_METRICS = 3
    raw_mean = out[z_cols].mean(axis=1, skipna=True)
    n_metrics = out[z_cols].notna().sum(axis=1)
    out["composite_z"] = raw_mean.where(n_metrics >= MIN_METRICS, np.nan)

    # 비교에 사용된 지표 개수 (신뢰도 지표)
    out["z_count"] = n_metrics

    # 비교 그룹 크기 표기
    out["sector_n"] = out[sector_col].map(sector_sizes).astype("Int64")
    return out


def compute_quality_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Quality 점수: 가치 함정(value trap) 회피용
    - profit_margin, roe, revenue_growth, gross_margin 각각 정규화 후 평균
    - 높을수록 우량
    """
    out = df.copy()
    quality_cols = []
    for metric in QUALITY_FIELDS.keys():
        z_col = f"q_{metric}"
        quality_cols.append(z_col)
        # 전체 유니버스 기준 (섹터 무관, quality는 절대 기준)
        s = out[metric]
        med = s.median()
        mad = (s - med).abs().median()
        if mad and not pd.isna(mad) and mad > 0:
            out[z_col] = (s - med) / (1.4826 * mad)
        else:
            out[z_col] = np.nan

    out["quality_z"] = out[quality_cols].mean(axis=1, skipna=True)
    return out


def assign_sectors(df: pd.DataFrame) -> pd.DataFrame:
    """유니버스 기반 섹터 + super_sector 할당"""
    mapping = get_ticker_to_sector()
    super_mapping = get_ticker_to_super_sector()
    df = df.copy()
    df["sector"] = df["ticker"].map(mapping)
    df["super_sector"] = df["ticker"].map(super_mapping)
    return df


# ---------------------------------------------------------------------------
def build_snapshot(df: pd.DataFrame) -> Dict[str, Any]:
    """
    최종 JSON 스냅샷 빌드.
    프런트엔드(대시보드) 가 직접 소비 가능한 형태.
    """
    now_kst = datetime.now(KST)

    # Super-sector 통계 (Z-score 비교 기준)
    super_sector_stats = []
    for sec in df["super_sector"].dropna().unique():
        sub = df[df["super_sector"] == sec]
        valid = sub.dropna(subset=["composite_z"])
        super_sector_stats.append({
            "super_sector": sec,
            "n_total": int(len(sub)),
            "n_valid": int(len(valid)),
            "median_pe": _safe_float(sub["pe"].median()),
            "median_ps": _safe_float(sub["ps"].median()),
            "median_pb": _safe_float(sub["pb"].median()),
            "median_ev_ebitda": _safe_float(sub["ev_ebitda"].median()),
            "median_ev_sales": _safe_float(sub["ev_sales"].median()),
            "tickers": sub["ticker"].tolist(),
        })

    # 세부 섹터 통계 (표시용)
    sector_stats = []
    for sec in df["sector"].dropna().unique():
        sub = df[df["sector"] == sec]
        sector_stats.append({
            "sector": sec,
            "n_total": int(len(sub)),
            "tickers": sub["ticker"].tolist(),
        })

    # 종목별 상세 (NaN -> None 변환)
    stocks = []
    for _, row in df.iterrows():
        stock = {}
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                stock[k] = None
            elif pd.isna(v):
                stock[k] = None
            else:
                stock[k] = v
        stocks.append(stock)

    return {
        "generated_at_kst": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
        "generated_at_iso": now_kst.isoformat(),
        "universe_size": len(df),
        "super_sectors": super_sector_stats,
        "sectors": sector_stats,
        "stocks": stocks,
    }


# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("US Valuation Radar — Fundamentals Fetch")
    print("=" * 70)

    tickers = get_all_tickers()
    print(f"Universe size: {len(tickers)}")

    df = fetch_all(tickers, verbose=True)
    print(f"\nFetched: {len(df)} rows")
    err_count = df["error"].notna().sum() if "error" in df.columns else 0
    print(f"Errors:  {err_count}")

    # 섹터 할당
    df = assign_sectors(df)

    # Z-score 산출 (super_sector 기준, 최소 5종목 보장)
    df = compute_sector_zscores(df, sector_col="super_sector", min_sector_size=5)
    df = compute_quality_score(df)

    # 정렬: composite_z 오름차순 (저평가 우선)
    df = df.sort_values("composite_z", ascending=True, na_position="last")

    # JSON 저장
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(df)

    latest_path = DATA_DIR / "latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✓ Saved: {latest_path}")

    # 히스토리 (날짜별 스냅샷)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    hist_path = HISTORY_DIR / f"{today}.json"
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
    print(f"✓ Saved: {hist_path}")

    # 콘솔 미리보기 — 저평가 TOP 10
    print("\n--- TOP 10 Undervalued (composite_z) ---")
    top = df.dropna(subset=["composite_z"]).head(10)
    cols = ["ticker", "name", "super_sector", "composite_z", "pe", "ps", "pb", "ev_ebitda", "z_count"]
    print(top[cols].to_string(index=False))

    return df


if __name__ == "__main__":
    main()
