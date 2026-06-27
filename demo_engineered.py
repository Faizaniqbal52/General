# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "pandas", "scikit-learn"]
# ///

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import RobustScaler
from predictor import Predictor as BasePredictor


class Predictor(BasePredictor):
    """
    Engineered baseline — known to pass the overfitting test.

    Uses rolling cross-sectional ranks of feature.1 at three look-backs
    with Ridge regression and moderate regularisation.
    """

    def __init__(self):
        self._model = Ridge(alpha=50.0, fit_intercept=True)
        self._scaler = RobustScaler()

    def _cs_rank(self, arr):
        return pd.Series(arr).rank(pct=True).values - 0.5

    def _build_X(self, features_df):
        tickers = features_df.columns.get_level_values(1).unique().tolist()
        T = len(features_df)
        J = len(tickers)
        feat1 = features_df["feature.1"].values  # (T, J) close returns

        windows = [1, 5, 20]
        roll_means = {}
        for w in windows:
            rm = np.empty_like(feat1, dtype=float)
            for t in range(T):
                rm[t] = feat1[max(0, t - w + 1):t + 1].mean(axis=0)
            roll_means[w] = rm

        rows = []
        for t in range(T):
            cols = [self._cs_rank(roll_means[w][t]) for w in windows]
            rows.append(np.column_stack(cols))  # (J, 3)

        X = np.vstack(rows)  # (T*J, 3)
        return X, tickers

    def train(self, features_list, target_list):
        X_parts, y_parts = [], []
        for feat_df, tgt_df in zip(features_list, target_list):
            X, tickers = self._build_X(feat_df)
            y = tgt_df.reindex(columns=tickers).values.ravel("C")
            X_parts.append(X)
            y_parts.append(y)

        X_all = np.vstack(X_parts)
        y_all = np.concatenate(y_parts)
        mask = ~np.isnan(y_all)
        X_s = self._scaler.fit_transform(np.where(np.isnan(X_all), 0.0, X_all)[mask])
        self._model.fit(X_s, y_all[mask])

    def predict(self, features):
        X, tickers = self._build_X(features)
        X_s = self._scaler.transform(np.where(np.isnan(X), 0.0, X))
        T, J = len(features), len(tickers)
        preds = self._model.predict(X_s).reshape(T, J)
        pred_df = pd.DataFrame(preds, index=features.index, columns=tickers)
        pred_df = pred_df.sub(pred_df.mean(axis=1), axis=0)
        return pred_df
