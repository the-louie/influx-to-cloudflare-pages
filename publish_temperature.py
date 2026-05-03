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

from PIL import Image, ImageDraw, ImageFont
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


def _parse_int_env(name, default):
    raw = os.environ.get(name, default)
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid integer for {name}: {raw!r}", file=sys.stderr)
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
SITE_URL = os.environ.get("SITE_URL", f"https://{CLOUDFLARE_PROJECT_NAME}.pages.dev").rstrip("/")

TIMEOUT_SECONDS = _parse_int_env("TIMEOUT_SECONDS", "30")
DEPLOY_TIMEOUT_SECONDS = _parse_int_env("DEPLOY_TIMEOUT_SECONDS", "120")
TEMP_MIN = _parse_int_env("TEMP_MIN", "-50")
TEMP_MAX = _parse_int_env("TEMP_MAX", "80")

SITE_DIR = Path(__file__).parent / "site"
if not SITE_DIR.is_dir():
    print(f"Site directory not found: {SITE_DIR.resolve()}", file=sys.stderr)
    sys.exit(1)


def _validate_flux_value(name, value):
    """Reject values containing characters that could alter the Flux query structure."""
    if '"' in value or '\\' in value:
        raise ValueError(f"Invalid character in {name}: {value!r}")


def fetch_temperature():
    if not re.match(r"^[a-zA-Z0-9_-]+$", INFLUXDB_BUCKET):
        raise ValueError(f"Invalid bucket name: {INFLUXDB_BUCKET}")

    for name, val in [("MEASUREMENT", MEASUREMENT), ("FIELD", FIELD),
                      ("DEVICE_ID", DEVICE_ID), ("HOST_FILTER", HOST_FILTER)]:
        _validate_flux_value(name, val)

    query = f"""
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: 0)
  |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
  |> filter(fn: (r) => r["_field"] == "{FIELD}")
  |> filter(fn: (r) => r["device_id"] == "{DEVICE_ID}")
  |> filter(fn: (r) => r["host"] == "{HOST_FILTER}")
  |> last()
"""
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=TIMEOUT_SECONDS * 1000)
    try:
        tables = client.query_api().query(query)
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
                if not (TEMP_MIN <= value <= TEMP_MAX):
                    logging.warning(f"Temperature {value} outside expected range [{TEMP_MIN}, {TEMP_MAX}]")
                return {
                    "temperature": value,
                    "time": record.get_time().isoformat(),
                    "device_id": DEVICE_ID,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
    finally:
        client.close()

    return None


def generate_og_image(data):
    """Generate a 1200x630 OpenGraph image matching the page style."""
    width, height = 1200, 630
    bg_color = (144, 192, 222)  # #90c0de
    text_color = (28, 123, 183)  # #1c7bb7
    white = (255, 255, 255, 255)  # #fff

    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 200)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
        font_date = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except OSError:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_date = ImageFont.load_default()

    # Draw device ID label above temperature
    device_text = data.get("device_id", "")
    bbox = draw.textbbox((0, 0), device_text, font=font_small)
    text_w = bbox[2] - bbox[0]
    draw.text(((width - text_w) / 2, 130), device_text, fill=white, font=font_small)

    # Draw temperature with unit, centered
    temp_text = f"{data['temperature']}°C"
    bbox = draw.textbbox((0, 0), temp_text, font=font_large)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    temp_y = (height - text_h) / 2
    draw.text(((width - text_w) / 2, temp_y), temp_text, fill=text_color, font=font_large)

    # Draw date below temperature
    from datetime import datetime as _dt
    try:
        dt = _dt.fromisoformat(data["time"])
        date_text = dt.strftime("%b %d, %Y %H:%M")
    except (ValueError, KeyError):
        date_text = ""
    if date_text:
        bbox = draw.textbbox((0, 0), date_text, font=font_date)
        text_w = bbox[2] - bbox[0]
        draw.text(((width - text_w) / 2, temp_y + text_h + 20), date_text, fill=white, font=font_date)

    img.save(SITE_DIR / "og-image.png")


def _update_og_meta(data):
    """Rewrite the OG meta tags in index.html with absolute URLs and current data."""
    index_path = SITE_DIR / "index.html"
    html = index_path.read_text()

    temp = data["temperature"]
    device = data["device_id"]
    og_title = f"{temp}°C — {device} Temperature"
    og_desc = f"Current reading: {temp}°C from sensor {device}. Live temperature display updated automatically."
    og_image = f"{SITE_URL}/og-image.png"

    og_block = f"""    <!-- OG_META_START -->
    <meta property="og:title" content="{og_title}">
    <meta property="og:description" content="{og_desc}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{SITE_URL}/">
    <meta property="og:image" content="{og_image}">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{og_title}">
    <meta name="twitter:description" content="{og_desc}">
    <meta name="twitter:image" content="{og_image}">
    <!-- OG_META_END -->"""

    import re as _re
    html = _re.sub(
        r"    <!-- OG_META_START -->.*?<!-- OG_META_END -->",
        og_block,
        html,
        flags=_re.DOTALL,
    )
    index_path.write_text(html)


def publish(data):
    generate_og_image(data)
    _update_og_meta(data)
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
            "--commit-dirty=true",
        ],
        check=True,
        timeout=DEPLOY_TIMEOUT_SECONDS,
    )


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    logging.info(f"-------- STARTED {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} --------")
    try:
        data = fetch_temperature()
        if data is None:
            logging.error("No data returned from InfluxDB")
            sys.exit(1)

        publish(data)
        logging.info(f"Published: {data['temperature']}°C at {data['time']}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Deploy failed: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
