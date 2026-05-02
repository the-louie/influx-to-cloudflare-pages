#!/usr/bin/env python3
"""Fetch latest temperature from InfluxDB and publish to Cloudflare Pages."""

import json
import logging
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

load_dotenv()

REQUIRED_VARS = [
    "INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET",
    "MEASUREMENT", "FIELD", "DEVICE_ID", "HOST_FILTER",
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_PROJECT_NAME",
]
missing = [v for v in REQUIRED_VARS if v not in os.environ]
if missing:
    print(
        f"Missing required environment variables: {', '.join(missing)}\n"
        "Copy .env.example to .env and fill in all values.",
        file=sys.stderr,
    )
    sys.exit(1)

# InfluxDB config
INFLUXDB_URL = os.environ["INFLUXDB_URL"]
INFLUXDB_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ["INFLUXDB_BUCKET"]

# Query filters
MEASUREMENT = os.environ["MEASUREMENT"]
FIELD = os.environ["FIELD"]
DEVICE_ID = os.environ["DEVICE_ID"]
HOST_FILTER = os.environ["HOST_FILTER"]

# Cloudflare Pages
CLOUDFLARE_PROJECT_NAME = os.environ["CLOUDFLARE_PROJECT_NAME"]

TIMEOUT_SECONDS = int(os.environ.get("TIMEOUT_SECONDS", "30"))

SITE_DIR = Path(__file__).parent / "site"


def fetch_temperature():
    if not re.match(r"^[a-zA-Z0-9_-]+$", INFLUXDB_BUCKET):
        raise ValueError(f"Invalid bucket name: {INFLUXDB_BUCKET}")

    query = f"""
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == params.measurement)
  |> filter(fn: (r) => r["_field"] == params.field)
  |> filter(fn: (r) => r["device_id"] == params.device_id)
  |> filter(fn: (r) => r["host"] == params.host_filter)
  |> last()
"""
    params = {
        "measurement": MEASUREMENT,
        "field": FIELD,
        "device_id": DEVICE_ID,
        "host_filter": HOST_FILTER,
    }
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=TIMEOUT_SECONDS * 1000)
    try:
        tables = client.query_api().query(query, params=params)
        for table in tables:
            for record in table.records:
                value = record.get_value()
                if value is None:
                    logging.warning("InfluxDB returned None value")
                    return None
                if not isinstance(value, (int, float)):
                    logging.warning(f"InfluxDB returned non-numeric value: {value!r}")
                    return None
                if not math.isfinite(value):
                    logging.warning(f"InfluxDB returned non-finite value: {value}")
                    return None
                temp_min = int(os.environ.get("TEMP_MIN", "-50"))
                temp_max = int(os.environ.get("TEMP_MAX", "80"))
                if not (temp_min <= value <= temp_max):
                    logging.warning(f"Temperature {value} outside expected range [{temp_min}, {temp_max}]")
                return {
                    "temperature": value,
                    "time": record.get_time().isoformat(),
                    "device_id": DEVICE_ID,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
    finally:
        client.close()

    return None


def publish(data):
    # Write temperature.json into the site directory
    json_path = SITE_DIR / "temperature.json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    # Deploy the site directory to Cloudflare Pages via Wrangler
    subprocess.run(
        [
            "npx", "wrangler", "pages", "deploy",
            str(SITE_DIR),
            "--project-name", CLOUDFLARE_PROJECT_NAME,
        ],
        check=True,
        timeout=TIMEOUT_SECONDS,
    )


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    data = fetch_temperature()
    if data is None:
        logging.error("No data returned from InfluxDB")
        sys.exit(1)

    publish(data)
    logging.info(f"Published: {data['temperature']}°C at {data['time']}")


if __name__ == "__main__":
    main()
