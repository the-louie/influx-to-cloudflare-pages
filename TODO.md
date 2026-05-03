# TODO

## Open Items

### T-009: Add exception handling with structured logging in main()

**Context:** T-005b specified "Log exceptions from `subprocess.CalledProcessError` and `InfluxDBClient` failures at `logging.error` level," and the checkbox was marked complete, but this was never implemented. Currently in `publish_temperature.py`, if the Wrangler deploy fails (`subprocess.CalledProcessError`) or the InfluxDB client throws, the raw traceback goes to stderr with no structured log entry. Under cron, this traceback may be lost entirely.

**Requirements:**
- [x] In `main()` in `publish_temperature.py` (line 122), wrap the `fetch_temperature()` and `publish(data)` calls in a `try/except` block
- [x] Catch `subprocess.CalledProcessError` and log with `logging.error(f"Deploy failed: {e}")`
- [x] Catch `Exception` broadly as a fallback and log with `logging.error(f"Unexpected error: {e}", exc_info=True)`
- [x] Re-raise or `sys.exit(1)` after logging so the cron job still reports a non-zero exit code

**Testing:**
- [x] In `test_publish_temperature.py`, monkeypatch `subprocess.run` to raise `CalledProcessError`, call `main()`, assert log contains "Deploy failed" at ERROR level
- [x] Monkeypatch `InfluxDBClient` to raise `ConnectionError`, call `main()`, assert log contains "Unexpected error" at ERROR level
- [x] Assert `sys.exit(1)` is called in both cases

**Estimated Effort:** 1h

---

### T-010: Increase default timeout for Wrangler deploy

**Context:** `TIMEOUT_SECONDS` (default 30) is shared between the InfluxDB query and the Wrangler deploy subprocess. A Cloudflare Pages deployment involves uploading files and waiting for edge propagation, which can exceed 30 seconds on slow connections or during Cloudflare incidents. The InfluxDB query, by contrast, should complete in under a second.

**Requirements:**
- [x] In `publish_temperature.py`, add a separate `DEPLOY_TIMEOUT_SECONDS = int(os.environ.get("DEPLOY_TIMEOUT_SECONDS", "120"))` on the line after `TIMEOUT_SECONDS`
- [x] Change the `timeout=` kwarg in the Wrangler `subprocess.run` call (line 118) from `TIMEOUT_SECONDS` to `DEPLOY_TIMEOUT_SECONDS`
- [x] Keep `TIMEOUT_SECONDS` for the InfluxDB client timeout (line 72), it remains appropriate there
- [x] Add `# DEPLOY_TIMEOUT_SECONDS=120` to `.env.example` under the existing timeout comment
- [x] Add a `DEPLOY_TIMEOUT_SECONDS` entry to section 4 of `SETUP.md`

**Testing:**
- [x] In `test_publish_temperature.py`, monkeypatch `subprocess.run`, call `publish()`, assert timeout is 120 (not 30)
- [x] Set `DEPLOY_TIMEOUT_SECONDS=60` in env, reimport, call `publish()`, assert timeout is 60
- [x] Assert InfluxDB client timeout remains `TIMEOUT_SECONDS * 1000` (unchanged)

**Estimated Effort:** 1h

---

### T-011: Manual QA for temperature display page

**Context:** The `site/index.html` page was built and committed but never visually tested in a browser. All code-level requirements are met per automated tests, but layout, responsiveness, and usability need manual verification.

**Requirements:**
- [ ] Create a sample `site/temperature.json` with realistic test data:
  ```json
  {"device_id":"gisebo-01","temperature":22.5,"time":"2026-05-02T12:00:00+00:00","updated_at":"2026-05-02T12:00:01+00:00"}
  ```
- [ ] Serve the site locally: `cd site && python3 -m http.server 8000`
- [ ] Open `http://localhost:8000` in a desktop browser and verify:
  - Light blue background (`#90c0de`)
  - Device ID label visible above temperature
  - Temperature displayed large, centered, with °C suffix
  - "Last updated" timestamp visible below
