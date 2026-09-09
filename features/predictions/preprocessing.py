import pandas as pd
import numpy as np

# How many days ahead to forecast by default, overridable per run
DEFAULT_HORIZON_DAYS = 5

# Which features to use for training and prediction
FEATURES = [
    "p", "mv", "days_to_next",
    "mv_change_1d", "mv_trend_1d",
    "mv_change_3d", "mv_vol_3d",
    "mv_trend_7d", "market_divergence",
]

def horizons_for(horizon_days):
    """The forecast horizons in days: 1..horizon_days.

    Each one gets its own target column and its own output entry, predicted
    directly (not recursively) by a single multi-output model.
    """

    return tuple(range(1, horizon_days + 1))

def target_columns(horizons):
    """What columns to learn and predict on, one per horizon."""

    return [f"mv_target_h{k}_clipped" for k in horizons]

def preprocess_player_data(df, horizons):
    """Build features and one target per horizon.

    Returns (train_df, inference_df). train_df holds every row that has all
    targets, inference_df the single most recent row with a market value per player.
    """

    # 1. Sort and filter
    df = df.sort_values(["player_id", "date"])
    df = df[     # Keep rows where team_id matches t1 or t2 OR where both t1 and t2 are missing
        (df["team_id"] == df["t1"]) |
        (df["team_id"] == df["t2"]) |
        (df["t1"].isna() & df["t2"].isna())
    ]

    # Convert date columns to datetime
    df["date"] = pd.to_datetime(df["date"])
    df["md"] = pd.to_datetime(df["md"])

    # 2. Date and matchday calculations
    df["next_md"] = df.groupby("player_id")["md"].transform(
        lambda x: x.shift(-1).where(x.shift(-1) != x).bfill()
    )
    df["days_to_next"] = (df["next_md"] - df["date"]).dt.days

    # 3. Multi-horizon targets: the market value change k days ahead.
    # The market value history is a contiguous daily series per player, so a
    # positional shift of k rows equals a calendar shift of k days.
    for k in horizons:
        df[f"mv_target_h{k}"] = df.groupby("player_id")["mv"].shift(-k) - df["mv"]

    df = df[df["mv"] != 0.0]

    # 4. Feature engineering
    # Market value trend 1d
    df["mv_change_1d"] = df["mv"] - df.groupby("player_id")["mv"].shift(1)
    df["mv_trend_1d"] = df.groupby("player_id")["mv"].pct_change(fill_method=None)
    df["mv_trend_1d"] = df["mv_trend_1d"].replace([np.inf, -np.inf], 0).fillna(0)

    # Market value trend 3d
    df["mv_change_3d"] = df["mv"] - df.groupby("player_id")["mv"].shift(3)
    df["mv_vol_3d"] = df.groupby("player_id")["mv"].rolling(3).std().reset_index(0, drop=True)

    # Market value trend 7d
    df["mv_trend_7d"] = df.groupby("player_id")["mv"].pct_change(periods=7, fill_method=None)
    df["mv_trend_7d"] = df["mv_trend_7d"].replace([np.inf, -np.inf], 0).fillna(0)

    ## League-wide market context
    df["market_divergence"] = (df["mv"] / df.groupby("md")["mv"].transform("mean")).rolling(3).mean()

    # 5. Clip outliers per horizon, each with its own IQR bounds
    for k in horizons:
        target = df[f"mv_target_h{k}"]

        Q1 = target.quantile(0.25)
        Q3 = target.quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 2.5 * IQR
        upper_bound = Q3 + 2.5 * IQR

        df[f"mv_target_h{k}_clipped"] = target.clip(lower_bound, upper_bound)

    # 6. Fill missing values
    df = df.fillna({
        "market_divergence": 1,
        "mv_change_3d": 0,
        "mv_vol_3d": 0,
        "p": 0,
        "ppm": 0,
        "won": -1,
    })

    # 7. The inference row of a player is their most recent row that has a market
    # value. Rows without a market value only exist to carry an upcoming matchday.
    with_mv = df[df["mv"].notna()]
    inference_df = df.loc[with_mv.groupby("player_id")["date"].idxmax()].copy()

    # 8. Training rows need every target, so the last len(horizons) days of a
    # player's history (the inference row among them) are never training rows.
    targets = [f"mv_target_h{k}" for k in horizons] + target_columns(horizons)
    train_df = df.dropna(subset=FEATURES + targets)

    # 9. A player whose history is too short to have any past matchday has no
    # days_to_next, and the last row of a season has no upcoming matchday either.
    # Fall back to the typical gap rather than dropping the player from the API.
    fallback_days_to_next = train_df["days_to_next"].median()
    inference_df = inference_df.fillna({
        "days_to_next": fallback_days_to_next,
        "mv_change_1d": 0,
    })

    missing = inference_df[FEATURES].isna().sum()
    if missing.any():
        raise RuntimeError(f"Inference rows still contain missing features: {missing[missing > 0].to_dict()}")

    print(f"Training rows: {len(train_df)}, inference rows: {len(inference_df)}")

    return train_df, inference_df

def split_data(df, features, targets):
    """Split the data into training and testing sets based on date to avoid data leakage"""

    # Sort by date
    df = df.sort_values("date").reset_index(drop=True)

    split_idx = int(len(df) * 0.75)
    split_date = df["date"].iloc[split_idx]

    # Split by time, to avoid data leakage
    train = df[df["date"] < split_date]
    test = df[(df["date"] >= split_date)]

    X_train = train[features]
    y_train = train[targets]

    X_test = test[features]
    y_test = test[targets]

    print(f"Train/test split at {split_date.date()}: {len(X_train)} train, {len(X_test)} test rows")

    return X_train, X_test, y_train, y_test
