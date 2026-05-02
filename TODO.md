# TODO

## Open Items

### T-009: Add exception handling with structured logging in main()

**Context:** T-005b specified "Log exceptions from `subprocess.CalledProcessError` and `InfluxDBClient` failures at `logging.error` level," and the checkbox was marked complete, but this was never implemented. Currently in `publish_temperature.py`, if the Wrangler deploy fails (`subprocess.CalledProcessError`) or the InfluxDB client throws, the raw traceback goes to stderr with no structured log entry. Under cron, this traceback may be lost entirely.

**Requirements:**
- [ ] In `main()` in `publish_temperature.py` (line 122), wrap the `fetch_temperature()` and `publish(data)` calls in a `try/except` block
- [ ] Catch `subprocess.CalledProcessError` and log with `logging.error(f"Deploy failed: {e}")`
- [ ] Catch `Exception` broadly as a fallback and log with `logging.error(f"Unexpected error: {e}", exc_info=True)`
- [ ] Re-raise or `sys.exit(1)` after logging so the cron job still reports a non-zero exit code

**Testing:**
- [ ] In `test_publish_temperature.py`, monkeypatch `subprocess.run` to raise `CalledProcessError`, call `main()`, assert log contains "Deploy failed" at ERROR level
- [ ] Monkeypatch `InfluxDBClient` to raise `ConnectionError`, call `main()`, assert log contains "Unexpected error" at ERROR level
- [ ] Assert `sys.exit(1)` is called in both cases

**Estimated Effort:** 1h

---

### T-010: Increase default timeout for Wrangler deploy

**Context:** `TIMEOUT_SECONDS` (default 30) is shared between the InfluxDB query and the Wrangler deploy subprocess. A Cloudflare Pages deployment involves uploading files and waiting for edge propagation, which can exceed 30 seconds on slow connections or during Cloudflare incidents. The InfluxDB query, by contrast, should complete in under a second.

**Requirements:**
- [ ] In `publish_temperature.py`, add a separate `DEPLOY_TIMEOUT_SECONDS = int(os.environ.get("DEPLOY_TIMEOUT_SECONDS", "120"))` on the line after `TIMEOUT_SECONDS`
- [ ] Change the `timeout=` kwarg in the Wrangler `subprocess.run` call (line 118) from `TIMEOUT_SECONDS` to `DEPLOY_TIMEOUT_SECONDS`
- [ ] Keep `TIMEOUT_SECONDS` for the InfluxDB client timeout (line 72), it remains appropriate there
- [ ] Add `# DEPLOY_TIMEOUT_SECONDS=120` to `.env.example` under the existing timeout comment
- [ ] Add a `DEPLOY_TIMEOUT_SECONDS` entry to section 4 of `SETUP.md`

**Testing:**
- [ ] In `test_publish_temperature.py`, monkeypatch `subprocess.run`, call `publish()`, assert timeout is 120 (not 30)
- [ ] Set `DEPLOY_TIMEOUT_SECONDS=60` in env, reimport, call `publish()`, assert timeout is 60
- [ ] Assert InfluxDB client timeout remains `TIMEOUT_SECONDS * 1000` (unchanged)

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

- **Open tickets:** 4 (1 bug fix, 1 improvement, 2 manual verification)
- **Completed tickets:** 11
- **Estimated remaining effort:** 3.5h
