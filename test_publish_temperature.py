"""Tests for publish_temperature.py covering T-001 through T-007d."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers: set all required env vars so the module can be imported
# ---------------------------------------------------------------------------

REQUIRED_ENV = {
    "INFLUXDB_URL": "http://localhost:8086",
    "INFLUXDB_TOKEN": "test-token",
    "INFLUXDB_ORG": "test-org",
    "INFLUXDB_BUCKET": "home_assistant",
    "MEASUREMENT": "http_listener_v2",
    "FIELD": "temperature",
    "DEVICE_ID": "gisebo-01",
    "CLOUDFLARE_API_TOKEN": "test-cf-token",
    "CLOUDFLARE_ACCOUNT_ID": "test-cf-account",
    "CLOUDFLARE_PROJECT_NAME": "temperature",
}


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Ensure all required env vars are set for every test."""
    for key, val in REQUIRED_ENV.items():
        monkeypatch.setenv(key, val)


def _import_fresh():
    """Import a fresh copy of the module (after env is set)."""
    if "publish_temperature" in sys.modules:
        del sys.modules["publish_temperature"]
    import publish_temperature
    return publish_temperature


_MINIMAL_INDEX_HTML = (
    '<html><head><!-- OG_META_START -->'
    '<meta property="og:image" content="og-image.png">'
    '<!-- OG_META_END --></head><body></body></html>'
)


def _make_site_dir(tmp_path):
    """Create a temp site directory with a minimal index.html for publish() tests."""
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text(_MINIMAL_INDEX_HTML)
    return site_dir


# ---------------------------------------------------------------------------
# T-002: Flux query input validation
# ---------------------------------------------------------------------------

class TestFluxQueryValidation:
    """T-002: Verify query values are validated against injection."""

    def test_query_contains_filter_values(self, monkeypatch):
        mod = _import_fresh()

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        mod.fetch_temperature()

        query = mock_query_api.query.call_args[0][0]
        assert "home_assistant" in query
        assert "http_listener_v2" in query
        assert "temperature" in query
        assert "gisebo-01" in query

    def test_flux_query_has_no_host_filter(self, monkeypatch):
        # T-021a regression guard. The host filter was removed because the
        # value was a Docker container ID, which Docker reassigns on every
        # container recreation. A churning ID inside a stable filter caused
        # silent zero-row results. The device_id filter is already a unique
        # sensor identifier, so the host filter added no selectivity.
        mod = _import_fresh()
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        mod.fetch_temperature()

        query = mock_query_api.query.call_args[0][0]
        assert 'r["host"]' not in query
        assert "61781446e5e9" not in query

    def test_host_filter_env_var_is_ignored_silently(self, monkeypatch):
        # T-021a backward-compat guard. Operators who still have HOST_FILTER
        # in their .env should NOT see an error, the variable should be
        # ignored. If a future change re-adds "HOST_FILTER" to REQUIRED_VARS,
        # this test will fail and flag the regression.
        monkeypatch.setenv("HOST_FILTER", "leftover-from-old-env-file")
        mod = _import_fresh()
        assert "HOST_FILTER" not in mod.REQUIRED_VARS
        assert not hasattr(mod, "HOST_FILTER")

    def test_injection_in_device_id_is_rejected(self, monkeypatch):
        monkeypatch.setenv("DEVICE_ID", '") |> drop(')
        mod = _import_fresh()
        with pytest.raises(ValueError, match="Invalid character in DEVICE_ID"):
            mod.fetch_temperature()

    def test_invalid_bucket_name_raises(self, monkeypatch):
        monkeypatch.setenv("INFLUXDB_BUCKET", 'bad"; drop')
        mod = _import_fresh()
        with pytest.raises(ValueError, match="Invalid bucket name"):
            mod.fetch_temperature()

    def test_valid_bucket_name_passes(self, monkeypatch):
        mod = _import_fresh()
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        mod.fetch_temperature()

    def test_backslash_in_filter_value_rejected(self, monkeypatch):
        monkeypatch.setenv("FIELD", 'temp\\n')
        mod = _import_fresh()
        with pytest.raises(ValueError, match="Invalid character in FIELD"):
            mod.fetch_temperature()


