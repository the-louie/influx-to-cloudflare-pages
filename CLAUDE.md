# Influx-to-Web Publisher

## Purpose
Fetch a temperature data point from InfluxDB (backing a Grafana dashboard) and publish it as a JSON file to a Cloudflare Pages static site.

## Architecture
- **Source:** InfluxDB 2.x with validated f-string Flux queries (allowlist-based input validation, see `_validate_flux_value` and `_parse_duration_env` in `publish_temperature.py`), bucket `home_assistant`
- **Template:** `templates/index.html` is the hand-edited source. The publish pipeline renders it into `site/index.html` with the current OG meta block on every run, so the committed template never carries rotating UUIDs.
- **Transport:** Wrangler CLI deploys the `site/` directory to Cloudflare Pages
- **Destination:** Static site on Cloudflare Pages containing the rendered `index.html` (temperature display) and `temperature.json` (data)
- **Frontend:** Single-page `index.html` with inline CSS/JS, displays temperature in large centered text, auto-refreshes every 60 seconds
- **Automation:** Cron job runs the fetch-and-publish script periodically

`site/` is treated as pure build output. Only `site/_headers` is committed; `site/index.html`, `site/temperature.json`, and `site/og-*.png` are all gitignored and regenerated on every publish run.

## Key Data Point
- Measurement: `http_listener_v2`
- Field: `temperature`
- Device: `gisebo-01`
- Query fetches the last (most recent) value

## Flux Query
The snippet below is illustrative pseudocode showing the query shape, not the literal source. The real query lives in `fetch_temperature()` in `publish_temperature.py` and uses validated f-string interpolation plus a multi-yield form that also computes 36h min/max in the same round trip. `|> group()` is load-bearing: without it, `last()`/`min()`/`max()` operate per-series (one table per unique tag combination, e.g. per `host`) and return ambiguous "latest" rows that the Python loop cannot principally rank. `|> sort(columns: ["_time"])` after `group()` is equally load-bearing: Flux `last()` returns the last row in the table's iteration order, not the row with max `_time`, and `group()` does not preserve global time order across merged series.
```flux
from(bucket: "home_assistant")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == params.measurement)
  |> filter(fn: (r) => r["_field"] == params.field)
  |> filter(fn: (r) => r["device_id"] == params.device_id)
  |> group()
  |> sort(columns: ["_time"])
  |> last()
```

## Project Conventions
- All configuration lives in `.env` (not committed, listed in `.gitignore`)
- Code and config are strictly separated
- Python script using `influxdb-client` library with validated f-string queries
- See `SETUP.md` for step-by-step configuration guide
