# Setup Guide

## Quick Start

```bash
cp .env.example .env
# Edit .env and fill in all values (see sections below)
pip install -r requirements.txt
python publish_temperature.py
```

---

## 1. InfluxDB Connection

### `INFLUXDB_URL`

The base URL of your InfluxDB 2.x instance.

- Default: `http://localhost:8086` (standard local install)
- Use `https://` if InfluxDB is on a remote host to protect your API token in transit
- The default port for InfluxDB 2.x is `8086`

### `INFLUXDB_TOKEN`

A read-only API token for querying your bucket.

How to create one:

1. Open the InfluxDB UI (e.g. `http://localhost:8086`)
2. Go to **Load Data** > **API Tokens**
3. Click **Generate API Token** > **Custom API Token**
4. Under **Read**, select your bucket (e.g. `home_assistant`)
5. Leave **Write** permissions unchecked
6. Click **Generate**
7. Copy the token string and paste it into `.env`

### `INFLUXDB_ORG`

Your InfluxDB organization name.

How to find it:

1. Open the InfluxDB UI
2. Go to **Settings** (gear icon) > **Organization**
3. Copy the organization name

Alternatively, run: `influx org list`

### `INFLUXDB_BUCKET`

The bucket where your temperature data is stored.

How to find it:

1. Open the InfluxDB UI
2. Go to **Load Data** > **Buckets**
3. Find the bucket used by your Home Assistant integration (typically `home_assistant`)

---

## 2. Flux Query Filters

These values identify which specific data point to fetch from InfluxDB. You can find all of them using the **Data Explorer** in the InfluxDB UI.

### `MEASUREMENT`

The InfluxDB measurement name.

- For Home Assistant using the HTTP listener input, this is typically `http_listener_v2`
- To find yours: open **Data Explorer**, select your bucket, and look at the measurements listed in the filter sidebar

### `FIELD`

The field key containing the sensor value you want to publish.

- Example: `temperature`
- To find yours: in **Data Explorer**, after selecting the measurement, the available fields are listed in the filter sidebar

### `DEVICE_ID`

The tag value that identifies your specific sensor device.

- Example: `gisebo-01`
- To find yours: in **Data Explorer**, filter on the `device_id` tag to see available devices

### `HOST_FILTER`

The InfluxDB `host` tag value, typically the container ID or hostname of the service writing data to InfluxDB.

- Example: `61781446e5e9`
- To find yours: in **Data Explorer**, browse the `host` tag values after selecting your measurement

---

## 3. Cloudflare Pages

### `CLOUDFLARE_API_TOKEN`

An API token with permission to deploy to Cloudflare Pages.

How to create one:

1. Log in to the [Cloudflare dashboard](https://dash.cloudflare.com)
2. Click your profile icon > **My Profile** > **API Tokens**
3. Click **Create Token**
4. Use the **Edit Cloudflare Pages** template, or create a custom token with **Cloudflare Pages: Edit** permission
5. Copy the token and paste it into `.env`

### `CLOUDFLARE_ACCOUNT_ID`

Your Cloudflare account identifier.

How to find it:

1. Log in to the [Cloudflare dashboard](https://dash.cloudflare.com)
2. Go to **Workers & Pages**, your Account ID is shown in the **Account details** section with a click-to-copy button
3. Alternatively, on the **Account home** page, click the menu button next to your account name and select **Copy account ID**
4. You can also run: `npx wrangler whoami`

### `CLOUDFLARE_PROJECT_NAME`

The name of your Cloudflare Pages project.

How to create one:

1. Log in to the [Cloudflare dashboard](https://dash.cloudflare.com)
2. Go to **Workers & Pages** > **Pages**
3. Click **Create a project** > **Direct Upload**
4. Name your project (e.g. `temperature`)
5. Use this exact name in your `.env`

---

## 4. Optional Variables

### `TIMEOUT_SECONDS`

Override the default timeout (in seconds) for network calls to InfluxDB and Cloudflare.

- Default: `30`
- Only needed if you experience slow or unreliable connections
- Applies to the InfluxDB query and the Wrangler deployment subprocess

### `DEPLOY_TIMEOUT_SECONDS`

Override the default timeout (in seconds) for the Wrangler deploy subprocess.

- Default: `120`
- Cloudflare Pages deployments involve uploading files and waiting for edge propagation, which can take longer than a simple database query
- Increase if you experience timeouts during deployment on slow connections

### `TEMP_MIN` / `TEMP_MAX`

Sanity-check bounds for temperature values. If a reading falls outside this range, a warning is logged but the value is still published.

- Defaults: `-50` and `80`
- Adjust if your sensor operates in extreme environments
