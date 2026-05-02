# TODO

## Security

### T-001: Secure subprocess calls in publish() against shell injection

**Context:** The `publish()` function in `publish_temperature.py` (lines 61,83) constructs SSH and SCP commands using `REMOTE_PATH` and `REMOTE_USER`/`REMOTE_HOST` from environment variables. SSH concatenates trailing arguments into a single string and executes via the remote shell, so shell metacharacters in `REMOTE_PATH` (semicolons, backticks, `$()`, spaces) are interpreted on the remote host, creating a command injection vector.

**Requirements:**
- [x] Add `import shlex` to the imports block at the top of `publish_temperature.py`
- [x] On line 79, replace `["ssh", remote_dest, "mv", remote_tmp, REMOTE_PATH]` with `["ssh", remote_dest, f"mv {shlex.quote(remote_tmp)} {shlex.quote(REMOTE_PATH)}"]`
- [x] On line 74, wrap the SCP destination: `f"{remote_dest}:{shlex.quote(remote_tmp)}"`
- [x] Verify that the `finally` block on line 82 still correctly cleans up `local_tmp`

**Testing:**
- [x] Create `test_publish_temperature.py` in the project root
- [x] Monkeypatch `subprocess.run`, call `publish()` with `REMOTE_PATH` containing shell metacharacters (e.g. `/tmp/foo; echo pwned`), assert args contain `shlex.quote()`-wrapped values
- [x] Test with spaces in path (e.g. `/var/www/my data/temp.json`), assert correct quoting
- [x] Test with single quotes in path (e.g. `/var/www/it's/temp.json`), assert proper escaping

**Estimated Effort:** 1,2h

---

### T-002: Parameterize Flux query to prevent injection in fetch_temperature()

**Context:** `fetch_temperature()` in `publish_temperature.py` (lines 34,58) builds its Flux query via f-string interpolation. If any `.env` value contains a double-quote, the query structure changes, creating an injection risk. The `influxdb-client` library supports parameterized Flux queries via `params={}` on `query_api().query()` since version 1.18.0.

**Requirements:**
- [x] Verify installed `influxdb-client` version >= 1.18.0, update pin in `requirements.txt` if needed
- [x] Rewrite the query string to use `params` references instead of f-string interpolation
- [x] Validate bucket name against regex `^[a-zA-Z0-9_-]+$` if `from(bucket:)` does not support params
- [x] Pass params dict to `client.query_api().query(query, params=params)`
- [x] Query string should be a plain triple-quoted string (no `f` prefix) with `params.measurement`, `params.field`, `params.device_id`, `params.host_filter`

**Testing:**
- [x] Monkeypatch `InfluxDBClient` and `query_api().query()`, call `fetch_temperature()`, assert `params` kwarg contains all expected keys
- [x] Assert query string does NOT contain f-string interpolated values
- [x] Set `DEVICE_ID` to `") |> drop(`, assert injected code appears inside params value, not in the query string
- [x] If bucket validation is required, test `valid_bucket` (pass) and `bad"; drop` (reject)

**Estimated Effort:** 1,2h

---

### T-003: Add timeouts to all blocking calls and document HTTPS

**Context:** Three blocking calls in `publish_temperature.py` lack timeouts: InfluxDB query (line 46), SCP subprocess (line 73), SSH subprocess (line 78). Under cron, a hung connection produces zombie processes. The `.env.example` defaults to `http://` with no HTTPS guidance.

**Requirements:**
- [x] Add `TIMEOUT_SECONDS` env var to `.env.example` with default comment value of `30`
- [x] In `publish_temperature.py`, read `TIMEOUT_SECONDS = int(os.environ.get("TIMEOUT_SECONDS", "30"))`
- [x] Add `timeout=TIMEOUT_SECONDS` to SCP `subprocess.run()` (line 73)
- [x] Add `timeout=TIMEOUT_SECONDS` to SSH `subprocess.run()` (line 78)
- [x] Set timeout on `InfluxDBClient` constructor (`timeout=TIMEOUT_SECONDS * 1000`, client accepts milliseconds)
- [x] Add HTTPS comment in `.env.example` above `INFLUXDB_URL`

