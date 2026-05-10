# TODO

## Open Items

### T-011: Manual QA for the deployed page (refreshed scope)

**Context:** `site/index.html` has accumulated several rendering surfaces that have never been visually verified in a browser: the original temperature display, the new 36h min/max line under the temperature, the pretty-printed device name in `#device-id` (e.g. `Gisebo 01` instead of `gisebo-01`), the dynamically-generated OG image at `site/og-<uuid>.png`, the OG/Twitter meta block, and the cache-busting fetch with `?t=Date.now()`. All have unit-test or static-validation coverage but none have a human-in-a-browser sign-off.

**Requirements:**
- Use the live `site/temperature.json` (or overwrite with a sample like `{"device_id":"gisebo-01","device_name":"Gisebo 01","temperature":22.5,"time":"2026-05-10T12:00:00+00:00","min_36h":18.0,"max_36h":27.3,"updated_at":"2026-05-10T12:00:01+00:00"}`)
- Serve locally: `cd site && python3 -m http.server 8000`
- In a desktop Chromium-family browser at `http://localhost:8000`, confirm: light blue (`#90c0de`) background, pretty-printed device name in `#device-id` above the temperature, large `#1c7bb7` temperature with `°C`, the new `<min> / <max> °C (36h)` line under the temperature in smaller white text, "Last updated" timestamp at the bottom, browser tab title equals `<temp>°C`
- Toggle DevTools mobile viewport (iPhone SE, Pixel 7), confirm `clamp()`-based font sizing scales without overflowing
- DevTools Network tab: confirm `temperature.json?t=<timestamp>` fires every 60s with a different `t=` value each time
- Rename `site/temperature.json`, wait 60s, confirm the page falls back to `--` for temperature, min, max, and the timestamp goes to `...`. Restore the file, confirm recovery within 60s
- Open the current `site/og-*.png` directly, confirm 1200×630 dimensions, pretty device label centred, temperature in big text, date below
- Validate the served HTML at https://validator.w3.org/nu/#textarea
- After the next production deploy, paste the public URL into https://www.opengraph.xyz/, confirm the preview shows the pretty device name in the title and the latest OG image renders

**Estimated Effort:** 1h

---

### T-012: Walk through SETUP.md and Docker quick-start on a fresh checkout

**Context:** `SETUP.md` was authored before Docker packaging and several env-var additions (`DEPLOY_TIMEOUT_SECONDS`, `SITE_URL`, `TEMP_MIN`, `TEMP_MAX`, `QUERY_RANGE`). The Docker path (`Dockerfile`, `docker-compose.yml`) is the recommended deployment but `SETUP.md` does not reference it. A new operator following SETUP.md alone will miss the Docker shape entirely.

**Requirements:**
- Clone the repo into a fresh directory on a machine with no prior project state
- Walk through SETUP.md from `cp .env.example .env` to a successful publish via the bare-metal path: `python -m venv .venv`, `source .venv/bin/activate`, `pip install -r requirements.txt`, populate `.env` with real credentials, `python publish_temperature.py`. Confirm a temperature value lands at the deployed Pages URL within 5 minutes
- Repeat via the Docker path: `docker compose build`, `docker compose run --rm publisher`. Confirm same outcome. Also confirm `docker history` and `docker run --rm <image> env` do not contain any token values
- Diff `.env.example` env vars against SETUP.md sections: every variable in `.env.example` must be documented somewhere in SETUP.md. Currently `QUERY_RANGE` is documented (added in section 4). Verify the others
- Add a short `## Docker quick-start` section near the top of `SETUP.md` that points operators at the README Docker section
- Confirm InfluxDB token-creation and Cloudflare API-token-scope screenshots/menu paths still match the current dashboards, fix any drift
- Commit fixes in the same PR

**Estimated Effort:** 1h

---

### T-024: Escape interpolated values in `_update_og_meta`

**Context:** `_update_og_meta()` in `publish_temperature.py` interpolates `data["temperature"]`, `data["device_name"]`, and `data["device_id"]` (via the device-name fallback chain) directly into HTML attribute values inside the OG/Twitter meta block. There is no escaping. The values originate in InfluxDB or operator-controlled `.env`, so the threat model is "operator self-foot-gun" or "anyone with InfluxDB write access", not external network input. The CSP at `site/_headers` would block any inline script execution at runtime, but malformed meta tags can still confuse social-media crawlers and break the OG preview entirely.

