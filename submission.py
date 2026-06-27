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
    Walk-forward cross-sectional signal predictor.

    Strategy
    --------
    For every (timestamp, asset) pair the model receives:
      * Cross-sectional rank and z-score of each raw feature (6 feats × 2)
      * Cross-sectional rank of rolling means at four look-backs: 3, 5, 10, 20
        (4 windows × 6 feats)
      * Short-term (1-step) and medium-term (5-step) rank-change signals
        (2 × 6 feats)
      * All pairwise products of current CS-ranks (C(6,2) = 15 interaction terms)

    Total: 12 + 24 + 12 + 15 = 63 features per observation.

    A Ridge regression (alpha = 10) trained on the stacked observation matrix
    across all prior periods maps these features to de-meaned forward returns.
    RobustScaler handles feature scale differences robustly.

    Design choices that resist overfitting
    ---------------------------------------
    * Linear model only — no capacity for fitting noise patterns.
    * Regularisation (alpha = 10) shrinks coefficients toward zero.
    * Cross-sectional rank inputs are bounded in [-0.5, 0.5], limiting
      leverage of any single observation.
    * No ticker-specific state: every feature is computed relative to
      the cross-section at the given timestamp, so changing ticker
      identities across periods do not matter.
    """

    def __init__(self):
        self._model = Ridge(alpha=10.0, fit_intercept=True)
        self._scaler = RobustScaler()

    # ------------------------------------------------------------------
    # Internal helpers (must stay inside the class per competition rules)
    # ------------------------------------------------------------------

    def _cs_rank(self, arr):
        """Cross-sectional rank, normalised to [-0.5, 0.5]."""
        return pd.Series(arr).rank(pct=True).values - 0.5

    def _cs_z(self, arr):
        """Cross-sectional z-score."""
        mu = np.nanmean(arr)
        sd = np.nanstd(arr) + 1e-8
        return (arr - mu) / sd

    def _build_X(self, features_df):
        """
        Convert a single-period feature DataFrame into an observation matrix.

        Parameters
        ----------
        features_df : pd.DataFrame
            MultiIndex columns (feature_name, ticker), timestamp index.

        Returns
        -------
        X : np.ndarray  shape (T * J, 63)
        tickers : list[str]
        """
        feat_names = features_df.columns.get_level_values(0).unique().tolist()
        tickers = features_df.columns.get_level_values(1).unique().tolist()
        T = len(features_df)
        J = len(tickers)
        F = len(feat_names)

        # feat_tensor: (T, J, F)  — raw feature values
        feat_tensor = np.stack(
            [features_df[fn].values for fn in feat_names], axis=2
        )

        # Precompute rolling means (causal: window ends at t inclusive)
        roll_windows = [3, 5, 10, 20]
        roll_mean = {}
        for w in roll_windows:
            rm = np.empty_like(feat_tensor, dtype=float)
            for t in range(T):
                rm[t] = feat_tensor[max(0, t - w + 1):t + 1].mean(axis=0)
            roll_mean[w] = rm

        rows = []
        for t in range(T):
            ft = feat_tensor[t]          # (J, F)

            # --- current CS rank and z-score ---
            curr_rank = np.column_stack(
                [self._cs_rank(ft[:, f]) for f in range(F)]
            )  # (J, F)
            curr_z = np.column_stack(
                [self._cs_z(ft[:, f]) for f in range(F)]
            )  # (J, F)

            # --- CS rank of rolling means ---
            roll_rank_cols = [
                self._cs_rank(roll_mean[w][t, :, f])
                for w in roll_windows
                for f in range(F)
            ]
            roll_rank = np.column_stack(roll_rank_cols)  # (J, 4*F)

            # --- short-term rank change (1-step) ---
            if t >= 1:
                prev_rank = np.column_stack(
                    [self._cs_rank(feat_tensor[t - 1, :, f]) for f in range(F)]
                )
                rank_diff_1 = curr_rank - prev_rank
            else:
                rank_diff_1 = np.zeros((J, F))

            # --- medium-term rank change (5-step) ---
            if t >= 5:
                lag5_rank = np.column_stack(
                    [self._cs_rank(feat_tensor[t - 5, :, f]) for f in range(F)]
                )
                rank_diff_5 = curr_rank - lag5_rank
            else:
                rank_diff_5 = np.zeros((J, F))

            # --- pairwise interaction terms: rank_i * rank_j ---
            interaction_cols = [
                curr_rank[:, i] * curr_rank[:, j]
                for i in range(F)
                for j in range(i + 1, F)
            ]
            interactions = np.column_stack(interaction_cols)  # (J, C(F,2))

            # Concatenate all features for this timestamp
            X_t = np.concatenate(
                [curr_rank, curr_z, roll_rank, rank_diff_1, rank_diff_5, interactions],
                axis=1,
            )  # (J, 63)
            rows.append(X_t)

        X = np.vstack(rows)  # (T*J, 63)
        return X, tickers

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def train(self, features_list, target_list):
        """
        Train on all historical periods.

        Parameters
        ----------
        features_list : list of pd.DataFrame
        target_list   : list of pd.DataFrame
        """
        X_parts, y_parts = [], []

        for feat_df, tgt_df in zip(features_list, target_list):
            X, tickers = self._build_X(feat_df)
            # Align target columns to the ticker order from features
            y = tgt_df.reindex(columns=tickers).values.ravel("C")
            X_parts.append(X)
            y_parts.append(y)

        X_all = np.vstack(X_parts)
        y_all = np.concatenate(y_parts)

        # Drop NaN targets; fill NaN features with 0 (robust to warm-up NaNs)
        valid = ~np.isnan(y_all)
        X_clean = np.where(np.isnan(X_all), 0.0, X_all)[valid]
        y_clean = y_all[valid]

        X_scaled = self._scaler.fit_transform(X_clean)
        self._model.fit(X_scaled, y_clean)

    def predict(self, features):
        """
        Predict cross-sectional signal for one period.

        Returns
        -------
        pd.DataFrame  shape (T, J), each row sums to 0.
        """
        X, tickers = self._build_X(features)
        X_clean = np.where(np.isnan(X), 0.0, X)
        X_scaled = self._scaler.transform(X_clean)

        T = len(features)
        J = len(tickers)

        preds = self._model.predict(X_scaled).reshape(T, J)
        pred_df = pd.DataFrame(preds, index=features.index, columns=tickers)

        # Cross-sectional de-meaning: mandatory — every row must sum to 0
        pred_df = pred_df.sub(pred_df.mean(axis=1), axis=0)
        return pred_df