# ---------------------------------------------------------------------------
# T-003: Timeouts
# ---------------------------------------------------------------------------

class TestTimeouts:
    """T-003: Verify timeout propagation to all blocking calls."""

    def test_publish_subprocess_has_deploy_timeout(self, monkeypatch):
        mod = _import_fresh()
        calls = []

        def mock_run(*args, **kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        assert calls[0]["timeout"] == 120

    def test_influxdb_timeout_independent_from_deploy_timeout(self, monkeypatch):
        monkeypatch.setenv("TIMEOUT_SECONDS", "10")
        monkeypatch.setenv("DEPLOY_TIMEOUT_SECONDS", "300")
        mod = _import_fresh()
        client_kwargs = {}

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []

        def mock_client(**kwargs):
            client_kwargs.update(kwargs)
            m = MagicMock()
            m.query_api.return_value = mock_query_api
            return m

        monkeypatch.setattr(mod, "InfluxDBClient", mock_client)
        mod.fetch_temperature()

        # InfluxDB client should use TIMEOUT_SECONDS (10), not DEPLOY_TIMEOUT_SECONDS (300)
        assert client_kwargs["timeout"] == 10000

    def test_influxdb_client_has_timeout(self, monkeypatch):
        mod = _import_fresh()
        client_kwargs = {}

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []

        def mock_client(**kwargs):
            client_kwargs.update(kwargs)
            m = MagicMock()
            m.query_api.return_value = mock_query_api
            return m

        monkeypatch.setattr(mod, "InfluxDBClient", mock_client)
        mod.fetch_temperature()

        assert client_kwargs["timeout"] == 30000

    def test_default_timeout_is_30(self, monkeypatch):
        monkeypatch.delenv("TIMEOUT_SECONDS", raising=False)
        mod = _import_fresh()
        assert mod.TIMEOUT_SECONDS == 30


# ---------------------------------------------------------------------------
# T-004: Dependency pinning and env validation
# ---------------------------------------------------------------------------

class TestDependencyPinning:
    """T-004: Verify requirements.txt has pinned versions."""

    def test_requirements_pinned(self):
        import re
        with open("requirements.txt") as f:
            lines = [l.strip() for l in f if l.strip()]
        for line in lines:
            assert re.match(r"^[\w-]+==[0-9.]+$", line), f"Unpinned: {line}"


class TestEnvValidation:
    """T-004: Verify startup validation catches missing env vars."""

    def test_missing_all_vars_exits(self, monkeypatch):
        for var in REQUIRED_ENV:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

        with pytest.raises(SystemExit) as exc_info:
            _import_fresh()
        assert exc_info.value.code == 1

    def test_missing_one_var_reports_it(self, monkeypatch, capsys):
        monkeypatch.delenv("CLOUDFLARE_PROJECT_NAME")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

        with pytest.raises(SystemExit):
            _import_fresh()

        captured = capsys.readouterr()
        assert "CLOUDFLARE_PROJECT_NAME" in captured.err

    def test_all_vars_present_no_error(self):
        mod = _import_fresh()
        assert mod.INFLUXDB_URL == "http://localhost:8086"


# ---------------------------------------------------------------------------
# T-005a: Temperature value validation
# ---------------------------------------------------------------------------

class TestTemperatureValidation:
    """T-005a: Verify invalid temperature values are rejected."""

    def _make_mock_client(self, value, monkeypatch):
        # T-022a: the production query now uses multi-yield Flux. Each
        # table carries a "result" column equal to the yield name. For
        # backward-compat with single-value tests, this helper returns
        # one table tagged as the "last" yield.
        mod = _import_fresh()
        mock_record = MagicMock()
        mock_record.get_value.return_value = value
        mock_record.get_time.return_value = datetime(2026, 5, 2, tzinfo=timezone.utc)
        mock_record.values = {"result": "last"}

        mock_table = MagicMock()
        mock_table.records = [mock_record]
        mock_table.get_group_key.return_value = {"result": "last"}

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = [mock_table]

        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)
        return mod

    def test_nan_returns_none(self, monkeypatch):
        mod = self._make_mock_client(float("nan"), monkeypatch)
        assert mod.fetch_temperature() is None

    def test_inf_returns_none(self, monkeypatch):
        mod = self._make_mock_client(float("inf"), monkeypatch)
        assert mod.fetch_temperature() is None

    def test_string_returns_none(self, monkeypatch):
        mod = self._make_mock_client("twenty", monkeypatch)
        assert mod.fetch_temperature() is None

    def test_none_returns_none(self, monkeypatch):
        mod = self._make_mock_client(None, monkeypatch)
        assert mod.fetch_temperature() is None

    def test_valid_float_returns_data(self, monkeypatch):
        mod = self._make_mock_client(22.5, monkeypatch)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["temperature"] == 22.5

    def test_out_of_range_warns_but_publishes(self, monkeypatch, caplog):
        import logging
        mod = self._make_mock_client(100.0, monkeypatch)
        with caplog.at_level(logging.WARNING):
            result = mod.fetch_temperature()
        assert result is not None
        assert result["temperature"] == 100.0
        assert "outside expected range" in caplog.text


