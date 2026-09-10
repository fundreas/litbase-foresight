# litbase-foresight

A daily 5-day market value forecast for **every player** in a Kickbase competition,
published as a static, read-only JSON API on GitHub Pages.

Every evening, after Kickbase recalculates market values, a GitHub Action downloads
the full market value and performance history of the competition, trains a random
forest on it, and writes one JSON file per player. The consumer is my Kickbase
companion app *litbase*, which fetches these files straight from the browser.

There is no league, no squad, no transfer market and no email in here. If you want
those, use [LennardFe/Kickbase-Trading-Advisor](https://github.com/LennardFe/Kickbase-Trading-Advisor),
the project this is forked from.

## The API

```
https://fundreas.github.io/litbase-foresight/data/index.json
https://fundreas.github.io/litbase-foresight/data/<player-id>.json
```

`data/<player-id>.json` is a six-entry series. The **first entry is the actual latest
market value** with the date Kickbase stamped it; the following five are the forecasts
for the next five days. Each forecast entry carries both the level and `delta`, the
**24 hour change against the previous entry**, which is what the model actually predicts:

```json
[
  {"date": "2026-09-09", "mv": 12345678},
  {"date": "2026-09-10", "mv": 12400000, "delta": 54322},
  {"date": "2026-09-11", "mv": 12450000, "delta": 50000},
  {"date": "2026-09-12", "mv": 12480000, "delta": 30000},
  {"date": "2026-09-13", "mv": 12500000, "delta": 20000},
  {"date": "2026-09-14", "mv": 12510000, "delta": 10000}
]
```

Market values are integer euros and never negative. Dates are `YYYY-MM-DD`. Player and
team ids are strings.

The first entry has no `delta` — it is an observation, not a forecast. For every other
entry `mv` minus the previous entry's `mv` equals `delta` exactly: the deltas are derived
back out of the published levels, so rounding and the clamp at zero can never make the
two disagree.

`data/index.json` lists every player in the current output, along with the model's
accuracy on its own test split:

```json
{
  "generatedAt": "2026-09-09T20:14:03Z",
  "competitionId": 1,
  "mvDate": "2026-09-09",
  "horizonDays": 5,
  "metrics": {
    "h1": {
      "signAccuracy": 95.32, "mae": 21850.66, "rmse": 41487.15, "r2": 0.916,
      "testRows": 34262, "movedRows": 25870, "flatShare": 24.49,
      "baseline": {"signAccuracy": 94.53, "mae": 28921.99, "rmse": 102979.17, "r2": 0.4824}
    }
  },
  "players": [
    {"id": "7226", "firstName": "Harry", "lastName": "Kane", "team": "Bayern", "teamId": "2", "position": 4}
  ]
}
```

`position` is Kickbase's code: `1` goalkeeper, `2` defender, `3` midfielder, `4` forward.

`mvDate` is the market value date of the run as a whole. A single player's first entry
can be a day or two older than that — Kickbase does not always have a fresh value for
everyone — so read the date of the first entry, not `mvDate`, when a player's own
series matters.

## How the forecast works

Features per player and day: matchday points, current market value, days to the next
matchday, 1-day change and trend, 3-day change and volatility, 7-day trend, and the
player's market value relative to the league average.

The objective is the **24 hour change**, not the market value itself. Target k is
`mv(t+k) - mv(t+k-1)`, the move on day k alone, each clipped to its own IQR bounds. A
single `RandomForestRegressor` is fitted with all five as a multi-output target, so **no
prediction is ever fed back in as a feature** — day 5 is predicted from today's data, not
from the day-4 prediction. The published levels are the running sum of the five predicted
changes on top of the latest actual value.

A row is only a training row if all of its targets exist, which means the last five days
of each player's history are held out. The most recent day with a market value is the row
the forecast is made from.

Five days is the default, not a hard-coded assumption — see `--horizon-days` below.

### Reading the metrics

Roughly a quarter of all player-days are a market value that **did not move at all** —
cheap bench players the market ignores, median value 500,000 against 8.0M for rows that
do move, with 72 players frozen on more than 90% of days. Those rows make a naive sign
accuracy meaningless in both directions: `sign(0)` never equals the sign of a continuous
prediction, so scoring them caps the metric at ~75% however good the model is, while a
"predict no change" rule collects them all for free.

So `signAccuracy` is measured **only on rows that actually moved**, and `flatShare` and
`movedRows` report how many were set aside. `baseline` is persistence — "the next 24 hour
change equals the last one" — because on a series this autocorrelated a high R² means
little without something trivial to compare against.

What that comparison shows is worth knowing before you build on these numbers:

```
 horizon  flat % |   signs %          MAE       R2 |  base signs     base MAE  base R2
      h1   24.49 |     95.32       21,851   0.9160 |       94.53       28,922   0.4824
      h2   24.51 |     90.90       36,127   0.7945 |       89.96       46,725   0.2798
      h3   24.54 |     86.89       48,913   0.6600 |       85.74       61,251   0.0713
      h4   24.57 |     82.71       60,251   0.5306 |       81.56       73,828  -0.1449
      h5   24.61 |     79.13       69,243   0.4212 |       77.65       84,489  -0.3474
```

**The model's value is in the magnitude, not the direction.** Direction is nearly free:
persistence alone calls tomorrow correctly 94.53% of the time and the model adds 0.79
points on top of it, because Kickbase market values move in streaks. On *how far* a value
moves the model wins properly — a third off the h1 error, and it still holds R² 0.42 at
day 5 where persistence has gone negative.

One consequence of a regression objective: nothing can output exactly zero, so all 80
players frozen for their last 30 days are still forecast to move, by a median of 11,662
over five days. Small against a 500,000 value, but it is noise rather than signal, and a
consumer that cares should treat a flat history as flat.

## Schedule and the freshness rule

Kickbase recalculates market values once a day, around 20:00 UTC. The workflow runs at
**22:10 and 22:40 Berlin time**, and the second run is the fallback for when the first
one still sees yesterday's numbers.

GitHub cron is UTC only, so each of those two times needs two entries (21:xx UTC in
winter, 20:xx UTC in summer) and the first step of the job discards whichever pair does
not currently match 22:xx Berlin. Note that GitHub often starts scheduled runs 10–30
minutes late; a run delayed past 23:00 Berlin is skipped by that check and the day is
covered by the other cron entry.

The run takes the **most common latest market value stamp across all players** and
publishes that as `mvDate`. A run that beats the recalculation is not wasted: it
forecasts from the newest values that exist, so with yesterday's data the day-1 entry
predicts *today* and the series still covers five unknown days. `fresh` in the run
summary says whether the data was today's; it does not gate the deploy. Both scheduled
runs are idempotent — a deploy simply overwrites the last one, so the 22:40 run upgrades
the morning's yesterday-based forecast as soon as today's values land.

Because the first entry of every player's series carries **its own date**, a consumer can
always tell which day a forecast starts from — read that, or `mvDate`, rather than
assuming the first entry is today.

The one case that does stop a run is data old enough to mean the feed is broken rather
than late: past `--max-staleness-days` (default 7) the run refuses to publish and exits
non-zero, so a stuck API cannot keep republishing ancient forecasts under a fresh
`generatedAt`. `--allow-stale` overrides that, which is what makes an old local cache
usable for development.

Pages is published from an artifact, so successful runs produce no commits. Because
GitHub pauses scheduled workflows on public repos after 60 days without a commit, the
job ends with a keepalive step that pushes an empty commit once the last one is 45 days
old. It is a handful of inline shell rather than a third-party action, which is one less
dependency that can go unmaintained or be blocked.

## Running it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

printf 'KICK_USER=you@example.com\nKICK_PASS=your-password\n' > .env
python run_forecast.py
```

On a Debian or Ubuntu box without the `python3-venv` package, use
[uv](https://github.com/astral-sh/uv) instead of the first two lines:

```bash
uv venv .venv && uv pip install -p .venv -r requirements.txt
.venv/bin/python run_forecast.py
```

The output lands in `output/`. Fetching the whole competition takes a few minutes.

### Authentication

Normally the run logs in with `KICK_USER` and `KICK_PASS` (email and password is all the
endpoint supports) and mints a fresh token for itself.

`KICK_TOKEN` short-circuits that: set it to a Kickbase JWT you already have — the
`Authorization: Bearer` header from a logged-in session in your browser's network tab —
and no login happens. Handy for a one-off local run, but **a Kickbase token lives only
seven days**, which is why the scheduled workflow uses credentials instead. A token that
never renews would take the daily schedule down with it every week.

The two combine sensibly. `KICK_TOKEN` wins while it is valid; once its `exp` claim has
passed the run says so and logs in instead, so a stale token left in a `.env` cannot
quietly shadow working credentials. The `exp` claim is read without verifying the
signature — it only decides whether the token is worth sending, and the API remains the
authority on whether it is actually valid.

Both are read from the environment only, never from a command line argument, so neither
can leak into process listings or shell history.

### Options

Every option defaults to its environment variable, so CI can use `env:` and you can use
flags. Run `python run_forecast.py --help` for the full list.

| Variable | Flag | Default | Meaning |
| --- | --- | --- | --- |
| `KICK_USER` | – | – | Kickbase email. Required unless `KICK_TOKEN` is set. |
| `KICK_PASS` | – | – | Kickbase password. Required unless `KICK_TOKEN` is set. |
| `KICK_TOKEN` | – | – | Existing JWT; skips the login while it is valid. |
| `KICK_API` | `--api-base` | `https://api.kickbase.com/v4` | Base URL of the Kickbase API. |
| `HORIZON_DAYS` | `--horizon-days` | `5` | How many days ahead to forecast (1–30). |
| `COMPETITION_ID` | `--competition-id` | `1` | 1 = Bundesliga, 2 = 2. Bundesliga, 3 = La Liga. |
| `OUTPUT_DIR` | `--output-dir` | `output` | Where the published files are written. |
| `MAX_STALENESS_DAYS` | `--max-staleness-days` | `7` | Refuse to publish data older than this. |
| `CACHE_DB` | `--cache-db` | `player_data_total.db` | Path of the optional local SQLite cache. |
| `WRITE_CACHE` | `--write-cache` | off | Save the fetched data to the cache. |
| `USE_CACHE` | `--use-cache` | off | Read the cache instead of fetching, and skip the token. |
| `ALLOW_STALE` | `--allow-stale` | off | Skip the staleness limit, however old the data is. |

The last three exist for local development only. CI always fetches fresh data and always
enforces the staleness limit.

Changing `--horizon-days` changes the whole pipeline consistently: the number of targets,
the columns the model predicts, `horizonDays` and `metrics` in `index.json`, and the
length of each player's series. Every extra day also holds one more day out of training,
since a training row needs all of its targets.

A quick loop that avoids re-downloading everything:

```bash
python run_forecast.py --write-cache               # once, to fill the cache
python run_forecast.py --use-cache --allow-stale   # afterwards, offline
```

`--allow-stale` is needed there only once the cache is more than a week old.

## Setting up a fork

1. Add the repository secrets `KICK_USER` and `KICK_PASS`.
2. Settings → Pages → Source: **GitHub Actions**.
3. Actions tab: enable workflows — forks have them disabled by default.
4. Run the *Forecast* workflow once via "Run workflow" and open the Pages URL.

Note that this repository is public so that GitHub Pages works on the Free plan, which
means **workflow logs are public**. The code therefore never prints the token, the
credentials or raw API responses — not even the status text of a failed login, which can
echo the submitted email address — and neither should anything you add.

## Known issues

`merge_asof` joins a performance row onto the market value row of the same date. A match
that kicks off in the evening finishes *after* the ~20:00 UTC recalculation, so its
points are attached to a market value that could not have known about them — the match
result leaks into that day's features. The fix is to shift a performance row to the next
day when kick-off + 2h is later than 20:00 UTC. Tracked as a TODO in `run_forecast.py`.

The leak is real but small: refitting without the `p` feature entirely moves h1 from
R² 0.9161 to 0.9136, and `p` carries about 3% of the feature importance. The model runs
almost entirely on the market value's own recent history — `mv_change_1d` at 34% and
`mv_trend_1d` at 20%. So the reported metrics are mildly optimistic, not inflated.

Separately, the IQR clip bounds in `preprocess_player_data` are computed over the whole
frame *before* the train/test split, so the test set's own distribution informs how its
targets are clipped. It shrinks the tails on both sides of the split, which flatters MAE
and RMSE a little against real euros.

## Credits

- [LennardFe/Kickbase-Trading-Advisor](https://github.com/LennardFe/Kickbase-Trading-Advisor)
  — the original tool this is forked from. The data fetching, the feature engineering and
  the model are all theirs.
- [kevinskyba](https://github.com/kevinskyba) — the community
  [Kickbase API documentation](https://kevinskyba.github.io/kickbase-api-doc/index.html).
