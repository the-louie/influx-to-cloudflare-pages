# Code Review: Full Codebase Audit

**Date:** 2026-05-03
**Reviewer:** Senior Staff Engineer / Security Researcher
**Scope:** All new and modified code across 20 commits (054b66a..f61c033)

---

## Summary

The project is an InfluxDB-to-Cloudflare-Pages publisher. It fetches a temperature reading from InfluxDB via a parameterized Flux query, validates it, writes it to a JSON file, and deploys a static site to Cloudflare Pages using the Wrangler CLI. The codebase is 143 lines of production Python, 105 lines of HTML/CSS/JS, and 530 lines of tests covering 35 cases.

Overall quality is solid for a small operational utility. The code is readable, well-structured, and the test coverage is thorough. The findings below are mostly edge-case hardening and minor structural observations, not fundamental flaws.

---

## Critical Findings

| Issue | Severity | Description | Suggested Fix |
|:------|:---------|:------------|:--------------|
| TEMP_MIN/TEMP_MAX parsed on every call | Low | Lines 88-89 of `publish_temperature.py` parse `TEMP_MIN` and `TEMP_MAX` from the environment inside `fetch_temperature()` on every invocation. If a non-integer value is set (e.g. `TEMP_MIN=abc`), it will raise `ValueError` on every cron run, caught by the generic handler as "Failed" with a traceback that does not clearly identify the config error. | Parse these at module level alongside other env vars. Add them to a validation block or use a try/except with a clear error message. |
| Module-level validation uses `print()` not `logging` | Low | Lines 26-31 use `print(..., file=sys.stderr)` for the missing-vars error, while the rest of the codebase uses `logging`. This is intentional since `logging.basicConfig()` has not been called yet at module scope, so it is not a bug. However, it means this specific error path produces a different output format than all other errors, which could confuse log parsers. | Acceptable as-is. If a future change moves validation into `main()`, switch to `logging.error()`. |
| No validation of `TIMEOUT_SECONDS` or `DEPLOY_TIMEOUT_SECONDS` | Low | Lines 48-49 call `int()` on the env var value. If someone sets `TIMEOUT_SECONDS=fast`, the `ValueError` is caught by the generic handler in `main()`, but the error message says "Failed: invalid literal for int()" with no indication which variable is wrong. | Wrap in a try/except at parse time with a clear message, or validate alongside `REQUIRED_VARS`. |
| Flux query still uses f-string for bucket | Info | Line 58 uses `f"""` because `from(bucket:)` does not support Flux params. The bucket is validated by regex on line 55. This is documented and correct, but a developer reading the code might wonder why the query uses an f-string when the TODO says "no f prefix." The regex guard makes this safe. | No change needed. The code is correct. |
| `SITE_DIR` not validated | Low | Line 51 assumes `site/` exists relative to the script. If the script is invoked from a different directory via cron, or if `site/` is missing, `open(json_path, "w")` on line 107 raises `FileNotFoundError`. The generic handler logs it, but the message is not helpful. | Add a startup check: `if not SITE_DIR.is_dir(): logging.error(...); sys.exit(1)`. |
| `temperature.json` cache busting | Info | The `index.html` fetches `temperature.json` every 60 seconds, but Cloudflare's CDN may serve a stale cached version. There is no cache-busting query parameter and no `Cache-Control` header configuration. | Consider adding `?t=` + timestamp to the fetch URL, or configure Cloudflare cache rules for the JSON file via `_headers` file in the site directory. |

---

## Structural Observations (non-critical)

1. **Test helper `_import_fresh()` re-imports the module on every test.** This is necessary because of module-level env var parsing, but it makes tests slower and harder to reason about. This is an acceptable tradeoff for a small codebase.

2. **No `__all__` or explicit exports.** The module exposes all module-level constants as public. This is fine for a standalone script.

3. **`re` import is used only for one regex check.** A simpler approach would be `all(c.isalnum() or c in "_-" for c in INFLUXDB_BUCKET)`, avoiding the import entirely. This is cosmetic.

4. **The HTML page uses `var` instead of `const`/`let`.** The JavaScript in `index.html` uses ES5 style (`var`, `function` declarations). This works everywhere but is unusual for 2026. Not a bug.

---

## Remediation

### Items fixed immediately: none

All findings are low severity. The two items worth addressing are the TEMP_MIN/TEMP_MAX parse location and the SITE_DIR validation. I will add these to `TODO.md`.

### Items added to TODO.md
