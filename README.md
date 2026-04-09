# Influx-to-Web Temperature Publisher

Fetches the latest temperature reading from an InfluxDB instance and publishes it to a Cloudflare Pages site. The result is a single web page that displays the current temperature in large text, refreshing automatically every 60 seconds.

## How It Works

```
InfluxDB  --->  publish_temperature.py  --->  Cloudflare Pages
(Flux query)       (fetch + validate)         (site/index.html + temperature.json)
```

1. The Python script queries InfluxDB for the most recent temperature value
2. It validates the reading (rejects null, non-numeric, NaN, and infinite values)
3. It generates `site/og-image.png` for social media link previews
4. It writes the data to `site/temperature.json`
5. It deploys the `site/` directory to Cloudflare Pages using the Wrangler CLI
6. The static `index.html` page fetches `temperature.json` and displays the value

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
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your values (see SETUP.md for detailed guidance)

# 4. Run
python publish_temperature.py
```

For detailed instructions on where to find each configuration value, see [SETUP.md](SETUP.md).

## Wrangler Authentication

Wrangler authenticates automatically using the `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` environment variables from your `.env` file. No interactive login (`wrangler login`) is needed, which makes it safe to run unattended via cron.

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
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token with Pages edit permission |
| `CLOUDFLARE_ACCOUNT_ID` | Yes | Cloudflare account identifier |
| `CLOUDFLARE_PROJECT_NAME` | Yes | Cloudflare Pages project name |
| `TIMEOUT_SECONDS` | No | InfluxDB query timeout in seconds (default: 30) |
| `DEPLOY_TIMEOUT_SECONDS` | No | Wrangler deploy timeout in seconds (default: 120) |
| `TEMP_MIN` | No | Low bound for sanity check (default: -50) |
| `TEMP_MAX` | No | High bound for sanity check (default: 80) |

### Creating an InfluxDB API Token

1. Open the InfluxDB UI (e.g. `http://localhost:8086`)
2. Go to **Load Data** > **API Tokens**
3. Click **Generate API Token** > **Custom API Token**
4. Under **Read**, select your bucket (e.g. `home_assistant`)
5. Leave **Write** unchecked, the script only needs read access
6. Click **Generate** and copy the token into your `.env`

### Creating a Cloudflare API Token

1. Log in to the [Cloudflare dashboard](https://dash.cloudflare.com)
2. Click your profile icon > **My Profile** > **API Tokens**
3. Click **Create Token**
4. Use the **Edit Cloudflare Pages** template, or create a custom token with **Cloudflare Pages: Edit** permission
5. Click **Continue to summary** > **Create Token**
6. Copy the token into your `.env` as `CLOUDFLARE_API_TOKEN`

To find your **Account ID**, go to **Workers & Pages** in the Cloudflare dashboard. Your Account ID is shown in the **Account details** section with a click-to-copy button. Alternatively, on the **Account home** page, click the menu button next to your account name and select **Copy account ID**.

For all other configuration values, see [SETUP.md](SETUP.md) for detailed instructions with UI paths.

## Docker

Build and run with Docker Compose. The `.env` file is passed to the container automatically.

```bash
# Build the image
docker compose build

# Run once
docker compose run --rm publisher

# Rebuild after code changes (skips cache)
docker compose build --no-cache
```

The `site/` directory is volume-mounted, so `temperature.json` and `og-image.png` are visible on the host for debugging.

Secrets are never baked into the image. They are read from `.env` at runtime via the `env_file` directive in `docker-compose.yml`.

## Cron Setup

### Without Docker

```
*/5 * * * * cd /path/to/project && .venv/bin/python publish_temperature.py >> /var/log/temperature.log 2>&1
```

### With Docker

```
*/5 * * * * cd /path/to/project && docker compose run --rm publisher >> /var/log/temperature.log 2>&1
```

## Project Structure

```
.
├── publish_temperature.py       # Main script: fetch, validate, deploy
├── site/
│   ├── index.html               # Static temperature display page
│   └── _headers                 # Cloudflare Pages security headers
├── test_publish_temperature.py  # Test suite (39 tests)
├── requirements.txt             # Pinned Python dependencies
├── Dockerfile                   # Container image definition
├── docker-compose.yml           # Docker Compose service config
├── .dockerignore                # Files excluded from Docker build
├── .env.example                 # Template for configuration
├── SETUP.md                     # Step-by-step setup guide
├── CLAUDE.md                    # Project conventions
└── TODO.md                      # Task tracking
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

The test suite has 39 tests covering InfluxDB query validation, timeout propagation, environment variable parsing, temperature value validation, structured logging, Cloudflare deploy, and error handling.

## Development

### Local page preview

You can preview the HTML page without deploying. Create a sample data file and serve it locally:

```bash
echo '{"device_id":"gisebo-01","temperature":22.5,"time":"2026-05-02T12:00:00+00:00","updated_at":"2026-05-02T12:00:01+00:00"}' > site/temperature.json
cd site && python3 -m http.server 8000
```

Open `http://localhost:8000` to see the page. Edit `site/index.html` and refresh.

### Making code changes

1. Edit `publish_temperature.py` or `site/index.html`
2. Run the test suite: `python -m pytest test_publish_temperature.py -v`
3. Test locally: `python publish_temperature.py` (needs a valid `.env`)
4. If using Docker, rebuild: `docker compose build`

### Writing tests

Tests live in `test_publish_temperature.py`. The module uses `_import_fresh()` to re-import `publish_temperature` with a clean environment on each test, since configuration is parsed at module level. Use `monkeypatch.setenv()` to set env vars before calling `_import_fresh()`.

## Dependencies

- Python 3.8+
- `influxdb-client` (pinned in requirements.txt)
- `python-dotenv` (pinned in requirements.txt)
- `Pillow` (pinned in requirements.txt, for OG image generation)
- Node.js with `npx` (for the Wrangler CLI)
- Docker and Docker Compose (optional, for containerized deployment)
