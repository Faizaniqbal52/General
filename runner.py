#!/usr/bin/env python
"""
Walk-forward runner for local validation.

Usage
-----
    python runner.py submission.py              # quick test (last 2 periods)
    python runner.py submission.py --full       # full walk-forward
    python runner.py submission.py --gauge-fix  # full + city/novelty metrics

When data/periods/ exists (competition data) that is used; otherwise the
runner falls back to synthetic data so you can iterate offline.
"""

import argparse
import importlib.util
import sys
import os
import numpy as np
import pandas as pd

from predictor import Predictor as BasePredictor

# ---------------------------------------------------------------------------
# Synthetic data generation (used when competition data is absent)
# ---------------------------------------------------------------------------

def _make_synthetic_periods(n_periods=30, T=60, J=20, F=6, seed=0):
    rng = np.random.default_rng(seed)
    feat_names = [f"feature.{i + 1}" for i in range(F)]
    periods = []

    for p in range(n_periods):
        tickers = [f"ticker.{j + 1}" for j in range(J)]
        idx = pd.RangeIndex(T, name="timestamp")

        # Latent factor drives cross-sectional returns
        factor = rng.normal(0, 1, size=(T, J))
        factor -= factor.mean(axis=1, keepdims=True)

        feat_data = {}
        for k, fn in enumerate(feat_names):
            # Each feature correlates differently with the factor
            loading = rng.uniform(0.1, 0.9)
            noise = rng.normal(0, 1, size=(T, J))
            noise -= noise.mean(axis=1, keepdims=True)
            vals = loading * factor + (1 - loading) * noise
            feat_data[fn] = pd.DataFrame(vals, index=idx, columns=tickers)

        feat_df = pd.concat(feat_data, axis=1)
        feat_df.columns.names = ["feature", "ticker"]

        # Target: de-meaned forward returns  ≈ factor at t+1
        fwd = rng.normal(0, 0.5, size=(T, J)) + 0.3 * factor
        fwd -= fwd.mean(axis=1, keepdims=True)
        tgt_df = pd.DataFrame(fwd, index=idx, columns=tickers)

        periods.append((feat_df, tgt_df))

    return periods


# ---------------------------------------------------------------------------
# Loading submission
# ---------------------------------------------------------------------------

def _load_predictor(path):
    spec = importlib.util.spec_from_file_location("_submission", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "Predictor"):
        raise ValueError(f"{path}: no Predictor class found")
    cls = mod.Predictor
    if not issubclass(cls, BasePredictor):
        raise ValueError("Predictor must inherit from predictor.Predictor")
    return cls


# ---------------------------------------------------------------------------
# Walk-forward evaluation
# ---------------------------------------------------------------------------

def _validate_prediction(pred_df, tol=1e-6):
    row_sums = pred_df.sum(axis=1).abs()
    if (row_sums > tol).any():
        worst = row_sums.max()
        raise ValueError(
            f"NOT_DEMEANED — row sums are not zero (max |sum| = {worst:.2e}). "
            "Apply pred.sub(pred.mean(axis=1), axis=0) before returning."
        )


def _run_walkforward(predictor_cls, periods, start_from):
    all_returns = []

    for test_idx in range(start_from, len(periods)):
        train_feats = [p[0] for p in periods[:test_idx]]
        train_tgts = [p[1] for p in periods[:test_idx]]

        predictor = predictor_cls()
        predictor.train(train_feats, train_tgts)

        test_feat, test_tgt = periods[test_idx]
        pred_df = predictor.predict(test_feat)

        _validate_prediction(pred_df)

        # r(i) = <P(i-1), X(i)>  where target[t] = X(t+1)
        # So portfolio return at step t = dot(pred[t], target[t])
        common = pred_df.columns.intersection(test_tgt.columns)
        p = pred_df[common].values   # (T, J)
        x = test_tgt[common].values  # (T, J)
        period_rets = (p * x).sum(axis=1)
        all_returns.extend(period_rets.tolist())

    return np.array(all_returns)


def _sharpe(returns, annualise=True):
    if len(returns) == 0 or returns.std() == 0:
        return float("nan")
    sr = returns.mean() / returns.std()
    return sr * np.sqrt(252) if annualise else sr


# ---------------------------------------------------------------------------
# City / novelty metrics (stub — real computation requires competition data)
# ---------------------------------------------------------------------------

