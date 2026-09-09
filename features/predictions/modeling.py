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

def evaluate_model(model, X_test, y_test, horizons):
    """Evaluate the model per horizon using sign accuracy, MAE, RMSE and R2."""

    y_pred = model.predict(X_test)
    y_true = y_test.to_numpy()

    metrics = {}

    for index, horizon in enumerate(horizons):
        true_column = y_true[:, index]
        pred_column = y_pred[:, index]

        signs_correct = np.sum(np.sign(true_column) == np.sign(pred_column))

        metrics[f"h{horizon}"] = {
            "signAccuracy": round(float(signs_correct / len(true_column) * 100), 2),
            "mae": round(float(mean_absolute_error(true_column, pred_column)), 2),
            "rmse": round(float(np.sqrt(mean_squared_error(true_column, pred_column))), 2),
            "r2": round(float(r2_score(true_column, pred_column)), 4),
            "testRows": int(len(true_column)),
        }

    return metrics

def format_metrics_table(metrics):
    """Render the per-horizon metrics as a small fixed-width table for the log."""

    header = f"{'horizon':>8} {'signs %':>9} {'MAE':>12} {'RMSE':>12} {'R2':>8}"
    lines = [header, "-" * len(header)]

    for horizon, values in metrics.items():
        lines.append(
            f"{horizon:>8} {values['signAccuracy']:>9.2f} "
            f"{values['mae']:>12,.0f} {values['rmse']:>12,.0f} {values['r2']:>8.4f}"
        )

    return "\n".join(lines)
