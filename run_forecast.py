from features.predictions.preprocessing import (
    preprocess_player_data,
    split_data,
    horizons_for,
    target_columns,
    DEFAULT_HORIZON_DAYS,
    FEATURES,
)
from features.predictions.data_handler import (
    fetch_player_data,
    save_player_data_to_db,
    load_player_data_from_db,
)
from features.predictions.modeling import train_model, evaluate_model, format_metrics_table
from features.predictions.predictions import predict_horizons
from features.output_writer import write_output
from kickbase_api.config import DEFAULT_BASE_URL
from kickbase_api.user import get_token
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import argparse
import os
import pandas as pd

# Load environment variables from .env file, before any of them are read
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

# A horizon beyond this is refused: every extra day holds one more day out of
# training, and the output series would stop resembling a forecast.
MAX_HORIZON_DAYS = 30

# Market values older than this are treated as a broken feed rather than as
# merely late, so a stuck API cannot keep republishing ancient forecasts.
DEFAULT_MAX_STALENESS_DAYS = 7

def env_flag(name):
    """Read a boolean switch from the environment."""

    return os.getenv(name, "").lower() in ("1", "true", "yes")

def parse_args(argv=None):
    """Command line options, each defaulting to its environment variable.

    KICK_TOKEN is intentionally not among these: a token on the command line
    would end up in process listings and shell history.
    """

    parser = argparse.ArgumentParser(
        description="Forecast Kickbase market values and write them as static JSON.",
    )

    parser.add_argument(
        "--horizon-days", type=int, default=int(os.getenv("HORIZON_DAYS", DEFAULT_HORIZON_DAYS)),
        help="how many days ahead to forecast (default: %(default)s)",
    )
    parser.add_argument(
        "--competition-id", type=int, default=int(os.getenv("COMPETITION_ID", "1")),
        help="1 = Bundesliga, 2 = 2. Bundesliga, 3 = La Liga (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir", default=os.getenv("OUTPUT_DIR", "output"),
        help="where to write the published files (default: %(default)s)",
    )
    parser.add_argument(
        "--api-base", default=os.getenv("KICK_API", DEFAULT_BASE_URL),
        help="base URL of the Kickbase API (default: %(default)s)",
    )

    development = parser.add_argument_group(
        "development options",
        "For local runs. CI always fetches fresh data and always enforces freshness.",
    )
    development.add_argument(
        "--cache-db", default=os.getenv("CACHE_DB", "player_data_total.db"),
        help="path of the local SQLite cache (default: %(default)s)",
    )
    development.add_argument(
        "--use-cache", action="store_true", default=env_flag("USE_CACHE"),
        help="read the cache instead of fetching, and skip the token",
    )
    development.add_argument(
        "--write-cache", action="store_true", default=env_flag("WRITE_CACHE"),
        help="save the fetched data to the cache",
    )
    development.add_argument(
        "--allow-stale", action="store_true", default=env_flag("ALLOW_STALE"),
        help="skip the staleness limit entirely, however old the data is",
    )
    parser.add_argument(
        "--max-staleness-days", type=int,
        default=int(os.getenv("MAX_STALENESS_DAYS", DEFAULT_MAX_STALENESS_DAYS)),
        help="refuse to publish data older than this many days (default: %(default)s)",
    )

    args = parser.parse_args(argv)

    if not 1 <= args.horizon_days <= MAX_HORIZON_DAYS:
        parser.error(f"--horizon-days must be between 1 and {MAX_HORIZON_DAYS}, got {args.horizon_days}")

    return args

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

def load_data(args):
    """Fetch the player data, or read it from the local cache during development."""

    if args.use_cache:
        print("Reading the local cache instead of fetching.")
        return load_player_data_from_db(args.cache_db)

    print("Fetching player data, this takes a few minutes...")
    df = fetch_player_data(get_token(), args.competition_id, LAST_MV_VALUES, LAST_PFM_VALUES)

    if args.write_cache:
        save_player_data_to_db(df, args.cache_db)

    return df

def main(argv=None):
    args = parse_args(argv)

    # The API layer reads this lazily, so a --api-base override belongs here
    os.environ["KICK_API"] = args.api_base

    horizons = horizons_for(args.horizon_days)
    print(f"Forecasting {args.horizon_days} day(s) ahead for competition {args.competition_id} via {args.api_base}")

    player_df = load_data(args)

    # Kickbase recalculates market values once a day, around 20:00 UTC. A run that
    # gets there first simply forecasts from the newest values that exist, so the
    # day-1 horizon then predicts today instead of tomorrow. Only data old enough
    # to mean the feed is broken stops the run.
    mv_date = get_market_value_date(player_df)
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    staleness = (today - mv_date).days

    set_step_output("fresh", "true" if staleness <= 0 else "false")
    set_step_output("mv_date", mv_date.isoformat())

    if staleness > args.max_staleness_days and not args.allow_stale:
        print(
            f"\nMarket values are {staleness} days old (newest stamp {mv_date}, today "
            f"{today} in Berlin), beyond the limit of {args.max_staleness_days}. That is "
            "too old to be a late recalculation, so this looks like a broken feed rather "
            "than a slow one. Refusing to publish; pass --allow-stale to override."
        )
        return 1

    if staleness > 0:
        print(
            f"\nKickbase has not recalculated yet: the newest market values are from "
            f"{mv_date}, {staleness} day(s) before today. Forecasting from those, so the "
            f"first forecast entry is for {mv_date + timedelta(days=1)}."
        )

    # Preprocess and split the data
    train_df, inference_df = preprocess_player_data(player_df, horizons)
    X_train, X_test, y_train, y_test = split_data(train_df, FEATURES, target_columns(horizons))

    # Train and evaluate one multi-output model for all horizons
    model = train_model(X_train, y_train)
    metrics = evaluate_model(model, X_test, y_test, horizons)

    print("\n=== Model evaluation per horizon (time-based test split) ===")
    print(format_metrics_table(metrics))

    # Predict and publish
    predictions_df = predict_horizons(inference_df, model, FEATURES, horizons)
    print(f"\nPredicted {len(horizons)} horizons for {len(predictions_df)} players.")

    write_output(args.output_dir, predictions_df, horizons, args.competition_id, mv_date, metrics)

    # What the deploy job keys on: output exists and is ready to publish
    set_step_output("published", "true")
    print("\nDone.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