**Testing:**
- [x] Monkeypatch `subprocess.run`, call `publish()`, assert both calls received `timeout` kwarg
- [x] Monkeypatch `InfluxDBClient`, assert constructed with timeout parameter
- [x] Set `TIMEOUT_SECONDS=5`, verify propagation to all three call sites
- [x] Omit `TIMEOUT_SECONDS`, verify default of 30

**Estimated Effort:** 1,2h

---

## Operational

### T-004: Pin dependency versions and add startup env variable validation

**Context:** `requirements.txt` lists dependencies without version pins. `publish_temperature.py` lines 17,31 use bare `os.environ["KEY"]` lookups that produce unhelpful `KeyError` if `.env` is missing or incomplete.

**Requirements:**
- [x] Run `pip freeze | grep -iE "influxdb-client|python-dotenv"` to get current versions
- [x] Update `requirements.txt` to pin exact versions (e.g. `influxdb-client==1.38.0`)
- [x] After `load_dotenv()` on line 14, add validation: define `REQUIRED_VARS` list, compute `missing`, print to stderr and `sys.exit(1)` if any missing
- [x] Error message must list all missing vars and say `Copy .env.example to .env and fill in all values.`

**Testing:**
- [x] Assert `requirements.txt` lines match pattern `package==X.Y.Z`
- [x] Clear all env vars, call validation, assert exit code 1 and stderr contains `Missing required environment variables`
- [x] Remove only `REMOTE_HOST`, assert error message includes that variable name
- [x] All vars present, assert no error

**Estimated Effort:** 1,2h

---

### T-005a: Add temperature value validation in fetch_temperature()

**Context:** `fetch_temperature()` places `record.get_value()` directly into the JSON payload without checking type or range. If InfluxDB returns `None`, `NaN`, `Inf`, or a non-numeric type, the published JSON is malformed.

**Requirements:**
- [x] Add `import math` to imports in `publish_temperature.py`
- [x] After getting the value from `record.get_value()`, extract to a local variable and validate: reject if `value is None`, `not isinstance(value, (int, float))`, or `not math.isfinite(value)`
- [x] On rejection, log a warning with the actual value and return `None`
- [x] Add optional `TEMP_MIN`/`TEMP_MAX` env vars (default -50 and 80), log warning if out of range but still publish

**Testing:**
- [x] Mock `record.get_value()` returning `float('nan')`, assert `fetch_temperature()` returns `None`
- [x] Test with `float('inf')`, assert `None`
- [x] Test with string `"twenty"`, assert `None`
- [x] Test with `None`, assert `None`
- [x] Test with `22.5`, assert returned dict contains `"temperature": 22.5`

**Estimated Effort:** 1,2h

---

### T-005b: Replace print() with structured logging

**Context:** Lines 89 and 93 in `publish_temperature.py` use `print()` for output. Under cron, stdout is discarded by default, making diagnostics impossible without explicit redirection.

**Requirements:**
- [x] Add `import logging` to imports
- [x] At the top of `main()`, configure `logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)`
- [x] Replace `print("No data returned from InfluxDB", file=sys.stderr)` with `logging.error("No data returned from InfluxDB")`
- [x] Replace `print(f"Published: ...")` with `logging.info(f"Published: ...")`
- [x] Log `subprocess.CalledProcessError` and `InfluxDBClient` failures at `logging.error` level

**Testing:**
- [x] Using `caplog` (pytest), call `main()` with mocked success path, assert log contains `Published:` at INFO level
- [x] Call `main()` with mocked failure (no data), assert log contains `No data returned` at ERROR level
- [x] Assert log messages contain timestamps

**Estimated Effort:** 1,2h

---

### T-006: Add remote .tmp file cleanup on SSH mv failure

**Context:** If SCP succeeds but `mv` fails in `publish()`, the `.tmp` file remains on the remote host. Repeated cron failures accumulate orphan temp files. *Depends on T-001.*

