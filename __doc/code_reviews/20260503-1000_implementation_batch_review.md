# Code Review: Implementation Batch (T-013 through T-019)

**Date:** 2026-05-03
**Reviewer:** Senior Staff Engineer / Security Researcher
**Scope:** All code changes from T-013, T-014, T-015, T-016, T-017, T-018, T-019

---

## Summary

This batch introduced six functional changes and one documentation update: module-level env var parsing with validation (T-013), SITE_DIR existence check (T-014), browser-side cache busting (T-015), Docker packaging (T-016), OpenGraph image generation (T-017), Cloudflare security headers (T-018), and README expansion (T-019). The codebase is now 197 lines of production Python, 117 lines of HTML, 39 passing tests, and a complete Docker packaging layer.

---

## Critical Findings

| Issue | Severity | Description | Suggested Fix |
|:------|:---------|:------------|:--------------|
| Docker runs as root | Medium | The Dockerfile does not create a non-root user. The container runs as root by default, which is unnecessary for this workload and violates container security best practices. | Add `RUN useradd -r appuser` and `USER appuser` before the CMD instruction. |
| `range(start: 0)` scans all data | Low | The Flux query now scans from epoch to present. For a bucket with years of data across many devices, the `last()` aggregation must process the entire series. This may cause slow queries or timeouts as the bucket grows. A bounded range like `range(start: -30d)` would be safer while still tolerating long gaps. | Consider adding a configurable `QUERY_RANGE` env var defaulting to `-30d`, or document the performance implication. |
| OG image font path is Linux-specific | Low | `generate_og_image()` hardcodes `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`. On macOS or Windows dev machines, this path does not exist, and the fallback to `ImageFont.load_default()` produces a tiny, barely readable image. The Docker image installs `fonts-dejavu-core` so the container is fine. | Acceptable for Docker-only deployment. Document that OG image quality depends on DejaVu font availability. |
| `Access-Control-Allow-Origin: *` on temperature.json | Info | The `_headers` file sets a wildcard CORS header on the JSON endpoint. This is intentional (allows third-party consumption), but worth noting it means any website can read the temperature data. For a public temperature display, this is appropriate. | No change needed. Document the intentional exposure if privacy matters. |

---

## Structural Observations

1. **Docker layer ordering is correct.** `requirements.txt` is copied and installed before the application code, so Python dependency installs are cached across code-only rebuilds.

2. **`.dockerignore` is thorough.** Secrets (`.env`), dev tooling (`.venv/`, `.claude/`, `.wrangler/`), tests, and documentation are all excluded. Generated artifacts (`temperature.json`, `og-image.png`) are excluded since they are written at runtime.

3. **Security headers are comprehensive.** The CSP is strict and correctly allows `unsafe-inline` only for the inline script and style blocks. HSTS with preload is configured. The `Cross-Origin-*` headers provide isolation.

4. **Cache busting uses `Date.now()` query parameter.** This is simple and effective. Combined with the `Cache-Control: no-cache` header on `temperature.json`, both browser and CDN caching are addressed.

5. **`_parse_int_env` is a clean pattern.** It centralizes env var parsing with named error messages, preventing the class of "invalid literal for int()" errors that are hard to diagnose under cron.

---

## Remediation

### Immediate fix: Docker non-root user
