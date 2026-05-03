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

- **Open tickets:** 5 (2 manual QA, 3 hardening from code review)
- **Completed tickets:** 13 (T-001 through T-010)
- **Estimated remaining effort:** 5.5h