**Requirements:**
- [x] Confirm `import shlex` is present (from T-001)
- [x] Wrap SSH `mv` call in `try/except subprocess.CalledProcessError`
- [x] In except: issue cleanup `subprocess.run(["ssh", remote_dest, f"rm -f {shlex.quote(remote_tmp)}"], timeout=TIMEOUT_SECONDS)` without `check=True`
- [x] Re-raise original `CalledProcessError` after cleanup
- [x] Log warning about the cleanup attempt

**Testing:**
- [x] Monkeypatch `subprocess.run`: SCP succeeds, SSH `mv` raises `CalledProcessError`, assert third call is `rm -f` targeting `.tmp` path
- [x] Assert original `CalledProcessError` is re-raised
- [x] Test both SCP and cleanup `rm` fail, assert original SCP error propagates
- [x] Test SCP and `mv` both succeed, assert no cleanup call

**Estimated Effort:** 1,2h

---

## Feature

### T-007a: Build static index.html for temperature display page

**Context:** The project is moving from SSH/SCP publishing to Cloudflare Pages. This ticket creates the front-end: a single self-contained `index.html` with all HTML, CSS, and JS inline, inspired by the vecka.nu design (large centered number on a light blue background). The page will display one device's temperature, but the structure should accommodate multiple devices in the future.

**Requirements:**
- [x] Create `site/index.html` in the project root
- [x] Full-viewport layout (`height: 100vh`), no scroll, background `#90c0de`
- [x] Flexbox centering (`display: flex; flex-direction: column; justify-content: center; align-items: center`)
- [x] Device ID label above the temperature in smaller muted text (~20px, color `rgba(255,255,255,0.7)`)
- [x] Temperature number: bold, responsive font size `clamp(120px, 25vw, 300px)`, color `#1c7bb7`
- [x] `°C` suffix in smaller text (~80px)
- [x] "Last updated" timestamp below in muted text (~16px)
- [x] Font: Arial, Helvetica, sans-serif
- [x] `<meta name="viewport">` tag for mobile
- [x] `<title>` element that JS will update with current temperature

**Testing:**
- [ ] Open `site/index.html` in a browser with a sample `temperature.json` alongside it, verify layout matches spec
- [ ] Test on mobile viewport (Chrome DevTools), verify responsive font sizing
- [ ] Validate HTML with W3C validator or similar

**Estimated Effort:** 1,2h

---

### T-007b: Add inline JavaScript to fetch and display temperature data

**Context:** The `index.html` (from T-007a) needs an inline `<script>` that fetches `temperature.json` from the same origin, updates the DOM, and auto-refreshes. The JSON format matches the existing `publish_temperature.py` output with fields `device_id`, `temperature`, `time`, and `updated_at`.

**Requirements:**
- [x] Add inline `<script>` in `index.html` that fetches `temperature.json` on page load
- [x] Update DOM elements: device ID label, temperature number, and last-updated timestamp
- [x] Update `<title>` to current temperature (e.g. `22.5°C`)
- [x] Auto-refresh via `setInterval` every 60 seconds
- [x] Handle fetch errors gracefully (show "..." or "N/A" if data unavailable)

**Testing:**
- [ ] Create a sample `site/temperature.json` with test data, serve with `python -m http.server`, verify page loads and displays correctly
- [ ] Verify auto-refresh by modifying `temperature.json` while page is open
- [ ] Test with missing/malformed JSON, verify graceful fallback

**Estimated Effort:** 1,2h

---

### T-007c: Rewrite publish() for Cloudflare Pages deployment

**Context:** The current `publish()` in `publish_temperature.py` uses SCP/SSH to deploy a JSON file. This ticket replaces that with Cloudflare Pages deployment using the Wrangler CLI. The `site/` directory contains `index.html` (from T-007a/b) and the script writes `temperature.json` into it before deploying.