A `device_name` derived from a `DEVICE_ID` containing `"><script>alert(1)</script>` would currently produce a structurally-broken `<meta>` tag.

**Requirements:**
- In `publish_temperature.py`, in `_update_og_meta()` (around line 184 in the current file), wrap the four interpolated values (`og_title`, `og_desc`, both occurrences of `og_image`) in `html.escape(value, quote=True)` before they enter the f-string template
- `from html import escape` near the top of the module if not already imported (check the import block)
- Confirm the resulting attribute values still render correctly for normal inputs (`Gisebo 01`, `22.5`)

**Testing:**
- In `test_publish_temperature.py`, add a test that calls `_update_og_meta()` with `data["device_name"] = 'Foo"><script>alert(1)</script>'`, reads the rewritten `index.html`, and asserts: the `<meta>` tags are still well-formed (count tags via a simple parser), the literal `<script` substring is absent from inside any `content="..."` attribute, the dangerous chars appear escaped (`&quot;`, `&gt;`, `&lt;`)
- Add a test that the normal happy-path output is unchanged for an ASCII device name (regression guard)

**Estimated Effort:** 45min

---

### T-025: Reconcile CLAUDE.md drift about Flux query parameterization

**Context:** `CLAUDE.md` lines 7 and 31 both claim the project uses "parameterized Flux queries", but the actual code at `publish_temperature.py:200-228` uses f-string interpolation with `_validate_flux_value` allowlists and the `_parse_duration_env` regex validator. The drift was flagged during the T-021b review and during the T-021b commit message but never fixed. The wording misleads new contributors and any AI agent that reads CLAUDE.md as ground truth.

**Requirements:**
- In `CLAUDE.md`, change "Source: InfluxDB 2.x with parameterized Flux queries" (line 7) to something like "Source: InfluxDB 2.x with validated f-string Flux queries (allowlist-based input validation, see `_validate_flux_value` and `_parse_duration_env` in `publish_temperature.py`)"
- Same correction in the Project Conventions section (line 34): change "Python script using `influxdb-client` library with parameterized queries" to "Python script using `influxdb-client` library with validated f-string queries"
- The Flux query example at lines 22-29 still uses `params.measurement` style. Either update it to show the actual f-string form, or add a one-line note above it stating it is illustrative pseudocode, not the literal source

**Estimated Effort:** 15min

---

### T-026: Run the deferred security audit

**Context:** A structured hostile-attacker security audit was scoped earlier in the project but never executed. The intended deliverables: a `SECURITY_FLOW_TRACKER.md` enumerating every code path that handles untrusted input, secret material, or external system interaction, plus one `[REMEDIATION TASK: SEC-NNN]` entry per finding using the same shape as SEC-001 and SEC-002 in this file.

The seven flow areas to attack: (1) configuration and startup, (2) InfluxDB query construction, (3) static site generation including the OG image race window and the unescaped HTML rewrite (which T-024 partially addresses), (4) Cloudflare Pages deploy subprocess, (5) edge-served headers and CORS, (6) container runtime and image layers, (7) logging and operational hygiene including verifying SEC-001/SEC-002 rotation status.

This work should be claimed by a developer using the `/security-review` skill or a dedicated subagent briefed with this ticket.

**Requirements:**
- Create `/workspace/SECURITY_FLOW_TRACKER.md` with a checkbox for each of the seven flow areas
- Walk each area, brainstorming injection, race conditions, broken validation, side effects, and supply-chain risks
- For each finding, append a `[REMEDIATION TASK: SEC-NNN]` block to the `## Security Remediation` section of this file (numbering continues from SEC-002), include a `Reproduction:` subsection with the exact crafted input that triggers the flaw
- Flip each tracker checkbox to `[x]` after the area is fully attacked
- Update SEC-001 and SEC-002 status if the tokens have been rotated in the meantime

**Estimated Effort:** 4-6h, splittable per flow area

---

## Security Remediation (urgent)

