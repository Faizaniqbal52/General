class Predictor:
    """Base class for walk-forward cross-sectional signal predictors."""

    def train(self, features, target):
        """
        Train on historical periods.

        Parameters
        ----------
        features : list of pd.DataFrame
            One DataFrame per period.  Each has MultiIndex columns
            (feature_name, ticker) and a timestamp index.
        target : list of pd.DataFrame
            One DataFrame per period.  Each has ticker columns and a
            timestamp index; values are cross-sectionally de-meaned
            one-step-ahead returns.
        """
        raise NotImplementedError("Subclasses must implement train()")

    def predict(self, features):
        """
        Generate a cross-sectional signal for one period.

        Parameters
        ----------
        features : pd.DataFrame
            MultiIndex columns (feature_name, ticker), timestamp index.

        Returns
        -------
        pd.DataFrame
            Same index as features, ticker columns.  Every row must sum
            to zero (cross-sectionally de-meaned).
        """
        raise NotImplementedError("Subclasses must implement predict()")