- [ ] Open Chrome DevTools, toggle mobile viewport (iPhone SE, Pixel 7), verify responsive font sizing works via `clamp()`
- [ ] Delete `temperature.json` while page is open, wait 60 seconds, verify page shows "--" fallback
- [ ] Validate HTML at https://validator.w3.org by pasting the source

**Estimated Effort:** 30min

---

### T-012: Verify SETUP.md accuracy on a fresh checkout

**Context:** `SETUP.md` was written based on known UI paths in InfluxDB and Cloudflare, but the instructions were never followed end-to-end on a fresh machine. Menu paths or UI labels may have changed.

**Requirements:**
- [ ] Clone the repo to a clean directory (or use a fresh virtual environment)
- [ ] Follow every step in `SETUP.md` from `cp .env.example .env` through running the script
- [ ] Verify every env var in `.env.example` has a matching entry in `SETUP.md`
- [ ] Fix any incorrect UI paths, missing steps, or unclear instructions found during the walkthrough

**Estimated Effort:** 1h

---

### T-013: Move TEMP_MIN/TEMP_MAX parsing to module level and validate

**Context:** Found during code review (see `__doc/code_reviews/20260503-0900_full_codebase_review.md`). Lines 88-89 of `publish_temperature.py` parse `TEMP_MIN` and `TEMP_MAX` from environment on every `fetch_temperature()` call. If a non-integer value is set (e.g. `TEMP_MIN=abc`), it raises `ValueError` on every cron run with a confusing "Failed: invalid literal for int()" message. The same issue applies to `TIMEOUT_SECONDS` and `DEPLOY_TIMEOUT_SECONDS` on lines 48-49.

**Requirements:**
- [ ] Move `temp_min` and `temp_max` parsing to module level, below `DEPLOY_TIMEOUT_SECONDS`
- [ ] Wrap all `int()` conversions for optional env vars in a helper or try/except that produces a clear error naming the variable
- [ ] Remove the `int()` calls from inside `fetch_temperature()`

**Testing:**
- [ ] Set `TEMP_MIN=abc` in env, import module, assert clear error message mentioning `TEMP_MIN`
- [ ] Set `TIMEOUT_SECONDS=fast`, assert clear error message mentioning `TIMEOUT_SECONDS`

**Estimated Effort:** 1h

---

### T-014: Validate SITE_DIR exists at startup

**Context:** Found during code review. `SITE_DIR` on line 51 of `publish_temperature.py` assumes the `site/` directory exists relative to the script. If invoked from an unexpected location or if `site/` was deleted, `publish()` raises `FileNotFoundError` with no helpful context.

**Requirements:**
- [ ] After `SITE_DIR` is defined (line 51), add a check: if `not SITE_DIR.is_dir()`, log an error and `sys.exit(1)`
- [ ] The error message should include the resolved path so the operator knows where to look

**Testing:**
- [ ] Monkeypatch `SITE_DIR` to a non-existent path, import module, assert `sys.exit(1)` and error message contains the path

**Estimated Effort:** 30min

---

### T-015: Add Cloudflare CDN cache busting for temperature.json

**Context:** Found during code review. The `index.html` fetches `temperature.json` every 60 seconds, but Cloudflare's CDN may serve a stale cached version. There is no cache-busting query parameter and no `Cache-Control` header configuration. This means the page could show stale temperature data even after a fresh deploy.

**Requirements:**
- [ ] Option A: In `index.html`, append a timestamp query parameter to the fetch URL: `'temperature.json?t=' + Date.now()`
- [ ] Option B: Create a `site/_headers` file with `Cache-Control: no-cache` for `temperature.json` (Cloudflare Pages supports this)
- [ ] Choose one approach and implement it

**Testing:**
- [ ] If Option A: verify the fetch URL in `index.html` includes a query parameter
- [ ] If Option B: verify `site/_headers` exists and contains the correct rule
- [ ] Deploy and confirm the JSON file is not stale after update