The following entries were generated by an automated secret scan of `/workspace/.env` on 2026-05-10. The file is `.gitignore`d and absent from git history (verified via `git log -S` for both token prefixes), so the leak surface is local filesystem only. The risk is one accidental `git add -f .env` away from a public-repository leak, plus the fact that anyone with shell access to the publishing host can read the live tokens. Rotation is still warranted.

[REMEDIATION TASK: SEC-001]
- Status: TODO
- Location: `/workspace/.env` at Line `3`
- Secret Type: InfluxDB v2 API Token (89-char base64 with `==` padding, prefix `Jv6KW9wB...`, suffix `...Fd-g==`)
- Risk Level: Critical
- Required Action:
    1. Revoke the secret immediately at the InfluxDB UI: Load Data > API Tokens > select the token > Delete
    2. Generate a replacement token with the same scope (read-only on `home_assistant` bucket)
    3. Update `INFLUXDB_TOKEN` in `.env` on every host that runs `publish_temperature.py` (production cron host, any operator workstations)
    4. Confirm `git log --all -p -S "Jv6KW9wB"` returns empty, run BFG Repo-Cleaner or `git filter-repo` only if it does not (precaution, not currently required)

[REMEDIATION TASK: SEC-002]
- Status: TODO
- Location: `/workspace/.env` at Line `14`
- Secret Type: Cloudflare API Token (`cfut_` prefix, prefix `cfut_mqE0...`, suffix `...3dba`)
- Risk Level: Critical
- Required Action:
    1. Revoke the secret immediately at the Cloudflare dashboard: My Profile > API Tokens > select > Roll or Delete
    2. Generate a replacement token with the same scope (`Account: Cloudflare Pages: Edit`)
    3. Update `CLOUDFLARE_API_TOKEN` in `.env` on every host that runs `publish_temperature.py`
    4. Confirm `git log --all -p -S "cfut_mqE0"` returns empty, run BFG Repo-Cleaner or `git filter-repo` only if it does not (precaution, not currently required)

[REMEDIATION TASK: SEC-003]
- Status: TODO
- Location: `/workspace/publish_temperature.py` lines 37-43 (`_parse_int_env`) and lines 115-118 (`TIMEOUT_SECONDS`, `DEPLOY_TIMEOUT_SECONDS`, `TEMP_MIN`, `TEMP_MAX`)
- Vulnerability Type: Missing range validation on integer env vars (logic-level DoS, silent misconfiguration)
- Risk Level: Medium
- Required Action:
    1. Add explicit lower bounds in `_parse_int_env` (or per-call wrappers): `TIMEOUT_SECONDS` and `DEPLOY_TIMEOUT_SECONDS` must be `>= 1` (zero collapses `TIMEOUT_SECONDS * 1000` to no-timeout in the Influx client; negative values are silently accepted today)
    2. Validate `TEMP_MIN < TEMP_MAX` after both are parsed; exit with a clear error if not, since an inverted range silently makes every reading "out of range" while still publishing
    3. Add an upper bound (e.g. `<= 86400`) on the timeouts to prevent operator typos from creating multi-day blocking calls
    4. Cover with tests in `test_publish_temperature.py`: zero, negative, oversized, and inverted-range cases
- Reproduction:
    1. `TIMEOUT_SECONDS=0 python publish_temperature.py` -> Influx client receives `timeout=0`, treats it as no timeout, request can hang for the full TCP timeout instead of the operator-specified bound
    2. `TEMP_MIN=80 TEMP_MAX=-50 python publish_temperature.py` -> every reading logs `Temperature N outside expected range [80, -50]` but is still published; operator only notices via log volume

[REMEDIATION TASK: SEC-004]
- Status: TODO
- Location: `/workspace/publish_temperature.py` line 113 (`SITE_URL` derivation, no scheme/host validation)
- Vulnerability Type: Unvalidated URL flows into rewritten OG/Twitter meta tags (open-redirect-style metadata poisoning)
- Risk Level: Medium
- Required Action:
    1. After loading `SITE_URL`, validate scheme is `https://` (or explicitly `http://` for local dev), validate host is not empty, reject embedded credentials (`user:pass@`), reject newlines and control characters
    2. On failure, exit with a clear error before `_update_og_meta` runs
    3. Cover with a test that asserts `SITE_URL=javascript:alert(1)` fails fast at startup
