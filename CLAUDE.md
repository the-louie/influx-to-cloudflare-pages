# Influx-to-Web Publisher

## Purpose
Fetch a temperature data point from InfluxDB (backing a Grafana dashboard) and publish it as a JSON file to a Cloudflare Pages static site.

## Architecture
- **Source:** InfluxDB 2.x with parameterized Flux queries, bucket `home_assistant`
- **Transport:** Wrangler CLI deploys the `site/` directory to Cloudflare Pages
- **Destination:** Static site on Cloudflare Pages containing `index.html` (temperature display) and `temperature.json` (data)
- **Frontend:** Single-page `index.html` with inline CSS/JS, displays temperature in large centered text, auto-refreshes every 60 seconds
- **Automation:** Cron job runs the fetch-and-publish script periodically

## Key Data Point
- Measurement: `http_listener_v2`
- Field: `temperature`
- Device: `gisebo-01`
- Host filter: `61781446e5e9`
- Query fetches the last (most recent) value

## Flux Query
```flux
from(bucket: "home_assistant")
  |> range(start: 0)
  |> filter(fn: (r) => r["_measurement"] == params.measurement)
  |> filter(fn: (r) => r["_field"] == params.field)
  |> filter(fn: (r) => r["device_id"] == params.device_id)
  |> filter(fn: (r) => r["host"] == params.host_filter)
  |> last()
```

## Project Conventions
- All configuration lives in `.env` (not committed, listed in `.gitignore`)
- Code and config are strictly separated
- Python script using `influxdb-client` library with parameterized queries
- See `SETUP.md` for step-by-step configuration guide
