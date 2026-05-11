#!/usr/bin/env python3
"""Fetch latest temperature from InfluxDB and publish to Cloudflare Pages."""

import glob
import html
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

# site/ is the deploy directory Wrangler uploads to Cloudflare Pages.
# It is treated as pure build output: index.html, temperature.json, and
# og-*.png are all (re)generated on every publish run. The static
# _headers file is the one committed exception, since it is not
# templated and never changes per run.
SITE_DIR = Path(__file__).parent / "site"
if not SITE_DIR.is_dir():
    print(f"Site directory not found: {SITE_DIR.resolve()}", file=sys.stderr)
    sys.exit(1)

# templates/ holds the hand-edited source of index.html. The publish
# pipeline renders it (currently just by rewriting the OG meta block)
# into SITE_DIR/index.html on every run. Keeping the template out of
# the deploy directory prevents every publish run from dirtying a
# committed file with a rotating OG image filename.
TEMPLATE_DIR = Path(__file__).parent / "templates"
if not (TEMPLATE_DIR / "index.html").is_file():
    print(
        f"Index template not found: {(TEMPLATE_DIR / 'index.html').resolve()}",
        file=sys.stderr,
    )
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
    #
    # |> group() is load-bearing. Without it, InfluxDB returns one
    # table per unique tag combination (e.g. one per `host` value),
    # and last()/min()/max() are computed per-series, not globally.
    # In practice a single device often reports under several `host`
    # tags over a 30-day window (each container restart picks a new
    # short hostname), so last() per-series returns several "latest"
    # rows and downstream Python is forced to pick one with no
    # principled basis. group() collapses everything into a single
    # group so the selectors operate over all points for the device.
    #
    # |> sort(columns: ["_time"]) after group() is also load-bearing.
    # Flux `last()` returns the LAST RECORD in the table's iteration
    # order; it does NOT scan for the maximum `_time`. Per-series
    # inputs are time-sorted by upstream operators (range/filter),
    # but group() merges them without preserving global time order,
    # so the table after group() can have rows from older series at
    # the end. Without an explicit sort, last() returns whichever row
    # group() happened to append last, which is exactly the
    # non-deterministic stale-reading symptom this whole block exists
    # to prevent. min()/max() below are value selectors and do not
    # depend on sort order, so the sort only matters for last().
    query = f"""
data = from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: {QUERY_RANGE})
  |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
  |> filter(fn: (r) => r["_field"] == "{FIELD}")
  |> filter(fn: (r) => r["device_id"] == "{DEVICE_ID}")
  |> group()
  |> sort(columns: ["_time"])

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
        last_seen_any = False  # True if at least one "last" record arrived, even if all were invalid
        min_36h = None
        max_36h = None

        for table in tables:
            yield_name = _table_yield_name(table)
            # Unnamed yields are treated as the "last" yield. Multi-yield
            # queries always name their outputs, but older single-yield
            # shapes (or test fixtures) may omit the name entirely.
            effective_yield = yield_name or "last"
            for record in table.records:
                value = record.get_value()
                if effective_yield == "last":
                    last_seen_any = True
                    validated = _validate_last_value(value)
                    if validated is None:
                        # Skip this invalid record but keep scanning. With
                        # |> group() in the Flux query we expect exactly
                        # one "last" record, so this branch should not
                        # trigger in practice. The defensive continue
                        # exists so a single bad row in a future
                        # multi-row shape does not abort the whole
                        # publish if a good row also exists.
                        continue
                    record_time = record.get_time()
                    # Across multiple "last" records, keep the one with the
                    # newest timestamp. Defense in depth: the |> group()
                    # in the Flux pipeline should make this loop see only
                    # one record, but if grouping is ever accidentally
                    # dropped or a new tag dimension silently splits the
                    # series, the time-wise newest still wins (rather
                    # than whichever table the client iterated last,
                    # which is non-deterministic).
                    if last_time is None or record_time > last_time:
                        last_value = validated
                        last_time = record_time
                elif effective_yield == "min_36h":
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        # Fold across all valid records. With group() we
                        # expect one record, but fold-min is the right
                        # semantic for any future shape.
                        min_36h = value if min_36h is None else min(min_36h, value)
                elif effective_yield == "max_36h":
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        max_36h = value if max_36h is None else max(max_36h, value)

        # No "last" record at all: nothing to publish.
        if not last_seen_any:
            return None
        # "last" rows arrived but every one failed validation (NaN, inf,
        # None, non-numeric). Preserve the pre-existing abort behavior
        # so corrupt data is not silently published.
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
    """Render templates/index.html into site/index.html with OG meta filled in.

    The template is the hand-edited source. The site copy is the
    deployable artifact Wrangler uploads on this run. Reading from one
    path and writing to another keeps the committed template clean and
    confines the rotating OG image filename to a gitignored output.
    """
    template_path = TEMPLATE_DIR / "index.html"
    output_path = SITE_DIR / "index.html"
    # Local variable name avoids shadowing the imported `html` module
    # used below for html.escape(). Naming it source_html instead of
    # html keeps the escape calls below resolving to the stdlib module
    # without renaming every usage at the call site of escape().
    source_html = template_path.read_text()

    temp = data["temperature"]
    # T-023: prefer the pretty-printed display form for human-facing
    # surfaces (OG title, OG description, Twitter card). The raw
    # device_id stays in the JSON so machine consumers (dashboards,
    # external integrations) keep a stable identifier.
    device = data.get("device_name") or data["device_id"]
    # T-024: html.escape with quote=True replaces &, <, >, ", and ' with
    # their entity equivalents so a hostile device name cannot break
    # out of the content="..." attribute and inject sibling tags. The
    # CSP at site/_headers blocks inline script execution, so the
    # remaining risk is structural breakage of the meta block (which
    # would break OG previews on social-media crawlers), not script
    # execution. We escape both the textual fields and the image URL,
    # since SITE_URL flows from operator-controlled .env and the
    # filename embeds a UUID we generate ourselves but that still
    # passes through string interpolation.
    og_title = html.escape(f"{temp}°C — {device} Temperature", quote=True)
    og_desc = html.escape(
        f"Current reading: {temp}°C from sensor {device}. Live temperature display updated automatically.",
        quote=True,
    )
    og_image = html.escape(f"{SITE_URL}/{og_filename}", quote=True)
    og_url = html.escape(f"{SITE_URL}/", quote=True)

    og_block = f"""    <!-- OG_META_START -->
    <meta property="og:title" content="{og_title}">
    <meta property="og:description" content="{og_desc}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{og_url}">
    <meta property="og:image" content="{og_image}">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{og_title}">
    <meta name="twitter:description" content="{og_desc}">
    <meta name="twitter:image" content="{og_image}">
    <!-- OG_META_END -->"""

    import re as _re
    rewritten = _re.sub(
        r"    <!-- OG_META_START -->.*?<!-- OG_META_END -->",
        og_block,
        source_html,
        flags=_re.DOTALL,
    )
    output_path.write_text(rewritten)


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
