# Influx-to-Web Publisher

## Purpose
Fetch a temperature data point from InfluxDB (backing a Grafana dashboard) and publish it as a JSON file to a remote static web server via SSH.

## Architecture
- **Source:** InfluxDB 2.x with Flux queries, bucket `home_assistant`
- **Transport:** SCP/rsync to remote host (write to temp file, then atomic move to avoid race conditions)
- **Destination:** Static JSON file on a remote web server
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
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "http_listener_v2")
  |> filter(fn: (r) => r["_field"] == "temperature")
  |> filter(fn: (r) => r["device_id"] == "gisebo-01")
  |> filter(fn: (r) => r["host"] == "61781446e5e9")
  |> last()
```

## Project Conventions
- All configuration lives in `.env` (not committed — listed in `.gitignore`)
- Code and config are strictly separated
- Python script using `influxdb-client` library
- Atomic remote writes: scp to a temp file, then `ssh mv` to final path (or rsync which overwrites atomically)