- Reproduction:
    1. Set `SITE_URL=javascript:alert(1)` in `.env` (or shell env) and run `python publish_temperature.py`
    2. The script accepts it, generates `og_image = "javascript:alert(1)/og-<uuid>.png"`, and writes the resulting `<meta property="og:image" content="javascript:alert(1)/og-...png">` block into `site/index.html` and pushes it live
    3. Social-media crawlers and any consumer that follows `og:image` see an attacker-controlled URL

[REMEDIATION TASK: SEC-005]
- Status: TODO
- Location: `/workspace/publish_temperature.py` lines 131-134 (`_validate_flux_value`) and lines 208-228 (Flux f-string)
- Vulnerability Type: Insufficient Flux input validation, structural-character injection
- Risk Level: High (latent: attacker needs `.env` write today, but the validator is the only guard if any future surface accepts these values)
- Required Action:
    1. Tighten `_validate_flux_value` to an allowlist (e.g. `^[A-Za-z0-9_.\-]+$`) instead of a two-character denylist
    2. Apply the same allowlist to `MEASUREMENT`, `FIELD`, `DEVICE_ID` at startup (fail fast in module top-level alongside `REQUIRED_VARS`), not only inside `fetch_temperature()`
    3. Consider migrating the query to actual `influxdb-client` parameters via `Dialect`/parameterized queries, removing the f-string entirely (also resolves the T-025 docs drift permanently)
    4. Add tests for newline, paren, pipe, comma, and Flux-operator inputs
