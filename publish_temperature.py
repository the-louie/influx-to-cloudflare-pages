#!/usr/bin/env python3
"""Fetch latest temperature from InfluxDB and publish to remote static site."""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

load_dotenv()

REQUIRED_VARS = [
    "INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET",
    "MEASUREMENT", "FIELD", "DEVICE_ID", "HOST_FILTER",
    "REMOTE_USER", "REMOTE_HOST", "REMOTE_PATH",
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

# Remote host
REMOTE_USER = os.environ["REMOTE_USER"]
REMOTE_HOST = os.environ["REMOTE_HOST"]
REMOTE_PATH = os.environ["REMOTE_PATH"]

TIMEOUT_SECONDS = int(os.environ.get("TIMEOUT_SECONDS", "30"))


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
                return {
                    "temperature": record.get_value(),
                    "time": record.get_time().isoformat(),
                    "device_id": DEVICE_ID,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
    finally:
        client.close()

    return None


def publish(data):
    remote_dest = f"{REMOTE_USER}@{REMOTE_HOST}"
    remote_tmp = REMOTE_PATH + ".tmp"

    # Write JSON to a local temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        local_tmp = f.name

    try:
        # SCP to a temp file on the remote host
        subprocess.run(
            ["scp", "-q", local_tmp, f"{remote_dest}:{remote_tmp}"],
            check=True,
            timeout=TIMEOUT_SECONDS,
        )
        # Atomic move on the remote host
        subprocess.run(
            ["ssh", remote_dest, "mv", remote_tmp, REMOTE_PATH],
            check=True,
            timeout=TIMEOUT_SECONDS,
        )
    finally:
        os.unlink(local_tmp)


def main():
    data = fetch_temperature()
    if data is None:
        print("No data returned from InfluxDB", file=sys.stderr)
        sys.exit(1)

    publish(data)
    print(f"Published: {data['temperature']}°C at {data['time']}")


if __name__ == "__main__":
    main()