# ---------------------------------------------------------------------------
# T-005b: Structured logging
# ---------------------------------------------------------------------------

class TestStructuredLogging:
    """T-005b: Verify print() is replaced with logging."""

    def test_success_logs_info(self, monkeypatch, caplog):
        import logging
        mod = _import_fresh()

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        mock_record = MagicMock()
        mock_record.get_value.return_value = 22.5
        mock_record.get_time.return_value = datetime(2026, 5, 2, tzinfo=timezone.utc)
        mock_record.values = {"result": "last"}  # T-022a: tag as last yield
        mock_table = MagicMock()
        mock_table.records = [mock_record]
        mock_table.get_group_key.return_value = {"result": "last"}
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = [mock_table]
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        with caplog.at_level(logging.INFO):
            mod.main()

        assert "Published:" in caplog.text

    def test_no_data_logs_error(self, monkeypatch, caplog):
        import logging
        mod = _import_fresh()

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit):
                mod.main()

        assert "No data returned from InfluxDB" in caplog.text


# ---------------------------------------------------------------------------
# T-007c: Cloudflare Pages publish
# ---------------------------------------------------------------------------

class TestCloudflarePublish:
    """T-007c: Verify publish() writes temperature.json and calls Wrangler."""

    def test_publish_writes_temperature_json(self, monkeypatch, tmp_path):
        mod = _import_fresh()

        # Point SITE_DIR to a temp directory
        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        data = {
            "temperature": 22.5,
            "time": "2026-05-02T12:00:00+00:00",
            "device_id": "gisebo-01",
            "updated_at": "2026-05-02T12:00:01+00:00",
        }
        mod.publish(data)

        json_path = site_dir / "temperature.json"
        assert json_path.exists()
        written = json.loads(json_path.read_text())
        assert written["temperature"] == 22.5
        assert written["device_id"] == "gisebo-01"
        assert written["time"] == "2026-05-02T12:00:00+00:00"
        assert written["updated_at"] == "2026-05-02T12:00:01+00:00"

    def test_publish_calls_wrangler_with_correct_args(self, monkeypatch, tmp_path):
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)

        calls = []

        def mock_run(*args, **kwargs):
            calls.append((args, kwargs))

        monkeypatch.setattr(subprocess, "run", mock_run)

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        assert len(calls) == 1
        cmd = calls[0][0][0]
        assert cmd[0] == "npx"
        assert cmd[1] == "wrangler"
        assert cmd[2] == "pages"
        assert cmd[3] == "deploy"
        assert cmd[4] == str(site_dir)
        assert "--project-name" in cmd
        project_idx = cmd.index("--project-name")
        assert cmd[project_idx + 1] == "temperature"

    def test_publish_uses_check_true(self, monkeypatch, tmp_path):
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)

        calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw))

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        assert calls[0]["check"] is True

    def test_publish_has_deploy_timeout(self, monkeypatch, tmp_path):
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)

        calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw))

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        assert calls[0]["timeout"] == 120

    def test_custom_deploy_timeout(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DEPLOY_TIMEOUT_SECONDS", "60")
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)

        calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw))

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        assert calls[0]["timeout"] == 60

    def test_no_ssh_scp_calls(self, monkeypatch, tmp_path):
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)

        calls = []

        def mock_run(*args, **kwargs):
            calls.append(args[0])

        monkeypatch.setattr(subprocess, "run", mock_run)

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        for cmd in calls:
            assert cmd[0] != "scp", "SCP should no longer be used"
            assert cmd[0] != "ssh", "SSH should no longer be used"


