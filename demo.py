# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "pandas", "scikit-learn"]
# ///

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from predictor import Predictor as BasePredictor


class Predictor(BasePredictor):
    """Minimal demo — uses only current cross-sectional rank of feature.1."""

    def __init__(self):
        self._coef = None

    def _rank(self, arr):
        return pd.Series(arr).rank(pct=True).values - 0.5

    def _build_X(self, features_df):
        tickers = features_df.columns.get_level_values(1).unique().tolist()
        T = len(features_df)
        J = len(tickers)
        # Use only feature.1 (close returns)
        feat1 = features_df["feature.1"].values  # (T, J)
        X = np.vstack([self._rank(feat1[t]) for t in range(T)])  # (T, J)
        return X, tickers

    def train(self, features_list, target_list):
        X_parts, y_parts = [], []
        for feat_df, tgt_df in zip(features_list, target_list):
            X, tickers = self._build_X(feat_df)
            y = tgt_df.reindex(columns=tickers).values
            X_parts.append(X.ravel())
            y_parts.append(y.ravel())
        X_all = np.concatenate(X_parts).reshape(-1, 1)
        y_all = np.concatenate(y_parts)
        mask = ~np.isnan(y_all)
        m = Ridge(alpha=1.0).fit(X_all[mask], y_all[mask])
        self._coef = m.coef_[0]
        self._intercept = m.intercept_

    def predict(self, features):
        X, tickers = self._build_X(features)
        preds = X * self._coef + self._intercept
        pred_df = pd.DataFrame(preds, index=features.index, columns=tickers)
        pred_df = pred_df.sub(pred_df.mean(axis=1), axis=0)
        return pred_df
