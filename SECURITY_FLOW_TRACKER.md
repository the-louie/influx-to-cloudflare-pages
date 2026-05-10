# Security Flow Tracker (T-026)

Hostile-attacker walkthrough of the Influx-to-Cloudflare-Pages publisher.
Findings are filed as `[REMEDIATION TASK: SEC-NNN]` blocks in
`/workspace/TODO.md` under `## Security Remediation (urgent)`. Numbering
continues from SEC-002, so the first new finding here is SEC-003.

Each area below is checked off after a full pass. The summary records
what attack categories were considered and which findings (if any) were
filed.

## Flow Areas

- [x] (1) Configuration and startup (env loading, `_parse_int_env`,
  `_parse_duration_env`, `REQUIRED_VARS`, `SITE_DIR` validation)

  Considered: missing-var bypass, type-confusion via numeric parsing,
  duration regex bypass, unbounded integer parsing (DoS via giant
  timeout/range, negative ints accepted by `_parse_int_env`),
  unicode/whitespace tricks in env, `.env` precedence vs shell env,
  attacker-writable `.env`, `SITE_DIR` symlink/race, non-existent
  `SITE_DIR` exit-message disclosure, `SITE_URL` default not validated
  for scheme.

  Findings:
  - SEC-003: `_parse_int_env` accepts arbitrary signed integers; no
    lower/upper bound on `TIMEOUT_SECONDS`, `DEPLOY_TIMEOUT_SECONDS`,
    `TEMP_MIN`, `TEMP_MAX`. A negative or zero deploy timeout silently
    breaks runs; `TEMP_MIN > TEMP_MAX` makes every reading "out of range"
    but still publishes; `TIMEOUT_SECONDS=0` collapses to
    `0 * 1000 = 0` ms which the Influx client treats as no timeout.
  - SEC-004: `SITE_URL` is not validated for scheme. A value like
    `javascript:alert(1)` or `//evil.example.com` is accepted and
    interpolated directly into rewritten OG `<meta>` tags, producing
    attacker-controlled `og:image` / `og:url` URLs that social-media
    crawlers will fetch.