# ---------------------------------------------------------------------------
# T-007d: Cloudflare env vars
# ---------------------------------------------------------------------------

class TestCloudflareEnvVars:
    """T-007d: Verify env vars are updated for Cloudflare Pages."""

    def test_env_example_has_cloudflare_vars(self):
        with open(".env.example") as f:
            content = f.read()
        assert "CLOUDFLARE_API_TOKEN" in content
        assert "CLOUDFLARE_ACCOUNT_ID" in content
        assert "CLOUDFLARE_PROJECT_NAME" in content

    def test_env_example_no_ssh_vars(self):
        with open(".env.example") as f:
            content = f.read()
        assert "REMOTE_USER" not in content
        assert "REMOTE_HOST" not in content
        assert "REMOTE_PATH" not in content

    def test_required_vars_includes_cloudflare(self):
        mod = _import_fresh()
        assert "CLOUDFLARE_API_TOKEN" in mod.REQUIRED_VARS
        assert "CLOUDFLARE_ACCOUNT_ID" in mod.REQUIRED_VARS
        assert "CLOUDFLARE_PROJECT_NAME" in mod.REQUIRED_VARS

    def test_required_vars_excludes_ssh(self):
        mod = _import_fresh()
        assert "REMOTE_USER" not in mod.REQUIRED_VARS
        assert "REMOTE_HOST" not in mod.REQUIRED_VARS
        assert "REMOTE_PATH" not in mod.REQUIRED_VARS

    def test_missing_cloudflare_project_name_exits(self, monkeypatch, capsys):
        monkeypatch.delenv("CLOUDFLARE_PROJECT_NAME")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

        with pytest.raises(SystemExit):
            _import_fresh()

        captured = capsys.readouterr()
        assert "CLOUDFLARE_PROJECT_NAME" in captured.err

    def test_module_exposes_cloudflare_project_name(self):
        mod = _import_fresh()
        assert mod.CLOUDFLARE_PROJECT_NAME == "temperature"


# ---------------------------------------------------------------------------
# T-009: Exception handling in main()
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    """T-009: Verify main() catches and logs exceptions before exiting."""

    def test_deploy_failure_logs_error(self, monkeypatch, caplog, tmp_path):
        import logging
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)

        mock_record = MagicMock()
        mock_record.get_value.return_value = 22.5
        mock_record.get_time.return_value = datetime(2026, 5, 2, tzinfo=timezone.utc)
        mock_record.values = {"result": "last"}  # T-022a: tag as last yield
        mock_table = MagicMock()
        mock_table.records = [mock_record]
        mock_table.get_group_key.return_value = {"result": "last"}
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = [mock_table]
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        def mock_run(*a, **kw):
            raise subprocess.CalledProcessError(1, "wrangler")

        monkeypatch.setattr(subprocess, "run", mock_run)

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                mod.main()

        assert exc_info.value.code == 1
        assert "Deploy failed" in caplog.text

    def test_unexpected_error_logs_with_traceback(self, monkeypatch, caplog):
        import logging
        mod = _import_fresh()

        def exploding_client(**kw):
            raise ConnectionError("connection refused")

        monkeypatch.setattr(mod, "InfluxDBClient", exploding_client)

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                mod.main()

        assert exc_info.value.code == 1
        assert "Failed" in caplog.text
        assert "connection refused" in caplog.text


