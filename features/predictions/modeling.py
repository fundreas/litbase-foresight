from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.ensemble import RandomForestRegressor
import numpy as np

def train_model(X_train, y_train):
    """Train a RandomForestRegressor model, parameters optimized via grid search.

    y_train carries one column per horizon; a random forest handles multi-output
    regression natively, so all five horizons come out of a single fitted model.
    """

    model = RandomForestRegressor(
        n_estimators=500,
        max_depth=20,
        min_samples_split=5,
        min_samples_leaf=2,
        max_features="sqrt",
        n_jobs=-1,
        random_state=42,  # so a rerun of the same day publishes the same numbers
    )

    model.fit(X_train, y_train)

    return model

def _direction_accuracy(true_column, pred_column, moved):
    """Share of moving rows whose direction was called correctly, as a percent.

    Only rows that actually moved count. Roughly a quarter of all player-days
    are a market value that did not budge at all -- cheap bench players the
    market ignores -- and np.sign of an exact zero can never equal the sign of
    a continuous prediction, so scoring those rows caps the metric well below
    100% for reasons that say nothing about the model.
    """

    if not moved.any():
        return None

    correct = np.sign(true_column[moved]) == np.sign(pred_column[moved])

    return round(float(correct.mean() * 100), 2)

def _error_metrics(true_column, pred_column, moved):
    """MAE, RMSE, R2 and directional accuracy of one prediction column."""

    return {
        "signAccuracy": _direction_accuracy(true_column, pred_column, moved),
        "mae": round(float(mean_absolute_error(true_column, pred_column)), 2),
        "rmse": round(float(np.sqrt(mean_squared_error(true_column, pred_column))), 2),
        "r2": round(float(r2_score(true_column, pred_column)), 4),
    }

def evaluate_model(model, X_test, y_test, horizons):
    """Evaluate the 24 hour change prediction of every horizon.

    Alongside the model's own error, each horizon carries a persistence
    baseline -- "the next 24 hour change equals the last one" -- because on a
    series this autocorrelated an impressive looking R2 means little without
    something trivial to compare it against.
    """

    # A single horizon makes this a single-output model, and sklearn then
    # returns a flat array rather than one column per horizon.
    y_pred = np.asarray(model.predict(X_test)).reshape(len(X_test), -1)
    y_true = y_test.to_numpy().reshape(len(y_test), -1)

    # The naive forecast: whatever the market value did over the last 24 hours,
    # it does again. Already a feature, so it needs no extra plumbing.
    baseline_pred = X_test["mv_change_1d"].to_numpy()

    metrics = {}

    for index, horizon in enumerate(horizons):
        true_column = y_true[:, index]
        pred_column = y_pred[:, index]
        moved = true_column != 0

        metrics[f"h{horizon}"] = {
            **_error_metrics(true_column, pred_column, moved),
            "testRows": int(len(true_column)),
            "movedRows": int(moved.sum()),
            "flatShare": round(float((~moved).mean() * 100), 2),
            "baseline": _error_metrics(true_column, baseline_pred, moved),
        }

    return metrics

def format_metrics_table(metrics):
    """Render the per-horizon metrics as a small fixed-width table for the log.

    Model and persistence baseline sit side by side, so a horizon where the
    model has stopped adding anything over the naive forecast is obvious.
    """

    def signs(value, width):
        """Directional accuracy is None when every test row was flat."""

        return f"{value:>{width}.2f}" if value is not None else f"{'n/a':>{width}}"

    header = (
        f"{'horizon':>8} {'flat %':>7} | {'signs %':>9} {'MAE':>12} {'R2':>8}"
        f" | {'base signs':>11} {'base MAE':>12} {'base R2':>8}"
    )
    lines = [header, "-" * len(header)]

    for horizon, values in metrics.items():
        baseline = values["baseline"]
        lines.append(
            f"{horizon:>8} {values['flatShare']:>7.2f} | "
            f"{signs(values['signAccuracy'], 9)} {values['mae']:>12,.0f} {values['r2']:>8.4f} | "
            f"{signs(baseline['signAccuracy'], 11)} {baseline['mae']:>12,.0f} {baseline['r2']:>8.4f}"
        )

    lines.append("")
    lines.append("signs %: direction called correctly, on rows that actually moved.")
    lines.append("flat %:  rows whose market value did not change at all, excluded from signs %.")
    lines.append("base:    persistence -- the next 24h change equals the last one.")

    return "\n".join(lines)
