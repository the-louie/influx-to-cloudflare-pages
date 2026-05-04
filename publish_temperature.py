#!/usr/bin/env python3
"""Fetch latest temperature from InfluxDB and publish to Cloudflare Pages."""

import glob
import json
import logging
import math
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

load_dotenv()

REQUIRED_VARS = [
    "INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET",
    "MEASUREMENT", "FIELD", "DEVICE_ID",
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


def _pretty_device_name(device_id):
    """Convert a machine identifier into a display-friendly form.

    Replaces '-' and '_' with spaces and upper-cases the first
    character. Casing of the rest of the string is preserved (so
    'Foo-Bar' becomes 'Foo Bar', not 'Foo bar'). Empty input yields
    empty output.

    Examples:
        gisebo-01            -> Gisebo 01
        living_room          -> Living room
        temp-sensor_kitchen  -> Temp sensor kitchen
        Foo-Bar              -> Foo Bar
        a                    -> A
    """
    if not device_id:
        return ""
    cleaned = device_id.replace("-", " ").replace("_", " ")
    return cleaned[0].upper() + cleaned[1:]


# Flux duration literal: a leading minus, one or more digits, then a unit
# character (s seconds, m minutes, h hours, d days, w weeks). Examples that
# pass: -30d, -12h, -7d, -1w. Examples that fail: 30d (no minus), -30 (no
# unit), -30y (unsupported unit), abc (not a duration at all).
_DURATION_PATTERN = re.compile(r"^-\d+[smhdw]$")


def _parse_duration_env(name, default):
    """Read a Flux duration env var, validate format, exit cleanly on failure.

    Sibling of _parse_int_env. Used by QUERY_RANGE so the value can be
    interpolated directly into the Flux query string without quoting,
    since Flux durations are bare literals (range(start: -30d)) not
    strings.

    Direct f-string interpolation is safe here because the regex
    allowlist below permits only one minus sign, ASCII digits, and a
    single unit character. None of those characters can break out of
    the Flux duration grammar, so there is no escape vector even
    though the value originates in an operator-controlled .env file.
    """
    raw = os.environ.get(name, default)
    if not _DURATION_PATTERN.match(raw):
        print(
            f"Invalid duration for {name}: {raw!r}. "
            f"Expected format like -30d, -12h, -7d, -1w (leading minus, "
            f"digits, unit s/m/h/d/w).",
            file=sys.stderr,
        )
        sys.exit(1)
    return raw


# InfluxDB config
INFLUXDB_URL = os.environ["INFLUXDB_URL"]
INFLUXDB_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ["INFLUXDB_BUCKET"]

# Query filters
MEASUREMENT = os.environ["MEASUREMENT"]
FIELD = os.environ["FIELD"]
DEVICE_ID = os.environ["DEVICE_ID"]

# Cloudflare Pages
CLOUDFLARE_PROJECT_NAME = os.environ["CLOUDFLARE_PROJECT_NAME"]
SITE_URL = os.environ.get("SITE_URL", f"https://{CLOUDFLARE_PROJECT_NAME}.pages.dev").rstrip("/")

TIMEOUT_SECONDS = _parse_int_env("TIMEOUT_SECONDS", "30")
DEPLOY_TIMEOUT_SECONDS = _parse_int_env("DEPLOY_TIMEOUT_SECONDS", "120")
TEMP_MIN = _parse_int_env("TEMP_MIN", "-50")
TEMP_MAX = _parse_int_env("TEMP_MAX", "80")
# How far back to scan in the bucket. Keeps query time bounded as the
# bucket grows. Default of -30d is generous for sensors that report every
# few minutes. Operators with sparser sensors (e.g. one reading per week)
# may need to widen this to -90d or more.
QUERY_RANGE = _parse_duration_env("QUERY_RANGE", "-30d")

SITE_DIR = Path(__file__).parent / "site"
if not SITE_DIR.is_dir():
    print(f"Site directory not found: {SITE_DIR.resolve()}", file=sys.stderr)
    sys.exit(1)


def _validate_flux_value(name, value):
    """Reject values containing characters that could alter the Flux query structure."""
    if '"' in value or '\\' in value:
        raise ValueError(f"Invalid character in {name}: {value!r}")


def _table_yield_name(table):
    """Return the Flux yield name (set via |> yield(name: ...)) for a table.

    The yield name lives in the table's group key under the column
    'result'. Different client versions expose this slightly
    differently, so we check several access paths and fall back to
    inspecting the first record's values dict. Returns an empty
    string if no name is available, in which case the caller treats
    the table as the default 'last' yield.

    Strict isinstance(str) check: anything non-string (None, mock
    objects in tests, unexpected client return shapes) falls through
    to the next path or to the empty-string default. This prevents
    silent miscategorisation of tables.
    """
    try:
        group_key = table.get_group_key()
        if hasattr(group_key, "get") and callable(group_key.get):
            name = group_key.get("result")
            if isinstance(name, str) and name:
                return name
    except Exception:
        pass
    for record in table.records:
        try:
            name = record.values.get("result", "")
            if isinstance(name, str):
                return name
            return ""
        except Exception:
            return ""
    return ""


def _validate_last_value(value):
    """Sanity-check the most-recent reading.

    Returns the value if usable, or None if it should be discarded.
    A warning is logged for out-of-range values, but they are still
    returned (the operator can adjust TEMP_MIN/TEMP_MAX if their
    sensor genuinely sees those readings).
    """
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
    return value


def fetch_temperature():
    if not re.match(r"^[a-zA-Z0-9_-]+$", INFLUXDB_BUCKET):
        raise ValueError(f"Invalid bucket name: {INFLUXDB_BUCKET}")

    for name, val in [("MEASUREMENT", MEASUREMENT), ("FIELD", FIELD),
                      ("DEVICE_ID", DEVICE_ID)]:
        _validate_flux_value(name, val)

    # Multi-yield query. The 'data =' alias defines the filtered
    # series once, then three yields aggregate it differently and
    # return three separate tables. The 36h window for min/max is
    # intentionally hardcoded and independent of QUERY_RANGE, since
    # QUERY_RANGE only bounds how far back to look for the latest
    # reading and 36h is the user-facing recency window for the
    # min/max display.
    query = f"""
data = from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: {QUERY_RANGE})
  |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
  |> filter(fn: (r) => r["_field"] == "{FIELD}")
  |> filter(fn: (r) => r["device_id"] == "{DEVICE_ID}")

data
  |> last()
  |> yield(name: "last")

data
  |> range(start: -36h)
  |> min()
  |> yield(name: "min_36h")

data
  |> range(start: -36h)
  |> max()
  |> yield(name: "max_36h")
"""
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG, timeout=TIMEOUT_SECONDS * 1000)
    try:
        tables = client.query_api().query(query)

        last_value = None
        last_time = None
        min_36h = None
        max_36h = None

        for table in tables:
            yield_name = _table_yield_name(table)
            for record in table.records:
                value = record.get_value()
                if yield_name == "last" or (yield_name == "" and last_value is None):
                    validated = _validate_last_value(value)
                    if validated is None:
                        return None
                    last_value = validated
                    last_time = record.get_time()
                elif yield_name == "min_36h":
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        min_36h = value
                elif yield_name == "max_36h":
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        max_36h = value

        if last_value is None or last_time is None:
            return None

        return {
            "temperature": last_value,
            "time": last_time.isoformat(),
            "device_id": DEVICE_ID,
            "device_name": _pretty_device_name(DEVICE_ID),
            "min_36h": min_36h,
            "max_36h": max_36h,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        client.close()


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

    # Draw device label above temperature. Prefer the pretty-printed
    # form (T-023) and fall back to the raw machine identifier if a
    # caller passes a payload that predates device_name.
    device_text = data.get("device_name") or data.get("device_id", "")
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
        draw.text(((width - text_w) / 2, temp_y + text_h + 68), date_text, fill=white, font=font_date)

    # Remove old OG images and save with a unique name to bust social media caches
    for old in glob.glob(str(SITE_DIR / "og-*.png")):
        os.remove(old)
    og_filename = f"og-{uuid.uuid4().hex[:12]}.png"
    img.save(SITE_DIR / og_filename)
    return og_filename


def _update_og_meta(data, og_filename):
    """Rewrite the OG meta tags in index.html with absolute URLs and current data."""
    index_path = SITE_DIR / "index.html"
    html = index_path.read_text()

    temp = data["temperature"]
    device = data["device_id"]
    og_title = f"{temp}°C — {device} Temperature"
    og_desc = f"Current reading: {temp}°C from sensor {device}. Live temperature display updated automatically."
    og_image = f"{SITE_URL}/{og_filename}"

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
    og_filename = generate_og_image(data)
    _update_og_meta(data, og_filename)
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
