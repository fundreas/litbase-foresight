import pandas as pd

# The columns carried from the inference rows into the published output
PLAYER_COLUMNS = [
    "player_id", "first_name", "last_name",
    "team_id", "team_name", "position",
    "date", "mv",
]

def predict_horizons(inference_df, model, features, horizons):
    """Predict the market value change for every horizon of every inference row.

    Returns one row per player with the latest market value, its stamp date and a
    predicted delta column per horizon. Predictions are never fed back in as
    features -- every horizon is a direct prediction from the same feature row.
    """

    predictions = model.predict(inference_df[features])

    results = inference_df[PLAYER_COLUMNS].copy()

    for index, horizon in enumerate(horizons):
        results[f"pred_h{horizon}"] = predictions[:, index]

    results["date"] = pd.to_datetime(results["date"])

    return results.sort_values("mv", ascending=False).reset_index(drop=True)
