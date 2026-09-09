from features.predictions.preprocessing import (
    preprocess_player_data,
    split_data,
    FEATURES,
    HORIZONS,
    TARGET_COLUMNS,
)
from features.predictions.data_handler import (
    fetch_player_data,
    save_player_data_to_db,
    load_player_data_from_db,
)
from features.predictions.modeling import train_model, evaluate_model, format_metrics_table
from features.predictions.predictions import predict_horizons
from features.output_writer import write_output
from kickbase_api.user import login
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import os
import pandas as pd

# Load environment variables from .env file
load_dotenv()

# ----------------- Notes & TODOs -----------------

# TODO The merge_asof on the match date lets a match that finishes after the ~20:00 UTC
# market value recalculation contribute its points to the same day's feature row, which
# leaks the match result into the features for that day. A fix is to shift a performance
# row to the next day when kick-off + 2h is later than 20:00 UTC.
# TODO market_divergence applies rolling(3) across the whole frame instead of per player,
# so the first two rows of each player mix in the previous player's values.
# TODO Add features like starting 11 probability, injuries, ...

# ----------------- SYSTEM PARAMETERS -----------------
# Should be left unchanged unless you know what you're doing

LAST_MV_VALUES = 365    # in days, max 365
LAST_PFM_VALUES = 50    # in matchdays, max idk

# ----------------- CONFIGURATION -----------------
# Everything is configured through the environment, see the README

COMPETITION_ID = int(os.getenv("COMPETITION_ID", "1"))  # 1 = Bundesliga, 2 = 2. Bundesliga, 3 = La Liga
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

# Local development only. CI always fetches fresh data and never keeps a cache.
CACHE_DB = os.getenv("CACHE_DB", "player_data_total.db")
USE_CACHE = os.getenv("USE_CACHE", "").lower() in ("1", "true", "yes")
WRITE_CACHE = os.getenv("WRITE_CACHE", "").lower() in ("1", "true", "yes")
ALLOW_STALE = os.getenv("ALLOW_STALE", "").lower() in ("1", "true", "yes")

# ---------------------------------------------------

def set_step_output(name, value):
    """Expose a value to the GitHub Actions workflow, if we are running in one."""

    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")

def get_market_value_date(df):
    """The date of the current market values: the most common latest stamp per player."""

    with_mv = df[df["mv"].notna()].copy()
    with_mv["date"] = pd.to_datetime(with_mv["date"])

    latest_per_player = with_mv.groupby("player_id")["date"].max()
    mv_date = latest_per_player.mode().max().date()

    on_mv_date = int((latest_per_player.dt.date == mv_date).sum())
    print(
        f"Latest market value date: {mv_date} "
        f"({on_mv_date} of {len(latest_per_player)} players)"
    )

    return mv_date

def load_data(token):
    """Fetch the player data, or read it from the local cache during development."""

    if USE_CACHE:
        print("USE_CACHE is set, reading the local cache instead of fetching.")
        return load_player_data_from_db(CACHE_DB)

    print("Fetching player data, this takes a few minutes...")
    df = fetch_player_data(token, COMPETITION_ID, LAST_MV_VALUES, LAST_PFM_VALUES)

    if WRITE_CACHE:
        save_player_data_to_db(df, CACHE_DB)

    return df

def main():
    token = login(os.getenv("KICK_USER"), os.getenv("KICK_PASS")) if not USE_CACHE else None
    if token:
        print("Logged in to Kickbase.")

    player_df = load_data(token)

    # Freshness guard: Kickbase recalculates market values once a day, around 20:00
    # UTC. If the newest values are not from today, this run has nothing new to say,
    # so it stops here and the deploy job is skipped.
    mv_date = get_market_value_date(player_df)
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()

    if mv_date < today and not ALLOW_STALE:
        print(
            f"\nMarket values are stale: newest stamp is {mv_date}, today is {today} "
            "in Berlin. Kickbase has not recalculated yet -- exiting without writing "
            "output, the next scheduled run will try again."
        )
        set_step_output("fresh", "false")
        return 0

    if mv_date < today:
        print(f"\nWarning: market values are stale ({mv_date}), continuing because ALLOW_STALE is set.")

    # Preprocess and split the data
    train_df, inference_df = preprocess_player_data(player_df)
    X_train, X_test, y_train, y_test = split_data(train_df, FEATURES, TARGET_COLUMNS)

    # Train and evaluate one multi-output model for all five horizons
    model = train_model(X_train, y_train)
    metrics = evaluate_model(model, X_test, y_test, HORIZONS)

    print("\n=== Model evaluation per horizon (time-based test split) ===")
    print(format_metrics_table(metrics))

    # Predict and publish
    predictions_df = predict_horizons(inference_df, model, FEATURES, HORIZONS)
    print(f"\nPredicted {len(HORIZONS)} horizons for {len(predictions_df)} players.")

    write_output(OUTPUT_DIR, predictions_df, HORIZONS, COMPETITION_ID, mv_date, metrics)

    set_step_output("fresh", "true")
    print("\nDone.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