# ---------------------------------------------------------------------------
# T-013: Module-level env var parsing with clear errors
# ---------------------------------------------------------------------------

class TestEnvVarParsing:
    """T-013: Verify invalid integer env vars produce clear errors."""

    def test_invalid_temp_min_exits_with_message(self, monkeypatch, capsys):
        monkeypatch.setenv("TEMP_MIN", "abc")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

        with pytest.raises(SystemExit) as exc_info:
            _import_fresh()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "TEMP_MIN" in captured.err

    def test_invalid_timeout_exits_with_message(self, monkeypatch, capsys):
        monkeypatch.setenv("TIMEOUT_SECONDS", "fast")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

        with pytest.raises(SystemExit) as exc_info:
            _import_fresh()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "TIMEOUT_SECONDS" in captured.err

    def test_temp_min_max_at_module_level(self):
        mod = _import_fresh()
        assert mod.TEMP_MIN == -50
        assert mod.TEMP_MAX == 80


# ---------------------------------------------------------------------------
# T-020a: QUERY_RANGE config and Flux duration validation
# ---------------------------------------------------------------------------

class TestQueryRange:
    """T-020a: Verify QUERY_RANGE bounds the Flux query window."""

    def test_query_range_default_is_30d(self, monkeypatch):
        # No QUERY_RANGE in env, default -30d should land in the query.
        # Critically, the old range(start: 0) full-bucket scan must be gone.
        monkeypatch.delenv("QUERY_RANGE", raising=False)
        mod = _import_fresh()

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        mod.fetch_temperature()
        query = mock_query_api.query.call_args[0][0]
        assert "range(start: -30d)" in query
        assert "range(start: 0)" not in query

    def test_query_range_overrides_via_env(self, monkeypatch):
        # Operator override should flow straight into the query.
        monkeypatch.setenv("QUERY_RANGE", "-7d")
        mod = _import_fresh()

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: mock_client)

        mod.fetch_temperature()
        query = mock_query_api.query.call_args[0][0]
        assert "range(start: -7d)" in query

    def test_invalid_query_range_exits(self, monkeypatch, capsys):
        # Garbage value must fail loudly at import time, not silently
        # produce a broken Flux query at fetch time.
        monkeypatch.setenv("QUERY_RANGE", "garbage")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

        with pytest.raises(SystemExit) as exc_info:
            _import_fresh()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "QUERY_RANGE" in captured.err

    def test_query_range_rejects_missing_minus(self, monkeypatch):
        # Common mistake: forgetting the leading minus, which would mean
        # "30 days from now" in Flux, not "the last 30 days".
        monkeypatch.setenv("QUERY_RANGE", "30d")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        with pytest.raises(SystemExit):
            _import_fresh()

    def test_query_range_rejects_unsupported_unit(self, monkeypatch):
        # Flux supports s/m/h/d/w. Years (y) and months (mo) need extra
        # logic to compute and are out of scope for this knob.
        monkeypatch.setenv("QUERY_RANGE", "-1y")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        with pytest.raises(SystemExit):
            _import_fresh()


# ---------------------------------------------------------------------------
# T-014: SITE_DIR validation
# ---------------------------------------------------------------------------

class TestSiteDirValidation:
    """T-014: Verify missing site/ directory is caught at startup."""

    def test_missing_site_dir_exits(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
        # Point Path(__file__).parent to a dir without site/
        import pathlib
        monkeypatch.setattr(pathlib.Path, "is_dir", lambda self: False if "site" in str(self) else True)

        with pytest.raises(SystemExit) as exc_info:
            _import_fresh()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "site" in captured.err.lower()
