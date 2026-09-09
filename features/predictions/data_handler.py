from kickbase_api.player import (
    get_all_players,
    get_player_info,
    get_player_market_value,
    get_player_performance,
)
from kickbase_api.config import MAX_WORKERS
import concurrent.futures
import pandas as pd
import sqlite3

# A run is aborted rather than published if more than this share of the players
# could not be fetched, so a partial API outage cannot silently shrink the API.
MAX_FAILURE_RATIO = 0.05

def fetch_player_data(token, competition_id, last_mv_values, last_pfm_values):
    """Fetch market value and performance history for every player of a competition."""

    players = get_all_players(token, competition_id)
    print(f"Found {len(players)} players in competition {competition_id}.")

    failures = []

    def process_player(player_id):
        player_info = get_player_info(token, competition_id, player_id)
        player_team_id = player_info["team_id"]
        player_df = pd.DataFrame([player_info])

        # Market Value
        mv_df = pd.DataFrame(get_player_market_value(token, competition_id, player_id, last_mv_values))
        if not mv_df.empty:
            mv_df["date"] = pd.to_datetime(mv_df["date"])
            mv_df = mv_df.sort_values("date")

        # Performance
        p_df = pd.DataFrame(get_player_performance(token, competition_id, player_id, last_pfm_values, player_team_id))
        if not p_df.empty:
            p_df["date"] = pd.to_datetime(p_df["date"])
            p_df = p_df.sort_values("date")
        else:
            p_df = pd.DataFrame({"date": pd.to_datetime([])})

        # Ensure date columns are in datetime64[us] format, see problem #6
        p_df["date"] = p_df["date"].astype("datetime64[us]")

        # Merge DataFrames
        merged_df = (
            pd.merge_asof(mv_df, p_df, on="date", direction="backward")
            if not mv_df.empty else pd.DataFrame()
        )

        # Get p_df values where p_df.date > max(mv_df.date) and append to merged_df.
        # These rows carry no market value; they exist so the last real market value
        # row can see the upcoming matchday and compute days_to_next.
        if not p_df.empty and not mv_df.empty:
            max_mv_date = mv_df["date"].max()
            additional_p_df = p_df[p_df["date"] > max_mv_date]
            merged_df = pd.concat([merged_df, additional_p_df], ignore_index=True)

        if not merged_df.empty:
            merged_df = player_df.merge(merged_df, how="cross")
            merged_df["competition_id"] = competition_id

        return merged_df

    def process_player_safely(player_id):
        try:
            return process_player(player_id)
        except Exception as exc:
            failures.append((player_id, type(exc).__name__))
            return pd.DataFrame()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        player_dfs = list(executor.map(process_player_safely, players))

    if failures:
        print(f"Warning: {len(failures)} of {len(players)} players could not be fetched.")
        for player_id, error in failures[:10]:
            print(f"  player {player_id}: {error}")

        if len(failures) > MAX_FAILURE_RATIO * len(players):
            raise RuntimeError(
                f"Aborting: {len(failures)} of {len(players)} player fetches failed, "
                "which is above the acceptable threshold."
            )

    final_df = pd.concat(
        [df.dropna(how="all", axis=1) for df in player_dfs if df is not None and not df.empty],
        ignore_index=True,
    )

    # Convert k column to string
    final_df["k"] = final_df["k"].apply(
        lambda x: ",".join(map(str, x)) if isinstance(x, list) else (None if x is None else str(x))
    )

    print(f"Fetched {len(final_df)} rows for {final_df['player_id'].nunique()} players.")

    return final_df

def save_player_data_to_db(df, db_path):
    """Write the fetched player data to a local SQLite cache."""

    with sqlite3.connect(db_path) as conn:
        df.to_sql("player_data_1d", conn, if_exists="replace", index=False)

    print(f"Player data cached in {db_path}.")

def load_player_data_from_db(db_path):
    """Load player data from the local SQLite cache into a dataframe."""

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql("SELECT * FROM player_data_1d", conn)

    print(f"Loaded {len(df)} cached rows for {df['player_id'].nunique()} players from {db_path}.")

    return df
