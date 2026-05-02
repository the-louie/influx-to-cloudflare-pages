# TODO Summary

| ID | Title | Complexity | Est. Time | Summary |
|----|-------|-----------|-----------|---------|
| T-001 | Secure subprocess calls in publish() against shell injection | Low | 1–2h | Add shlex.quote() to SSH mv and SCP path arguments, write tests with metacharacter payloads |
| T-002 | Parameterize Flux query to prevent injection | Medium | 1–2h | Replace f-string query with params dict, verify client version support, test with injection payloads |
| T-003 | Add timeouts to all blocking calls and document HTTPS | Low | 1–2h | Add configurable TIMEOUT_SECONDS to subprocess and InfluxDB calls, add HTTPS comment to .env.example |
| T-004 | Pin dependency versions and add env variable validation | Low | 1–2h | Pin exact versions in requirements.txt, add startup check listing all missing env vars |
| T-005 | Add temperature value validation and structured logging | Medium | 1–2h | Reject non-finite values from InfluxDB, replace print() with logging module for cron compatibility |
| T-006 | Add remote .tmp file cleanup on SSH mv failure | Low | 1–2h | Attempt rm of orphan .tmp on remote host if mv fails, re-raise original error, depends on T-001 |

## Statistics

, **Total tickets:** 6
, **Original items consolidated:** 9 (from prior TODO)
, **Dependency chain:** T-006 depends on T-001, T-006 optionally benefits from T-003 and T-005
, **Estimated total effort:** 6–12h (6 tickets × 1–2h)
, **Security tickets:** 3 (T-001, T-002, T-003)
, **Operational tickets:** 3 (T-004, T-005, T-006)
