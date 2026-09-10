import numpy as np
import pandas as pd

# The columns carried from the inference rows into the published output
PLAYER_COLUMNS = [
    "player_id", "first_name", "last_name",
    "team_id", "team_name", "position",
    "date", "mv",
]

def predict_horizons(inference_df, model, features, horizons):
    """Predict the 24 hour market value change for every horizon of every inference row.

    Returns one row per player with the latest market value, its stamp date and
    one predicted 24 hour change per horizon -- `pred_h3` is the move on day 3
    alone, not the total since today. Predictions are never fed back in as
    features -- every horizon is a direct prediction from the same feature row,
    so day 5 is predicted from today's data rather than from day 4's output.
    """

    # Reshaped because a single horizon makes this a single-output model, and
    # sklearn then returns a flat array rather than one column per horizon.
    predictions = np.asarray(
        model.predict(inference_df[features])
    ).reshape(len(inference_df), -1)

    results = inference_df[PLAYER_COLUMNS].copy()

    for index, horizon in enumerate(horizons):
        results[f"pred_h{horizon}"] = predictions[:, index]

    results["date"] = pd.to_datetime(results["date"])

    return results.sort_values("mv", ascending=False).reset_index(drop=True)