- [x] (2) InfluxDB query construction (`_validate_flux_value`, bucket
  regex, f-string interpolation, multi-yield handling,
  `_table_yield_name`, `_validate_last_value`)

  Considered: Flux injection via MEASUREMENT/FIELD/DEVICE_ID, bucket
  regex completeness, newline injection (the validator rejects `"` and
  `\` but allows `\n`, `)`, `}`, `|>`, `,`), yield-name spoofing via a
  table named `last`/`min_36h`/`max_36h` from a hostile bucket,
  multi-yield ordering when first yield is empty, `_validate_last_value`
  out-of-range still being published, integer overflow in temperature.

  Findings:
  - SEC-005: `_validate_flux_value` only blocks `"` and `\`. Newlines,
    parens, pipes, commas, and Flux operators all pass. A `DEVICE_ID`
    of `x) |> drop(columns: ["_value"]) |> filter(fn: (r) => true` (no
    `"` or `\`) injects a complete Flux clause into every interpolated
    position and silently exfiltrates or drops data. The `.env` file
    is the trust source today, but the same validator is the only
    guard if any future code path takes these values from another
    surface (HTTP, message queue, secondary config file, multi-tenant
    deployment).

- [x] (3) Static site generation (`generate_og_image` glob/remove/save
  race, `_update_og_meta` unescaped HTML rewrite which T-024 partially
  addresses, JSON write atomicity, `SITE_URL` path-traversal handling)

  Considered: TOCTOU between `glob` and `os.remove`, symlink in
  `site/og-*.png` causing arbitrary-file deletion, JSON write
  non-atomic (page sees half-written file), `SITE_URL` containing
  `..` or trailing path segments, `og_filename` fixed pattern but
  attacker could plant `og-evil.png` symlink before run. T-024 already
  covers HTML escaping in `_update_og_meta`; not re-filed.

  Findings:
  - SEC-006: `generate_og_image` does `glob('og-*.png')` then
    `os.remove()` on each match, with no symlink/realpath check. An
    attacker with write access to `SITE_DIR` (e.g. shared host, leaked
    appuser shell, future multi-tenant scenario) can plant
    `site/og-evil.png` as a symlink to `/etc/passwd` or any
    appuser-writable file, and the next publish run will delete the
    symlink target.
  - SEC-007: `temperature.json` is written non-atomically via
    `open(..., 'w')` and `json.dump()`. A page-load that races the
    write sees a truncated or zero-byte JSON file and `fetch().json()`
    rejects, briefly flashing `--`. Worse, if the publisher process
    is killed mid-write (OOM, SIGTERM during cron, container stop),
    the file stays corrupted until the next successful run.
  - SEC-008: `SITE_URL` is `.rstrip("/")` only. A value like
    `https://temperature.pages.dev/../evil` or `https://x.example/foo`
    flows directly into `og:url` and `og:image` content attributes
    with no path-component validation. Combined with SEC-004 (no
    scheme check) the OG meta block becomes attacker-steerable.

- [x] (4) Cloudflare Pages deploy subprocess (`subprocess.run` argv,
  `--commit-dirty`, secret exposure in process listing, `npx wrangler`
  resolution)

  Considered: argv shape (list form, no `shell=True`, safe), PATH
  hijack of `npx`, `npx wrangler` re-resolves the package each run
  (network dependency + supply-chain), `--commit-dirty=true` semantics,
  `CLOUDFLARE_API_TOKEN` lives in env so visible to any process under
  same UID via `/proc/<pid>/environ`, no integrity check on the
  wrangler binary, no audit log of what was uploaded.

  Findings:
  - SEC-009: `npx wrangler` is invoked without a lockfile or
    integrity check. `npx` resolves `wrangler` from the local
    `node_modules` if present, otherwise downloads and executes the
    latest matching version from the public npm registry. The
    Dockerfile pins `wrangler@4.86.0` globally so the container path
    is fine, but bare-metal operators (per SETUP.md) get whatever
    `npx wrangler` resolves, with no SRI or version pin.
  - SEC-010: `CLOUDFLARE_API_TOKEN` and `INFLUXDB_TOKEN` are passed
    to the wrangler subprocess via inherited environment. Any other
    process running as the same UID can read them from
    `/proc/<pid>/environ`. The script does not scrub the env before
    `subprocess.run`, so wrangler (a third-party binary) sees both
    tokens even though it only needs `CLOUDFLARE_API_TOKEN` and
    `CLOUDFLARE_ACCOUNT_ID`.

- [x] (5) Edge-served headers and CORS (`site/_headers`, CSP source
  list, CORS posture for `/temperature.json`, no-cache rules, HSTS
  preload safety)

  Considered: CSP `'unsafe-inline'` in script-src, missing
  `object-src`/`base-uri`, `Access-Control-Allow-Origin: *` on the
  data file, HSTS `preload` commitment, missing
  `Cross-Origin-Embedder-Policy`, lack of report-uri.

  Findings:
  - SEC-011: CSP allows `script-src 'self' 'unsafe-inline'`. The
    inline `<script>` in `site/index.html` requires `'unsafe-inline'`
    today, which neutralises CSP as an XSS mitigation. Combined with
    the unescaped HTML rewrite (T-024) and the unvalidated `SITE_URL`
    (SEC-004), an attacker who controls any of those inputs has no
    CSP backstop. Recommend moving the inline script to an external
    file plus a `'sha256-...'` hash, dropping `'unsafe-inline'`, and
    adding `base-uri 'none'`, `object-src 'none'`, `form-action
    'none'`.
  - SEC-012: `Access-Control-Allow-Origin: *` is set on
    `/temperature.json` with no need stated. Any third-party site can
    fetch and embed the live reading; if the data ever becomes
    sensitive (location, occupancy inference) this is a wide-open
    leak. If cross-origin embed is not required, the header should
    be removed.

- [x] (6) Container runtime and image layers (`Dockerfile`,
  `docker-compose.yml`, `.dockerignore`, non-root `appuser` posture,
  bake-in via `--build-arg`, base image freshness)

  Considered: secret bake-in via `COPY .` (mitigated by `.dockerignore`
  listing `.env`), `.env` mounted via `env_file`, base image
  `python:3.11-slim` floating tag (no digest pin), `apt-get install`
  with no version pins, `npm install -g wrangler@4.86.0` pinned to a
  specific version (good), Docker layer caching of npm registry data,
  non-root `appuser` UID 1000 (good), missing `--no-new-privileges`,
  no read-only root FS, no resource limits.

  Findings:
  - SEC-013: Base image `python:3.11-slim` is referenced by tag, not
    digest. A future re-pull (CI, host rebuild) silently picks up a
    different image. Recommend `python:3.11-slim@sha256:<digest>` and
    a renovate/dependabot policy to bump it.
  - SEC-014: `docker-compose.yml` has no `read_only: true`,
    `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, or
    `pids_limit`/`mem_limit`. A compromised wrangler or Pillow
    dependency runs with full container capabilities and can write
    anywhere in the filesystem.

- [x] (7) Logging and operational hygiene (`logging.error
  exc_info=True` content, secret leakage in logs, SEC-001/SEC-002
  rotation status verification)

  Considered: `exc_info=True` traceback content (does the Influx
  client put the token in `__repr__` of an exception? does an HTTP
  401 traceback include the Authorization header?), `print(...,
  file=sys.stderr)` for missing-vars uses var name only (good),
  `f"Invalid integer for {name}: {raw!r}"` echoes raw value to stderr
  (TEMP_MIN/TEMP_MAX/TIMEOUT_SECONDS are not secrets), `f"Invalid
  duration for {name}: {raw!r}"` same, `logging.info(f"Published:
  {data['temperature']}°C at {data['time']}")` no secret, no log
  rotation policy, no PII concerns currently.

  SEC-001/SEC-002 rotation verification: the token prefixes
  documented in TODO.md SEC-001 (`Jv6KW9wB...`/`...Fd-g==`) and
  SEC-002 (`cfut_mqE0...`/`...3dba`) still match the values currently
  in `/workspace/.env`. Rotation has NOT happened. SEC-001 and
  SEC-002 remain Status: TODO. (Verified by inspecting `.env` line 3
  and line 14; values are not echoed here.)

  Findings:
  - SEC-015: `main()` uses `logging.error(f"Failed: {e}",
    exc_info=True)` as a catch-all. The InfluxDB client and the
    `requests`/`urllib3` stack underneath it can include the
    Authorization header, the full request URL with query string,
    and the raw query body in exception messages or
    `BaseException.args`. A network failure mid-request (or a wrong
    org/bucket triggering a 401) can write the bearer token into the
    log. Logs end up in cron mail, container `docker logs`, and
    journald, all of which are commonly forwarded.
  - SEC-016: SEC-001 and SEC-002 rotation is incomplete. The
    InfluxDB and Cloudflare tokens documented as critical in
    SEC-001/SEC-002 still match the current `/workspace/.env`
    values. Both Status fields should remain TODO until rotation is
    confirmed at the provider consoles, and the operator should be
    re-pinged.

## Out-of-scope / already tracked

- HTML escaping in `_update_og_meta` is being addressed by T-024 and
  is intentionally NOT re-filed here.
- SEC-001 (InfluxDB token leaked locally) and SEC-002 (Cloudflare
  token leaked locally) already exist and remain valid; SEC-016
  records that rotation has not yet completed.