**Estimated Effort:** 30min

---

### T-016: Package as Docker container with docker-compose.yml

**Context:** The project currently requires manual setup of Python, Node.js/npx, and pip dependencies. Packaging it as a Docker container makes deployment reproducible and simplifies cron setup on any host. The container needs both Python (for the script) and Node.js (for `npx wrangler`).

**Requirements:**
- [ ] Create a `Dockerfile` in the project root:
  - Use `python:3.11-slim` as the base image
  - Install Node.js (via `apt-get install -y nodejs npm` or use a multi-stage build with `node:20-slim`)
  - Copy `requirements.txt` and run `pip install --no-cache-dir -r requirements.txt`
  - Copy `publish_temperature.py` and the `site/` directory into the image
  - Set the working directory to `/app`
  - Default command: `python publish_temperature.py`
  - Do NOT copy `.env` into the image (secrets must not be baked into the image)
- [ ] Create a `docker-compose.yml` in the project root:
  ```yaml
  services:
    publisher:
      build: .
      env_file:
        - .env
      volumes:
        - ./site:/app/site
  ```
  - The `env_file` directive reads all variables from `.env` automatically, no changes needed to the Python code since `os.environ` sees them
  - The volume mount for `site/` ensures `temperature.json` is written to the host (optional, useful for debugging)
- [ ] Add a `.dockerignore` file to exclude `.env`, `.venv/`, `__pycache__/`, `.git/`, `__doc/`, `*.pyc`, and `test_publish_temperature.py` from the build context
- [ ] Verify the container runs correctly: `docker compose up --build`
- [ ] Verify the container exits cleanly with code 0 on success and code 1 on failure
- [ ] Document the Docker usage in `README.md`:
  - `docker compose up --build` for a single run
  - Cron example: `*/5 * * * * cd /path/to/project && docker compose up --build 2>&1 >> /var/log/temperature.log`
  - Or use `docker compose up -d` with `restart: "no"` and an external cron/systemd timer
- [ ] Note on `npx wrangler`: the first run inside the container will download Wrangler since it is not globally installed. To speed up repeated runs, either `RUN npm install -g wrangler` in the Dockerfile, or use a named volume for the npm cache

**Testing:**
- [ ] `docker compose build` succeeds without errors
- [ ] `docker compose run --rm publisher` with a valid `.env` fetches data and deploys (or logs the expected error if InfluxDB/Cloudflare are unreachable)
- [ ] `docker compose run --rm publisher` without `.env` exits with code 1 and prints the missing variables message
- [ ] Verify no secrets are in the built image: `docker history <image>` and `docker run --rm <image> env` should not contain tokens

**Estimated Effort:** 1-2h

---

### T-017: Add OpenGraph meta tags and generate dynamic OG image

**Context:** When the page URL is shared on social media, messaging apps, or link previews, there are no OpenGraph tags, so it shows a blank or generic preview. The page should include full OG meta tags and a dynamically generated image that displays the current temperature in the same visual style as the web page (light blue background, large bold number).

**Requirements:**
- [ ] Add the following OpenGraph meta tags to `<head>` in `site/index.html`:
  ```html
  <meta property="og:title" content="Temperature">
  <meta property="og:description" content="Current temperature reading">
  <meta property="og:type" content="website">
  <meta property="og:image" content="og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  ```
  Also add Twitter Card tags for broader compatibility:
  ```html
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="Temperature">
  <meta name="twitter:description" content="Current temperature reading">
  <meta name="twitter:image" content="og-image.png">
  ```
- [ ] Generate `site/og-image.png` (1200x630px) in `publish_temperature.py` using the Pillow library:
  - Add `Pillow` to `requirements.txt` (pin to current version)
  - Background: `#90c0de` (same light blue as the page)
  - Temperature value centered, bold, large font (~200px), color `#1c7bb7`
  - Include `°C` suffix at the same size as the number
  - Device ID label above in smaller white text (~40px), color `rgba(255,255,255,0.7)` approximated as `#ffffffb3` or `(255,255,255,178)`
  - Use a bundled font: include `Arial` or a free alternative like `DejaVu Sans` (available on most Linux systems at `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`), or bundle a `.ttf` in the repo under `fonts/`
  - Generate the image in `publish()` before the Wrangler deploy, so it is included in the deployed site