**Requirements:**
- [x] Rewrite `publish()` to write `temperature.json` into the `site/` directory
- [x] Deploy using `subprocess.run(["npx", "wrangler", "pages", "deploy", "site/", "--project-name", CLOUDFLARE_PROJECT_NAME], check=True)`
- [x] Set env vars `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` (Wrangler reads these from environment automatically)
- [x] Remove SCP/SSH subprocess calls and `shlex` import (no longer needed)
- [x] Keep `timeout=TIMEOUT_SECONDS` on the subprocess call if T-003 has landed

**Testing:**
- [x] Monkeypatch `subprocess.run`, call `publish()`, assert Wrangler command was invoked with correct project name and directory
- [x] Assert `site/temperature.json` was written with correct content before deployment
- [x] Assert no SCP/SSH calls remain

**Estimated Effort:** 1,2h

---

### T-007d: Update env vars and config for Cloudflare Pages

**Context:** With the move to Cloudflare Pages (T-007c), the SSH/SCP env vars are no longer needed and must be replaced with Cloudflare-specific configuration.

**Requirements:**
- [x] Remove `REMOTE_USER`, `REMOTE_HOST`, `REMOTE_PATH` from `.env.example`
- [x] Add to `.env.example`: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_PROJECT_NAME` with descriptive comments
- [x] Update `REQUIRED_VARS` list in `publish_temperature.py` (from T-004) to replace SSH vars with Cloudflare vars
- [x] Remove `REMOTE_USER`, `REMOTE_HOST`, `REMOTE_PATH` variable assignments from the module-level config block
- [x] Add `CLOUDFLARE_PROJECT_NAME = os.environ["CLOUDFLARE_PROJECT_NAME"]`

**Testing:**
- [x] Assert `.env.example` contains all three Cloudflare vars
- [x] Assert `.env.example` does NOT contain `REMOTE_USER`, `REMOTE_HOST`, or `REMOTE_PATH`
- [x] Run env var validation with missing `CLOUDFLARE_PROJECT_NAME`, assert error message

**Estimated Effort:** 1,2h

---

## Documentation

### T-008: Add step-by-step setup tutorial for each .env value

**Context:** New operators need guidance on where to find each configuration value. This ticket creates a `SETUP.md` with a walkthrough for every `.env` variable, including screenshots/paths in the InfluxDB and Cloudflare UIs. *Should be updated after T-007 lands.*

**Requirements:**
- [x] Create `SETUP.md` in the project root
- [x] Quick-start checklist at the top: `cp .env.example .env`, fill in values, run `python publish_temperature.py`
- [x] Section 1, InfluxDB connection: document `INFLUXDB_URL` (default port 8086, HTTPS for remote), `INFLUXDB_TOKEN` (UI path: Load Data > API Tokens > Generate Read-Only Token), `INFLUXDB_ORG` (UI path: Settings > Organization), `INFLUXDB_BUCKET` (UI path: Load Data > Buckets)
- [x] Section 2, Flux query filters: document `MEASUREMENT`, `FIELD`, `DEVICE_ID`, `HOST_FILTER` with instructions to find each in the Data Explorer UI
- [x] Section 3, Cloudflare Pages: document `CLOUDFLARE_API_TOKEN` (dashboard path: My Profile > API Tokens), `CLOUDFLARE_ACCOUNT_ID` (dashboard sidebar or `wrangler whoami`), `CLOUDFLARE_PROJECT_NAME` (Pages > Create project)
- [x] Section 4, Optional: `TIMEOUT_SECONDS`, `TEMP_MIN`/`TEMP_MAX`
- [x] Update `.env.example` with inline comments referencing `SETUP.md` sections

**Testing:**
- [ ] Follow the tutorial on a fresh checkout, verify all steps are accurate and complete
- [ ] Verify every env var in `.env.example` has a corresponding entry in `SETUP.md`

**Estimated Effort:** 1,2h

---

## Stats

- **Total tickets:** 11 (3 security, 4 operational, 3 feature, 1 documentation)
- **Dependency chain:** T-006 depends on T-001, T-007b depends on T-007a, T-007c depends on T-007a/b, T-007d depends on T-007c, T-008 should follow T-007
- **Estimated total effort:** 12,20h
- **Completed:** All tickets (T-001 through T-008)
