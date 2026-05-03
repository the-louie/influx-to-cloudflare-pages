# Influx-to-Web Temperature Publisher

Fetches the latest temperature reading from an InfluxDB instance and publishes it to a Cloudflare Pages site. The result is a single web page that displays the current temperature in large text, refreshing automatically every 60 seconds.

## How It Works

```
InfluxDB  --->  publish_temperature.py  --->  Cloudflare Pages
(Flux query)       (fetch + validate)         (site/index.html + temperature.json)
```

1. The Python script queries InfluxDB for the most recent temperature value
2. It validates the reading (rejects null, non-numeric, NaN, and infinite values)
3. It writes the data to `site/temperature.json`
4. It deploys the `site/` directory to Cloudflare Pages using the Wrangler CLI
5. The static `index.html` page fetches `temperature.json` and displays the value

The script is designed to run as a cron job. All output uses structured logging for compatibility with log collectors.

## The Web Page

A minimal, single-page display inspired by [vecka.nu](https://vecka.nu/):

- Light blue background with the temperature shown in large, bold text
- Device ID label above the number
- "Last updated" timestamp below
- Responsive layout that works on desktop and mobile
- Auto-refreshes the data every 60 seconds without reloading the page
- Shows "--" if data is unavailable

## Quick Start

```bash
# 1. Clone and install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your values (see SETUP.md for detailed guidance)

# 3. Authenticate Wrangler (first time only)
npx wrangler login

# 4. Run
python publish_temperature.py
```

For detailed instructions on where to find each configuration value, see [SETUP.md](SETUP.md).

## Wrangler Authentication

Since this runs via cron, the authentication flow is:

1. Run the script manually the first time and log in via the browser prompt
2. Wrangler persists the login credentials locally for future runs
3. The `CLOUDFLARE_API_TOKEN` in `.env` is used for API authentication on subsequent runs

## Configuration

All configuration lives in a `.env` file (not committed to git). Copy `.env.example` to get started.

| Variable | Required | Description |
|----------|----------|-------------|
| `INFLUXDB_URL` | Yes | InfluxDB base URL (e.g. `http://localhost:8086`) |
| `INFLUXDB_TOKEN` | Yes | Read-only API token for InfluxDB |
| `INFLUXDB_ORG` | Yes | InfluxDB organization name |
| `INFLUXDB_BUCKET` | Yes | Bucket name (e.g. `home_assistant`) |
| `MEASUREMENT` | Yes | InfluxDB measurement (e.g. `http_listener_v2`) |
| `FIELD` | Yes | Field key (e.g. `temperature`) |
| `DEVICE_ID` | Yes | Device identifier tag (e.g. `gisebo-01`) |
| `HOST_FILTER` | Yes | InfluxDB host tag value |
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token with Pages edit permission |
| `CLOUDFLARE_ACCOUNT_ID` | Yes | Cloudflare account identifier |
| `CLOUDFLARE_PROJECT_NAME` | Yes | Cloudflare Pages project name |
| `TIMEOUT_SECONDS` | No | InfluxDB query timeout in seconds (default: 30) |
| `DEPLOY_TIMEOUT_SECONDS` | No | Wrangler deploy timeout in seconds (default: 120) |
| `TEMP_MIN` | No | Low bound for sanity check (default: -50) |
| `TEMP_MAX` | No | High bound for sanity check (default: 80) |

## Cron Setup

Run every 5 minutes:

```
*/5 * * * * cd /path/to/project && /path/to/venv/bin/python publish_temperature.py
```

Logging goes to stderr with timestamps, so you can redirect to a log file:

```
*/5 * * * * cd /path/to/project && /path/to/venv/bin/python publish_temperature.py >> /var/log/temperature.log 2>&1
```

## Project Structure

```
.
├── publish_temperature.py    # Main script: fetch, validate, deploy
├── site/
│   └── index.html            # Static temperature display page
├── test_publish_temperature.py  # Test suite (35 tests)
├── requirements.txt          # Pinned Python dependencies
├── .env.example              # Template for configuration
├── SETUP.md                  # Step-by-step setup guide
├── CLAUDE.md                 # Project conventions
└── TODO.md                   # Task tracking
```

## Data Format

The script writes `site/temperature.json` with this structure:

```json
{
  "temperature": 22.5,
  "time": "2026-05-02T12:34:56.789012+00:00",
  "device_id": "gisebo-01",
  "updated_at": "2026-05-02T12:35:00.123456+00:00"
}
```

Currently only one data point is published. The structure is designed to support multiple devices in the future.

## Running Tests

```bash
python -m pytest test_publish_temperature.py -v
```

## Dependencies

- Python 3.8+
- `influxdb-client` (pinned in requirements.txt)
- `python-dotenv` (pinned in requirements.txt)
- Node.js with `npx` (for the Wrangler CLI)