- [ ] The OG image must be regenerated on every publish run so it always shows the current temperature
- [ ] Update the JS in `index.html` to also update the `og:description` meta tag content with the current temperature value (note: this only affects in-page reads, crawlers see the static HTML)

**Testing:**
- [ ] Run the script, verify `site/og-image.png` is created with correct dimensions (1200x630)
- [ ] Open the image, verify it shows the temperature value on the light blue background
- [ ] Paste the deployed URL into https://www.opengraph.xyz/ or the Facebook Sharing Debugger and verify the preview shows the OG image and correct title/description
- [ ] Add `site/og-image.png` to `.gitignore` (it is a generated artifact like `temperature.json`)

**Estimated Effort:** 2h

---

### T-018: Add security headers via Cloudflare Pages _headers file

**Context:** The site currently serves no security headers. Cloudflare Pages supports a `_headers` file in the site directory that applies custom HTTP response headers to all deployed assets. Since this is a simple static site with inline CSS, inline JS, and a single `fetch()` call to same-origin `temperature.json`, the Content Security Policy can be strict.

**Requirements:**
- [ ] Create `site/_headers` with the following content (one rule block applying to all paths):
  ```
  /*
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    Referrer-Policy: no-referrer
    Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()
    Content-Security-Policy: default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; font-src 'none'; frame-ancestors 'none'
    Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
    X-DNS-Prefetch-Control: off
    Cross-Origin-Opener-Policy: same-origin
    Cross-Origin-Resource-Policy: same-origin
  ```
  Header explanations for the team:
  - `X-Content-Type-Options: nosniff` prevents the browser from guessing MIME types, reducing XSS risk
  - `X-Frame-Options: DENY` prevents the page from being embedded in iframes (clickjacking protection)
  - `Referrer-Policy: no-referrer` prevents sending the URL to third parties when following links
  - `Permissions-Policy` disables browser features the site does not use (camera, mic, location, FLoC)
  - `Content-Security-Policy` controls which resources the browser is allowed to load:
    - `default-src 'none'` blocks everything by default
    - `script-src 'self' 'unsafe-inline'` allows the inline `<script>` in index.html (required since the JS is inline, not a separate file)
    - `style-src 'self' 'unsafe-inline'` allows the inline `<style>` block
    - `img-src 'self'` allows same-origin images (needed for og-image.png if T-017 lands)
    - `connect-src 'self'` allows the `fetch('temperature.json')` call
    - `frame-ancestors 'none'` reinforces the X-Frame-Options DENY
  - `Strict-Transport-Security` enforces HTTPS for 1 year with subdomain coverage
  - `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` isolate the page from cross-origin interactions
- [ ] Add a separate rule for `temperature.json` to prevent caching (also addresses T-015):
  ```
  /temperature.json
    Cache-Control: no-cache, no-store, must-revalidate
    Access-Control-Allow-Origin: *
  ```
  - `no-cache, no-store, must-revalidate` ensures Cloudflare's CDN and the browser always fetch fresh data
  - `Access-Control-Allow-Origin: *` allows the JSON to be consumed by other tools if needed
- [ ] The `_headers` file must NOT be in `.gitignore` since it is a static config file, not a generated artifact
- [ ] Deploy and verify headers are applied