def _gauge_fix_report(predictor_cls, periods, start_from):
    print("\n=== Gauge-fix / Novelty ===")
    city_path = os.path.join("data", "signal_cities.parquet")
    if not os.path.exists(city_path):
        print("  data/signal_cities.parquet not found — skipping city distance.")
        print("  Run on the competition platform for real novelty metrics.")
        return

    cities = pd.read_parquet(city_path)
    print(f"  Loaded {len(cities)} existing signal cities.")

    # Collect predictions across test periods to estimate the signal's city
    all_preds = []
    for test_idx in range(start_from, len(periods)):
        train_feats = [p[0] for p in periods[:test_idx]]
        train_tgts = [p[1] for p in periods[:test_idx]]
        predictor = predictor_cls()
        predictor.train(train_feats, train_tgts)
        pred_df = predictor.predict(periods[test_idx][0])
        # Flatten each timestamp's prediction to a vector
        for t in range(len(pred_df)):
            v = pred_df.iloc[t].values.astype(float)
            norm = np.linalg.norm(v)
            if norm > 1e-10:
                all_preds.append(v / norm)

    if not all_preds:
        print("  No predictions collected.")
        return

    city = np.mean(all_preds, axis=0)
    city_norm = np.linalg.norm(city)
    if city_norm < 1e-10:
        print("  Signal city is near zero — very diverse predictions.")
        return
    city /= city_norm

    # Compare to existing cities
    city_matrix = cities.values.astype(float)
    cosines = city_matrix @ city
    angles_deg = np.degrees(np.arccos(np.clip(cosines, -1, 1)))
    min_angle = angles_deg.min()
    print(f"  Your signal city's min angular distance from existing cities: {min_angle:.1f}°")
    if min_angle >= 60:
        print("  ✓ >60° — good novelty (uncorrelated with existing signals likely).")
    else:
        print("  ✗ <60° — consider different features, look-backs, or model class.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Walk-forward signal runner")
    parser.add_argument("submission", help="Path to .py submission file")
    parser.add_argument("--full", action="store_true",
                        help="Full walk-forward (all test periods)")
    parser.add_argument("--gauge-fix", action="store_true",
                        help="Full walk-forward + city/novelty metrics")
    args = parser.parse_args()

    print(f"Loading submission: {args.submission}")
    predictor_cls = _load_predictor(args.submission)

    # Try to load competition data from data/periods/; fall back to synthetic
    data_dir = os.path.join("data", "periods")
    if os.path.isdir(data_dir):
        parquets = sorted(f for f in os.listdir(data_dir) if f.endswith(".parquet"))
        if parquets:
            print(f"Loading {len(parquets)} periods from {data_dir}/")
            periods = []
            for fname in parquets:
                path = os.path.join(data_dir, fname)
                df = pd.read_parquet(path)
                # Expected columns: MultiIndex (feature_name, ticker) + target tickers
                feat_cols = [c for c in df.columns if isinstance(c, tuple)]
                tgt_cols = [c for c in df.columns if not isinstance(c, tuple)]
                feat_df = df[feat_cols].copy()
                feat_df.columns = pd.MultiIndex.from_tuples(feat_cols)
                tgt_df = df[tgt_cols].copy() if tgt_cols else pd.DataFrame()
                periods.append((feat_df, tgt_df))
        else:
            periods = None
    else:
        periods = None

    if periods is None:
        n_periods = 30 if (args.full or args.gauge_fix) else 12
        print(f"No competition data found — generating {n_periods} synthetic periods.")
        periods = _make_synthetic_periods(n_periods=n_periods)

    n = len(periods)
    if args.full or args.gauge_fix:
        start_from = max(1, n // 5)          # use first 20 % as warm-up
    else:
        start_from = max(1, n - 2)           # quick: test only last 2 periods

    print(f"Walk-forward: {n} periods total, testing from period {start_from}  "
          f"({n - start_from} test periods)")

    returns = _run_walkforward(predictor_cls, periods, start_from)

    print("\n=== Results ===")
    print(f"  Portfolio return observations : {len(returns)}")
    print(f"  Mean return (per step)        : {returns.mean():.6f}")
    print(f"  Std  return (per step)        : {returns.std():.6f}")
    sharpe = _sharpe(returns)
    print(f"  Sharpe (annualised √252)      : {sharpe:.4f}")

    if args.gauge_fix:
        _gauge_fix_report(predictor_cls, periods, start_from)


if __name__ == "__main__":
    main()
