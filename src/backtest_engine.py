"""
Backtest Engine — Quintile Portfolio Performance Analysis

목표: "현재 시그널이 실제 미래 수익률을 예측하는가?"를 검증

방법:
1. 매월 말 기준 종목별 시그널 (Value Z, F-score, Momentum, Final Score)
2. 시그널 강도순 5분위 portfolio (Q1=최저, Q5=최고)
3. 다음 달 forward return 측정
4. Q5-Q1 spread = 시그널 알파
5. Information Coefficient (IC) = corr(score_t, return_t+1)

⚠️ 중요한 한계 (반드시 인지):
- yfinance 무료티어로는 "현재 시점 펀더멘털"만 안정적 → look-ahead bias 가능
- 따라서 본 백테스트는 "Momentum + Price-based" 시그널 위주로 신뢰성 확보
- Fundamental(P/E 등)은 5년 전부터 동일했다고 가정한 단순화 모드
- → 결과는 "지표 방향성 검증"용이지 "실제 운용 알파" 추정용이 아님

학계 표준 메트릭:
- Annualized Return
- Annualized Volatility
- Sharpe Ratio (rf=0 가정)
- Max Drawdown
- Information Coefficient (IC) — Pearson corr
- Rank IC — Spearman corr (더 robust)
- IC IR (Information Ratio) = mean(IC) / std(IC)
- Hit Rate (예측 방향 일치율)
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from universe import get_all_tickers


# ---------------------------------------------------------------------------
KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"


# ---------------------------------------------------------------------------
def fetch_price_history(tickers: List[str], years: int = 3, verbose: bool = True) -> pd.DataFrame:
    """
    멀티 종목 일별 종가 매트릭스 (long form → pivot).
    yf.download 사용 (batch).
    """
    if verbose:
        print(f"  Downloading {len(tickers)} tickers, ~{years}y of daily data...")

    start = (datetime.now(KST) - timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    df = yf.download(
        tickers=" ".join(tickers),
        start=start,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )

    # 종가 매트릭스 추출
    if isinstance(df.columns, pd.MultiIndex):
        closes = pd.DataFrame({tk: df[tk]["Close"] for tk in tickers if tk in df.columns.levels[0]})
    else:
        closes = df["Close"].to_frame()

    closes = closes.dropna(how="all")
    if verbose:
        print(f"  Got: {closes.shape[0]} days x {closes.shape[1]} tickers")
    return closes


# ---------------------------------------------------------------------------
def compute_momentum_signal(closes: pd.DataFrame, lookback: int = 252, skip: int = 21) -> pd.DataFrame:
    """
    매일자 시점의 12-1M momentum 시그널 매트릭스.
    closes[t-252] → closes[t-21] 변화율.
    """
    return closes.shift(skip) / closes.shift(lookback) - 1.0


def compute_forward_return(closes: pd.DataFrame, horizon_days: int = 21) -> pd.DataFrame:
    """t시점 이후 horizon_days까지의 수익률."""
    return closes.shift(-horizon_days) / closes - 1.0


# ---------------------------------------------------------------------------
def run_quintile_backtest(
    signal: pd.DataFrame,
    forward_ret: pd.DataFrame,
    n_quintiles: int = 5,
    rebalance_freq: str = "M",
) -> Dict[str, Any]:
    """
    매월 말 시그널 기준 5분위 portfolio.
    각 분위 균등 가중. 다음 달 수익률.
    
    Returns: {
        "quintile_returns": DataFrame (월별, Q1~Q5),
        "long_short": Series (Q5 - Q1),
        "stats": Dict (annual return/vol/sharpe per quintile + LS),
        "ic_series": Series (월별 IC),
        "ic_stats": Dict (mean, std, IR, hit rate),
    }
    """
    # 월말 리밸런싱 시점
    if rebalance_freq == "M":
        # 매월 마지막 거래일
        rebal_dates = signal.resample("ME").last().index
    elif rebalance_freq == "Q":
        rebal_dates = signal.resample("QE").last().index
    else:
        rebal_dates = signal.resample("W").last().index

    rebal_dates = [d for d in rebal_dates if d in signal.index]

    quintile_returns = []
    ic_records = []

    for i, t in enumerate(rebal_dates):
        if i + 1 >= len(rebal_dates):
            break
        t_next = rebal_dates[i + 1]

        sig_t = signal.loc[t].dropna()
        if len(sig_t) < n_quintiles * 2:
            continue

        # 다음 리밸런싱까지의 누적 수익률
        if t not in signal.index or t_next not in signal.index:
            continue
        # closes 기반이라 forward_ret은 21-day 가정. 실제 holding 기간을 다시 계산
        # → 간단히 t→t_next 사이의 모든 거래일 평균 (각 분위는 동일가중)

        # forward_ret이 21-day horizon으로 미리 계산돼 있음. 그걸 t에 평가.
        if t not in forward_ret.index:
            continue
        fr_t = forward_ret.loc[t]
        # 시그널과 forward return 모두 가용한 종목만
        common = sig_t.index.intersection(fr_t.dropna().index)
        if len(common) < n_quintiles * 2:
            continue
        sig_filtered = sig_t.loc[common]
        fr_filtered = fr_t.loc[common]

        # === Quintile 분류 ===
        try:
            quintiles = pd.qcut(sig_filtered, n_quintiles, labels=False, duplicates="drop")
        except Exception:
            continue

        # 각 분위 평균 수익률
        row = {"date": t}
        for q in range(n_quintiles):
            mask = quintiles == q
            row[f"Q{q+1}"] = float(fr_filtered[mask].mean()) if mask.any() else np.nan
        quintile_returns.append(row)

        # === Information Coefficient (Spearman rank corr) ===
        try:
            ic, p = stats.spearmanr(sig_filtered.values, fr_filtered.values, nan_policy="omit")
            ic_records.append({"date": t, "ic": float(ic) if not np.isnan(ic) else None})
        except Exception:
            pass

    if not quintile_returns:
        return {"error": "no_valid_rebalance_dates"}

    qdf = pd.DataFrame(quintile_returns).set_index("date")
    qdf["LS"] = qdf[f"Q{n_quintiles}"] - qdf["Q1"]  # long-short

    # === 통계 ===
    # 월간 → 연환산
    periods_per_year = 12 if rebalance_freq == "M" else (4 if rebalance_freq == "Q" else 52)
    stats_out = {}
    for col in qdf.columns:
        s = qdf[col].dropna()
        if len(s) < 3:
            continue
        ann_ret = (1 + s.mean()) ** periods_per_year - 1
        ann_vol = s.std() * math.sqrt(periods_per_year)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else None
        # MDD
        cum = (1 + s).cumprod()
        dd = (cum / cum.cummax() - 1.0)
        mdd = float(dd.min())
        stats_out[col] = {
            "annual_return":  round(float(ann_ret), 4),
            "annual_vol":     round(float(ann_vol), 4),
            "sharpe":         round(float(sharpe), 3) if sharpe is not None else None,
            "max_drawdown":   round(mdd, 4),
            "hit_rate":       round(float((s > 0).mean()), 3),
            "n_periods":      int(len(s)),
        }

    # === IC 통계 ===
    ic_df = pd.DataFrame(ic_records).set_index("date") if ic_records else pd.DataFrame()
    if not ic_df.empty:
        ic_s = ic_df["ic"].dropna()
        ic_stats = {
            "mean_ic":  round(float(ic_s.mean()), 4),
            "std_ic":   round(float(ic_s.std()), 4),
            "ic_ir":    round(float(ic_s.mean() / ic_s.std() * math.sqrt(periods_per_year)), 3) if ic_s.std() > 0 else None,
            "hit_rate": round(float((ic_s > 0).mean()), 3),
            "n":        int(len(ic_s)),
        }
    else:
        ic_stats = {}

    return {
        "quintile_returns": qdf,
        "long_short": qdf["LS"],
        "stats": stats_out,
        "ic_series": ic_df,
        "ic_stats": ic_stats,
        "n_rebalances": len(qdf),
    }


# ---------------------------------------------------------------------------
def serialize_backtest(result: Dict[str, Any], signal_name: str) -> Dict[str, Any]:
    """JSON 직렬화"""
    if "error" in result:
        return {"signal": signal_name, "error": result["error"]}

    qdf = result["quintile_returns"]
    out = {
        "signal":         signal_name,
        "n_rebalances":   result["n_rebalances"],
        "stats":          result["stats"],
        "ic_stats":       result["ic_stats"],
        "first_date":     str(qdf.index[0].date()) if len(qdf) > 0 else None,
        "last_date":      str(qdf.index[-1].date()) if len(qdf) > 0 else None,
    }

    # 시계열 (월별 분위별 + LS + IC)
    timeseries = []
    for dt, row in qdf.iterrows():
        rec = {"date": str(dt.date())}
        for col in qdf.columns:
            v = row[col]
            rec[col] = round(float(v), 4) if pd.notna(v) else None
        timeseries.append(rec)
    out["timeseries"] = timeseries

    # IC 시계열
    if not result["ic_series"].empty:
        out["ic_timeseries"] = [
            {"date": str(d.date()), "ic": round(float(v["ic"]), 4) if pd.notna(v["ic"]) else None}
            for d, v in result["ic_series"].iterrows()
        ]

    return out


# ---------------------------------------------------------------------------
def main():
    print("=" * 72)
    print("Backtest Engine — Momentum Signal (12-1M)")
    print("=" * 72)

    tickers = get_all_tickers()
    print(f"\nUniverse: {len(tickers)} tickers")

    # === Price history ===
    closes = fetch_price_history(tickers, years=3, verbose=True)
    print(f"Price matrix: {closes.shape}")

    # === Momentum signal ===
    print("\n[Building Momentum Signal (12-1M)]")
    mom_signal = compute_momentum_signal(closes, lookback=252, skip=21)
    print(f"  Signal matrix: {mom_signal.shape}")

    # === Forward return (21-day = ~1 month) ===
    fwd_ret = compute_forward_return(closes, horizon_days=21)
    print(f"  Forward return: {fwd_ret.shape}")

    # === Backtest ===
    print("\n[Running Quintile Backtest — Monthly Rebalancing]")
    result = run_quintile_backtest(mom_signal, fwd_ret, n_quintiles=5, rebalance_freq="M")

    if "error" in result:
        print(f"❌ {result['error']}")
        return

    # === 출력 ===
    print("\n=== Quintile Performance (Annualized) ===")
    print(f"{'Quintile':<10}{'AnnRet':>10}{'AnnVol':>10}{'Sharpe':>10}{'MaxDD':>10}{'HitRate':>10}")
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5", "LS"]:
        if q not in result["stats"]:
            continue
        s = result["stats"][q]
        sharpe = f"{s['sharpe']:+.2f}" if s['sharpe'] is not None else "—"
        print(f"{q:<10}{s['annual_return']:>9.1%} {s['annual_vol']:>9.1%} {sharpe:>10}{s['max_drawdown']:>9.1%} {s['hit_rate']:>9.1%}")

    print(f"\n=== Information Coefficient ===")
    if result["ic_stats"]:
        ic = result["ic_stats"]
        print(f"  Mean IC:  {ic['mean_ic']:+.4f}")
        print(f"  Std IC:   {ic['std_ic']:.4f}")
        print(f"  IC IR:    {ic['ic_ir']:+.3f}  (annualized)")
        print(f"  Hit Rate: {ic['hit_rate']:.1%}")
        print(f"  Samples:  {ic['n']}")
    print(f"\n  N rebalances: {result['n_rebalances']}")

    # === 저장 ===
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bt_data = {
        "generated_at_kst": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "universe_size":    len(tickers),
        "lookback_years":   3,
        "backtests": {
            "momentum_12_1m": serialize_backtest(result, "momentum_12_1m"),
        },
    }
    out_path = DATA_DIR / "backtest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bt_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✓ Saved: {out_path}")

    return result


if __name__ == "__main__":
    main()
