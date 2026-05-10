# Influx-to-Web Publisher

## Purpose
Fetch a temperature data point from InfluxDB (backing a Grafana dashboard) and publish it as a JSON file to a Cloudflare Pages static site.

## Architecture
- **Source:** InfluxDB 2.x with validated f-string Flux queries (allowlist-based input validation, see `_validate_flux_value` and `_parse_duration_env` in `publish_temperature.py`), bucket `home_assistant`
- **Transport:** Wrangler CLI deploys the `site/` directory to Cloudflare Pages
- **Destination:** Static site on Cloudflare Pages containing `index.html` (temperature display) and `temperature.json` (data)
- **Frontend:** Single-page `index.html` with inline CSS/JS, displays temperature in large centered text, auto-refreshes every 60 seconds
- **Automation:** Cron job runs the fetch-and-publish script periodically

## Key Data Point
- Measurement: `http_listener_v2`
- Field: `temperature`
- Device: `gisebo-01`
- Query fetches the last (most recent) value

## Flux Query
The snippet below is illustrative pseudocode showing the query shape, not the literal source. The real query lives in `fetch_temperature()` in `publish_temperature.py` and uses validated f-string interpolation plus a multi-yield form that also computes 36h min/max in the same round trip.
```flux
from(bucket: "home_assistant")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == params.measurement)
  |> filter(fn: (r) => r["_field"] == params.field)
  |> filter(fn: (r) => r["device_id"] == params.device_id)
  |> last()
```

## Project Conventions
- All configuration lives in `.env` (not committed, listed in `.gitignore`)
- Code and config are strictly separated
- Python script using `influxdb-client` library with validated f-string queries
- See `SETUP.md` for step-by-step configuration guide