**Testing:**
- [ ] Deploy the site with the `_headers` file and verify headers using `curl -I <site-url>`
- [ ] Verify `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, and `Strict-Transport-Security` are present in the response
- [ ] Verify `temperature.json` returns `Cache-Control: no-cache, no-store, must-revalidate`
- [ ] Open the page in Chrome DevTools > Network tab, confirm no CSP violations in the Console
- [ ] Scan the deployed URL at https://securityheaders.com/ and aim for an A or A+ grade

**Estimated Effort:** 1h

---

### T-019: Add developer workflow and Docker instructions to README

**Context:** The README currently covers quick start and cron setup for operators, but has no guidance for developers contributing to the project. It also lacks Docker instructions even though T-016 plans Docker packaging. Developers need to know how to set up a dev environment, run tests, modify the HTML page, rebuild the Docker image, and deploy changes.

**Requirements:**
- [ ] Add a "Development" section to `README.md` after "Running Tests" with:
  - How to set up a local dev environment (clone, venv, install deps, copy .env)
  - How to preview the page locally: `cd site && python3 -m http.server 8000` with a sample `temperature.json`
  - How to run the test suite and what to expect (number of tests, what they cover)
  - How to add a new test: which file, naming conventions, the `_import_fresh()` pattern explained
  - How to modify `site/index.html` and verify changes locally before deploying
- [ ] Add a "Docker" section to `README.md` after "Cron Setup" with:
  - How to build: `docker compose build`
  - How to run once: `docker compose run --rm publisher`
  - How to run via cron: `*/5 * * * * cd /path/to/project && docker compose run --rm publisher >> /var/log/temperature.log 2>&1`
  - How to rebuild after code changes: `docker compose build --no-cache`
  - Note that `.env` is read via `env_file` in `docker-compose.yml`, not baked into the image
  - Note that `site/` is volume-mounted so `temperature.json` and `og-image.png` are visible on the host for debugging
- [ ] Update the "Project Structure" tree to include new files: `site/_headers`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- [ ] Update the "Dependencies" section to mention Pillow and Docker as optional
- [ ] Update the test count from 35 to the current number (39)

**Estimated Effort:** 1h

---

### T-020: Add configurable query range to prevent full-bucket scans

**Context:** Found during code review (see `__doc/code_reviews/20260503-1000_implementation_batch_review.md`). The Flux query uses `range(start: 0)` which scans from epoch. For a bucket accumulating years of data across many devices, this forces InfluxDB to process the entire series before `last()` can aggregate. This may cause slow queries or timeouts as the bucket grows.

**Requirements:**
- [ ] Add a `QUERY_RANGE` env var (default: `-30d`) to `.env.example` and the `_parse_int_env` section
- [ ] Use it in the Flux query: `range(start: {QUERY_RANGE})`
- [ ] Validate the format (must start with `-` and end with `s`, `m`, `h`, `d`, or `w`)
- [ ] Document in `SETUP.md` that this controls how far back the query looks, and that `-30d` is generous for a sensor that reports every few minutes

**Estimated Effort:** 30min

---

## Completed (archived)

All original tickets T-001 through T-008 have been implemented, tested, and committed. The following is a summary for reference:

| ID | Title | Status |
|----|-------|--------|
| T-001 | Secure subprocess calls (shlex) | Done, then superseded by Cloudflare migration |
| T-002 | Parameterize Flux query | Done, 5 tests |
| T-003 | Add timeouts to blocking calls | Done, 4 tests |
| T-004 | Pin deps and env validation | Done, 4 tests |
| T-005a | Temperature value validation | Done, 6 tests |
| T-005b | Structured logging | Done, 2 tests (exception logging gap found, see T-009) |
| T-006 | Remote .tmp cleanup | Done, then superseded by Cloudflare migration |
| T-007a | Static index.html | Done, manual QA pending (see T-011) |
| T-007b | Inline JS for data fetch | Done, manual QA pending (see T-011) |
| T-007c | Cloudflare Pages publish | Done, 5 tests |
| T-007d | Update env vars for Cloudflare | Done, 6 tests |
| T-008 | Setup documentation | Done, walkthrough pending (see T-012) |

## Stats

- **Open tickets:** 9 (2 manual QA, 4 hardening/security, 1 packaging, 1 feature, 1 documentation)
- **Completed tickets:** 13 (T-001 through T-010)
- **Estimated remaining effort:** 11h
