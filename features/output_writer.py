from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import json

INDEX_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>litbase-foresight</title></head>
<body>
<h1>litbase-foresight</h1>
<p>Daily 5-day market value forecast for every Kickbase player, as static JSON.</p>
<p>One file per player at <code>data/&lt;player-id&gt;.json</code>; the player list and
model metrics are in <code>data/index.json</code>.</p>
</body>
</html>
"""

def _player_series(row, horizons):
    """Build the six-entry series of one player: the actual value, then the forecasts."""

    latest_date = row["date"].date()
    latest_mv = int(round(row["mv"]))

    series = [{"date": latest_date.isoformat(), "mv": latest_mv}]

    for horizon in horizons:
        forecast = latest_mv + row[f"pred_h{horizon}"]

        series.append({
            "date": (latest_date + timedelta(days=horizon)).isoformat(),
            "mv": max(0, int(round(forecast))),
        })

    return series

def write_output(output_dir, predictions_df, horizons, competition_id, mv_date, metrics):
    """Write one JSON file per player plus the index, and the files Pages needs."""

    output_dir = Path(output_dir)
    data_dir = output_dir / "data"

    # Start from a clean data directory so a player who left the competition
    # does not linger as a stale file in a local run.
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)

    players = []

    for row in predictions_df.to_dict("records"):
        player_id = str(row["player_id"])

        with open(data_dir / f"{player_id}.json", "w", encoding="utf-8") as handle:
            json.dump(_player_series(row, horizons), handle, separators=(",", ":"))

        players.append({
            "id": player_id,
            "firstName": row["first_name"],
            "lastName": row["last_name"],
            "team": row["team_name"],
            "teamId": str(row["team_id"]),
            "position": int(row["position"]),
        })

    index = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "competitionId": int(competition_id),
        "mvDate": mv_date.isoformat(),
        "horizonDays": len(horizons),
        "metrics": metrics,
        "players": players,
    }

    with open(data_dir / "index.json", "w", encoding="utf-8") as handle:
        json.dump(index, handle, separators=(",", ":"))

    # GitHub Pages would otherwise run the output through Jekyll
    (output_dir / ".nojekyll").write_text("")
    (output_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")

    print(f"Wrote {len(players)} player files plus index.json to {data_dir}.")

    return len(players)