- Reproduction:
    1. Set `DEVICE_ID=$'foo\nbar'` (literal newline) in the shell environment and run `python publish_temperature.py`. The validator only checks for `"` and `\`, so the newline passes through. The interpolated query gains an extra line that breaks the intended `filter(...)` call boundary and either errors out at parse time or, with the right surrounding context, becomes a different pipeline.
    2. Set `DEVICE_ID='gisebo-01) |> limit(n: 0'` (no `"` and no `\`, only parens, pipe, colon, space). The validator passes, and the resulting f-string interpolation yields `r["device_id"] == "gisebo-01) |> limit(n: 0"` which is still inside the original quotes, so the immediate impact is just a broken filter that returns zero rows. But the same pattern combined with a future code path that passes these values through a different Flux context (without the surrounding quotes) becomes an actual injection, which is why an allowlist is the correct fix today rather than tomorrow.

[REMEDIATION TASK: SEC-006]
- Status: TODO
- Location: `/workspace/publish_temperature.py` lines 318-320 (`generate_og_image` glob/remove loop)
- Vulnerability Type: TOCTOU symlink-following on file removal (arbitrary-file-deletion within appuser scope)
- Risk Level: Medium
- Required Action:
    1. Before `os.remove(old)`, call `os.path.islink(old)` and skip (or refuse to run) if true
    2. Alternatively, use `os.unlink` with `os.lstat` first to confirm it is a regular file owned by the publisher
    3. Even better: write the new OG image first, then remove only files matching `og-*.png` whose realpath resolves under `SITE_DIR`
    4. Cover with a test that places a symlink at `site/og-evil.png -> /tmp/canary` and asserts the canary survives the run
- Reproduction:
    1. As any user with write access to `site/` (e.g. compromised `appuser` shell, shared host): `ln -s /tmp/canary site/og-attacker.png`
    2. `touch /tmp/canary`
    3. Run `python publish_temperature.py`
    4. The `glob('og-*.png')` returns `site/og-attacker.png`; `os.remove()` follows the symlink and deletes `/tmp/canary`. With path manipulation, any file the publisher UID can write becomes a deletion target

[REMEDIATION TASK: SEC-007]
- Status: TODO
- Location: `/workspace/publish_temperature.py` lines 369-372 (`temperature.json` write)
- Vulnerability Type: Non-atomic file write, observable partial state
- Risk Level: Low
- Required Action:
    1. Write to `temperature.json.tmp` first, fsync, then `os.replace()` onto `temperature.json`. `os.replace` is atomic on POSIX
    2. Apply the same pattern to `index.html` rewrite in `_update_og_meta` (lines 329, 362) for consistency
    3. Optional: also use atomic rename for the OG PNG so the page never loads a half-written PNG between `img.save` finish and the next `_update_og_meta`
- Reproduction:
    1. In one shell, run a tight loop: `while true; do curl -s file://$PWD/site/temperature.json | python3 -c 'import sys,json; json.load(sys.stdin)' || echo BROKEN; done`
    2. In another shell, repeatedly run `python publish_temperature.py`
    3. Occasionally observe `BROKEN` output, corresponding to a fetch that landed during the open-truncate-write window. The browser-side `fetch().json()` rejects the same way and the page flashes `--`

[REMEDIATION TASK: SEC-008]
- Status: TODO
- Location: `/workspace/publish_temperature.py` line 113 (`SITE_URL.rstrip("/")`) and lines 339, 345-346, 352 (interpolation into OG meta)
- Vulnerability Type: Path-traversal segments in `SITE_URL` flow unvalidated into OG meta
- Risk Level: Low (related to SEC-004; filed separately because the fix is path-component validation rather than scheme validation)
- Required Action:
    1. Parse `SITE_URL` with `urllib.parse.urlsplit`, reject non-empty `path` (or normalise it via `posixpath.normpath` and reject if it contains `..`), reject non-empty `query`/`fragment`
    2. Reconstruct from validated components before storing
    3. Cover with tests for `..`, double-slash, percent-encoded slash inputs
- Reproduction:
    1. Set `SITE_URL=https://temperature.pages.dev/../evil` and run `python publish_temperature.py`
    2. The script only does `.rstrip("/")`, so the value passes through unchanged
    3. `og_image` becomes `https://temperature.pages.dev/../evil/og-<uuid>.png` and `og:url` becomes `https://temperature.pages.dev/../evil/`
    4. Some social-media crawlers normalise the path, others follow it literally and miss the OG image entirely; either way the meta block is no longer trustworthy

[REMEDIATION TASK: SEC-009]
- Status: TODO
- Location: `/workspace/publish_temperature.py` lines 375-384 (`subprocess.run(["npx", "wrangler", ...])`) and `SETUP.md` bare-metal path
- Vulnerability Type: Unpinned `npx` resolution (supply-chain), no integrity verification
- Risk Level: Medium
- Required Action:
    1. Bare-metal path: document and require a project-local `package.json` and `package-lock.json` pinning `wrangler@4.86.0` (matching the Dockerfile), and invoke as `npx --no-install wrangler ...` so an unexpected install fails loudly
    2. Alternatively, remove `npx` and call the wrangler binary directly from a known path
    3. Container path is already pinned via `npm install -g wrangler@4.86.0` in the Dockerfile; verify this stays in lockstep with bare-metal
    4. Optionally pin a wrangler binary checksum in CI
- Reproduction:
    1. On a fresh bare-metal host: clear local `node_modules`, then run `python publish_temperature.py`
    2. `npx wrangler` resolves the latest `wrangler` from the public npm registry, downloads it, executes it
    3. A compromised version of `wrangler` (or any of its transitive deps) gains code execution with the operator's `CLOUDFLARE_API_TOKEN` and `INFLUXDB_TOKEN` in its environment

[REMEDIATION TASK: SEC-010]
- Status: TODO
- Location: `/workspace/publish_temperature.py` lines 375-384 (subprocess inherits full env)
- Vulnerability Type: Excess secret exposure to third-party subprocess
- Risk Level: Medium
- Required Action:
    1. Build an explicit `env` dict containing only what wrangler needs (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `PATH`, `HOME`)
    2. Pass it as `subprocess.run(..., env=clean_env)`
    3. This denies the wrangler process visibility into `INFLUXDB_TOKEN` and any unrelated env vars (including any that may be added in future)
    4. Cover with a test that monkeypatches `subprocess.run` and asserts the `env` kwarg is set and excludes `INFLUXDB_TOKEN`
- Reproduction:
    1. Run `publish_temperature.py` with both tokens set
    2. While the wrangler subprocess is running, in another shell as the same UID: `cat /proc/$(pgrep -n wrangler)/environ | tr '\0' '\n' | grep -E 'INFLUXDB_TOKEN|CLOUDFLARE_API_TOKEN'`
    3. Both tokens are visible. Wrangler only legitimately needs the Cloudflare one; the InfluxDB token is gratuitously exposed

[REMEDIATION TASK: SEC-011]
- Status: TODO
- Location: `/workspace/site/_headers` line 6 (CSP), `/workspace/site/index.html` lines 90-145 (inline `<script>`)
- Vulnerability Type: CSP weakened by `'unsafe-inline'` in `script-src`; missing `base-uri`/`object-src`/`form-action`
- Risk Level: Medium
- Required Action:
    1. Move the inline `<script>` block in `site/index.html` to a separate `site/app.js` file
    2. Replace `'unsafe-inline'` in CSP `script-src` with `'self'` (drop `'unsafe-inline'` entirely; the inline `<style>` keeps its `'unsafe-inline'` in `style-src` until that is also externalised)
    3. Add `base-uri 'none'`, `object-src 'none'`, `form-action 'none'` to the CSP
    4. Confirm via `curl -I https://temperature.pages.dev/` after deploy
- Reproduction:
    1. Suppose any of SEC-004 / SEC-005 / T-024 lands an attacker-controlled string into `index.html`. Today the CSP `script-src 'self' 'unsafe-inline'` does not block an injected inline script; the only thing keeping the page safe from XSS-via-meta is the existing T-024 escape work
    2. Concretely: `curl -I https://temperature.pages.dev/ | grep -i content-security-policy` shows `script-src 'self' 'unsafe-inline'`. With `'unsafe-inline'` present, any injected `<script>...</script>` executes

[REMEDIATION TASK: SEC-012]
- Status: TODO
- Location: `/workspace/site/_headers` line 14 (`Access-Control-Allow-Origin: *` on `/temperature.json`)
- Vulnerability Type: Wide-open CORS on the data endpoint
- Risk Level: Low (sensitivity of the temperature reading is low today, but the reading is a side-channel for occupancy/heating patterns)
- Required Action:
    1. If no third-party site needs to fetch `/temperature.json`, remove the `Access-Control-Allow-Origin` line entirely (the page itself is same-origin and does not need CORS)
    2. If a specific consumer is expected, set the header to that explicit origin instead of `*`
    3. Document the decision in `_headers` as an inline comment
- Reproduction:
    1. From any browser, on any third-party origin, run: `fetch('https://temperature.pages.dev/temperature.json').then(r => r.json()).then(console.log)`
    2. The full payload is returned, including timestamps. A malicious page can build a long-running occupancy graph for the sensor location with no consent

[REMEDIATION TASK: SEC-013]
- Status: TODO
- Location: `/workspace/Dockerfile` line 1 (`FROM python:3.11-slim`)
- Vulnerability Type: Floating base-image tag (supply-chain reproducibility)
- Risk Level: Low
- Required Action:
    1. Pin to a digest: `FROM python:3.11-slim@sha256:<digest>`
    2. Look up the current digest via `docker pull python:3.11-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim`
    3. Add a renovate / dependabot rule (or a quarterly manual bump) to refresh the digest
    4. Apply the same pattern to any future base image
- Reproduction:
    1. Today: `docker compose build` pulls `python:3.11-slim` (whatever Docker Hub currently serves)
    2. Tomorrow Docker Hub re-tags `python:3.11-slim` to a freshly built (potentially compromised, potentially just behaviour-changed) image with different sha256
    3. The next CI run silently picks up the new image, no diff in source control reflects the change

[REMEDIATION TASK: SEC-014]
- Status: TODO
- Location: `/workspace/docker-compose.yml` (no hardening directives)
- Vulnerability Type: Missing container hardening (capabilities, read-only FS, no-new-privileges, resource limits)
- Risk Level: Low
- Required Action:
    1. Add to the `publisher` service: `read_only: true`, `tmpfs: ["/tmp", "/app/site"]` (the publisher writes to `site/`, which needs to remain writable; consider a named volume for `site/` if persistence matters)
    2. Add `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`
    3. Add `mem_limit: 256m`, `pids_limit: 100` as a starting point, tune from observed usage
    4. Confirm the publisher still completes a full run after each change
- Reproduction:
    1. `docker compose run --rm publisher bash -c 'cat /proc/self/status | grep CapEff'`
    2. CapEff shows non-zero capabilities; the container has more privileges than the workload requires
    3. `docker compose run --rm publisher bash -c 'echo malicious > /etc/cron.d/evil && ls -la /etc/cron.d/evil'`
    4. Inside the container, `appuser` cannot write to `/etc/cron.d` (good, root-owned), but a future privilege-escalation bug in any dependency would not be blocked by `no-new-privileges` because the option is not set

[REMEDIATION TASK: SEC-015]
- Status: TODO
- Location: `/workspace/publish_temperature.py` lines 401-403 (`logging.error(f"Failed: {e}", exc_info=True)`)
- Vulnerability Type: Potential secret leakage via exception logging
- Risk Level: Medium
- Required Action:
    1. Wrap the catch-all in a sanitiser that strips `Authorization:` headers and bearer-token-shaped substrings from the rendered exception/traceback before logging
    2. Or: catch known InfluxDB and `requests` exceptions explicitly, log only the type and a short summary, and reserve `exc_info=True` for unexpected types under a debug-only flag
    3. Confirm by simulating an Influx 401: temporarily point `INFLUXDB_URL` at a host that returns 401 with the request echoed, run, and inspect the log
    4. Cover with a test that raises a synthetic exception whose `__str__` contains `Bearer FAKE_TOKEN` and asserts the rendered log does not contain `FAKE_TOKEN`
- Reproduction:
    1. Configure `INFLUXDB_URL=http://127.0.0.1:9999` (no listener) and a valid-looking `INFLUXDB_TOKEN`
    2. Run `python publish_temperature.py`
    3. The connection error traceback can include the request URL and, depending on `urllib3` / `influxdb-client` version, the full `Authorization: Token <value>` header in the exception chain
    4. The traceback is written via `logging.error(..., exc_info=True)` to stdout/stderr, which cron forwards via mail and Docker captures into `docker logs` / journald

[REMEDIATION TASK: SEC-016]
- Status: TODO
- Location: `/workspace/.env` lines 3 and 14 (re-verification of SEC-001 and SEC-002 rotation)
- Vulnerability Type: Critical-secret rotation overdue
- Risk Level: Critical (inherits from SEC-001/SEC-002)
- Required Action:
    1. Confirm SEC-001 (InfluxDB token, prefix `Jv6KW9wB...`, suffix `...Fd-g==`) has been revoked at the InfluxDB UI; current `/workspace/.env` line 3 still matches the prefix/suffix documented in SEC-001, so revocation has not happened yet
    2. Confirm SEC-002 (Cloudflare token, prefix `cfut_mqE0...`, suffix `...3dba`) has been rolled at the Cloudflare dashboard; current `/workspace/.env` line 14 still matches the prefix/suffix documented in SEC-002, so revocation has not happened yet
    3. After both providers confirm revocation and replacement tokens are deployed, flip SEC-001 and SEC-002 status to Done and remove this entry
    4. Add a calendar reminder to revisit in 90 days regardless
- Reproduction:
    1. Compare `head -c 12 < <(grep ^INFLUXDB_TOKEN= /workspace/.env | cut -d= -f2)` against the prefix in SEC-001 (`Jv6KW9wB`); they match today, proving the original leaked token is still live in the file (and presumably still accepted by InfluxDB)
    2. Compare `head -c 12 < <(grep ^CLOUDFLARE_API_TOKEN= /workspace/.env | cut -d= -f2)` against the prefix in SEC-002 (`cfut_mqE0`); they match today, same conclusion for Cloudflare
    3. (Do NOT echo the full token values when running these checks; the prefix is sufficient to confirm non-rotation)

---

## Completed (archived)

All tickets T-001 through T-023 are implemented, tested, and committed. Summary table preserved for reference and to support cross-references from open tickets:

| ID | Title | Status |
|----|-------|--------|
| T-001 | Secure subprocess calls (shlex) | Done, then superseded by Cloudflare migration |
| T-002 | Parameterize Flux query | Done, replaced by allowlist-validated f-string interpolation, 5 tests |
| T-003 | Add timeouts to blocking calls | Done, 4 tests |
| T-004 | Pin deps and env validation | Done, 4 tests |
| T-005a | Temperature value validation | Done, 6 tests, extracted to `_validate_last_value` helper in T-022a |
| T-005b | Structured logging | Done, 2 tests |
| T-006 | Remote .tmp cleanup | Done, then superseded by Cloudflare migration |
| T-007a/b | Static index.html + JS data fetch | Done, manual QA still tracked under T-011 |
| T-007c | Cloudflare Pages publish | Done, 5 tests |
| T-007d | Update env vars for Cloudflare | Done, 6 tests |
| T-008 | Setup documentation | Done, walkthrough still tracked under T-012 |
| T-009 | Exception handling in `main()` | Done, `try/except` for `CalledProcessError` and generic `Exception`, both `sys.exit(1)`, 2 tests |
| T-010 | Separate `DEPLOY_TIMEOUT_SECONDS` | Done, defaults to 120s, separate from `TIMEOUT_SECONDS`, 2 tests |
| T-013 | Module-level int parsing with clear errors | Done, `_parse_int_env` helper handles `TIMEOUT_SECONDS`, `DEPLOY_TIMEOUT_SECONDS`, `TEMP_MIN`, `TEMP_MAX`, 3 tests |
| T-014 | Validate `SITE_DIR` exists at startup | Done, exits with the resolved path on missing directory, 1 test |
| T-015 | Cache-bust `temperature.json` | Done, both `?t=Date.now()` query string and `Cache-Control: no-cache, no-store, must-revalidate` rule in `site/_headers` |
| T-016 | Docker packaging | Done, `Dockerfile` (python:3.11-slim, Node.js, wrangler@4.86.0, DejaVu fonts, non-root `appuser`), `docker-compose.yml` (`env_file: .env`), `.dockerignore` |
| T-017 | OpenGraph meta + dynamic OG image | Done, Pillow pinned to 9.4.0, `generate_og_image()` writes `og-<uuid>.png` per run with cache-busting filename, `_update_og_meta()` rewrites the OG/Twitter meta block in place |
| T-018 | Security headers via `_headers` | Done, full CSP, HSTS with preload, X-Frame-Options DENY, COOP/CORP, plus per-path no-cache for `/temperature.json` |
| T-019 | README dev workflow + Docker section | Done, README has Development, Docker, updated Project Structure, Pillow + Docker in Dependencies |
| T-020 | Configurable QUERY_RANGE | Done, `_parse_duration_env` helper with regex `^-\d+[smhdw]$`, `QUERY_RANGE` defaults to `-30d`, 5 tests, documented in `.env.example`, `SETUP.md`, README |
| T-021a | Remove HOST_FILTER from code | Done, churning Docker container ID was breaking queries on every container restart, 2 regression tests |
| T-021b | Remove HOST_FILTER from docs | Done, scrubbed from `.env.example`, README, SETUP.md, CLAUDE.md |
| T-022a | Compute 36h min/max in fetch | Done, multi-yield Flux query, `_table_yield_name` dispatcher, `min_36h`/`max_36h` fields in JSON payload, 5 tests |
| T-022b | Display 36h min/max on page | Done, new `#min-max` div with CSS sized between temperature and timestamp, JS reads new fields with `--` fallback |
| T-023 | Pretty-print sensor name | Done, `_pretty_device_name` helper (e.g. `gisebo-01` to `Gisebo 01`), `device_name` field in JSON, wired into OG image label, OG meta rewriter, page JS, 9 tests |

## Stats

- **Open tickets:** 2 (T-011 and T-012, both manual QA, deferred to operator)
- **Security remediation pending:** 16 (SEC-001 and SEC-002 from the original .env scan, SEC-003 through SEC-016 from the T-026 audit; SEC-001/SEC-002/SEC-016 require operator action at provider consoles, the rest require code changes)
- **Completed tickets:** 28 (T-001 through T-025, plus T-026 audit deliverables)
- **Test suite:** 62 passing
- **Estimated remaining effort:** manual QA (T-011, T-012) is operator-blocked; the SEC-003 through SEC-015 remediation backlog is the next major work surface and should be prioritised by Risk Level (High first, then Medium, then Low)
