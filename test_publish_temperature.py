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
    """Create temp site and templates directories for publish() tests.

    Returns the site directory. The index.html template lives in a
    sibling templates/ dir, matching the layout the publish pipeline
    expects (TEMPLATE_DIR is separate from SITE_DIR so that rendered
    output never overwrites the committed source). Callers that need
    to patch TEMPLATE_DIR can derive it from tmp_path / "templates".
    """
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "index.html").write_text(_MINIMAL_INDEX_HTML)
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
# T-022a: 36h min/max aggregation
# ---------------------------------------------------------------------------

class TestMinMax36h:
    """T-022a: Verify the multi-yield Flux query populates min_36h and max_36h."""

    def _make_table(self, value, yield_name):
        # Build a mock FluxTable that looks enough like the real client's
        # output for fetch_temperature() to dispatch on its yield name.
        # The 'result' column holds the yield name, both on the group
        # key (preferred path) and on the record.values fallback.
        record = MagicMock()
        record.get_value.return_value = value
        record.get_time.return_value = datetime(2026, 5, 2, tzinfo=timezone.utc)
        record.values = {"result": yield_name}
        table = MagicMock()
        table.records = [record]
        table.get_group_key.return_value = {"result": yield_name}
        return table

    def _wire(self, monkeypatch, tables):
        mod = _import_fresh()
        api = MagicMock()
        api.query.return_value = tables
        client = MagicMock()
        client.query_api.return_value = api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: client)
        return mod

    def test_three_yields_populate_all_fields(self, monkeypatch):
        # Happy path: three tables, one per yield, each with a real value.
        tables = [
            self._make_table(22.5, "last"),
            self._make_table(18.0, "min_36h"),
            self._make_table(27.3, "max_36h"),
        ]
        mod = self._wire(monkeypatch, tables)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["temperature"] == 22.5
        assert result["min_36h"] == 18.0
        assert result["max_36h"] == 27.3

    def test_missing_min_max_yields_become_none(self, monkeypatch):
        # Sensor offline for >36h: the min/max yields return empty
        # tables, but a "last" record still exists from earlier. The
        # function must still return the latest reading and surface
        # None for the absent aggregates rather than crashing.
        empty_table = MagicMock()
        empty_table.records = []
        empty_table.get_group_key.return_value = {"result": "min_36h"}
        empty_max = MagicMock()
        empty_max.records = []
        empty_max.get_group_key.return_value = {"result": "max_36h"}

        tables = [
            self._make_table(22.5, "last"),
            empty_table,
            empty_max,
        ]
        mod = self._wire(monkeypatch, tables)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["temperature"] == 22.5
        assert result["min_36h"] is None
        assert result["max_36h"] is None

    def test_min_max_skip_temp_min_max_sanity_check(self, monkeypatch):
        # The TEMP_MIN/TEMP_MAX bounds apply only to the latest reading,
        # not to the 36h aggregates. A min of -100 (below TEMP_MIN of
        # -50) should still flow through, since aggregates are summary
        # statistics, not new readings to validate.
        tables = [
            self._make_table(22.5, "last"),
            self._make_table(-100.0, "min_36h"),
            self._make_table(200.0, "max_36h"),
        ]
        mod = self._wire(monkeypatch, tables)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["min_36h"] == -100.0
        assert result["max_36h"] == 200.0

    def test_query_uses_36h_window_for_aggregates(self, monkeypatch):
        # Regression guard: the min/max yields must scope their range
        # to -36h, independent of QUERY_RANGE which only bounds the
        # outer scan. If someone refactors the query and accidentally
        # drops the inner range(start: -36h), this test will catch it.
        mod = _import_fresh()
        api = MagicMock()
        api.query.return_value = [self._make_table(22.5, "last")]
        client = MagicMock()
        client.query_api.return_value = api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: client)

        mod.fetch_temperature()
        query = api.query.call_args[0][0]
        assert "range(start: -36h)" in query
        assert 'yield(name: "min_36h")' in query
        assert 'yield(name: "max_36h")' in query

    def test_completely_missing_aggregate_tables_become_none(self, monkeypatch):
        # In real Flux, an empty min()/max() yield can return zero
        # tables (the entire table for that yield is absent), not a
        # table with zero records. The previous test covered the
        # zero-records shape. This test covers the zero-tables shape.
        mod = self._wire(monkeypatch, [self._make_table(22.5, "last")])
        result = mod.fetch_temperature()
        assert result is not None
        assert result["temperature"] == 22.5
        assert result["min_36h"] is None
        assert result["max_36h"] is None

    def _make_table_at(self, value, yield_name, when):
        # Variant of _make_table that lets the caller pick the record's
        # _time. Used by the multi-series regression tests below.
        record = MagicMock()
        record.get_value.return_value = value
        record.get_time.return_value = when
        record.values = {"result": yield_name}
        table = MagicMock()
        table.records = [record]
        table.get_group_key.return_value = {"result": yield_name}
        return table

    def test_query_groups_and_sorts_before_yields(self, monkeypatch):
        # Regression guard for the multi-host bug: if a device reports
        # under several `host` tag values over the QUERY_RANGE window,
        # InfluxDB returns one table per series unless the pipeline
        # explicitly collapses them. |> group() guarantees a single
        # global last()/min()/max(). |> sort(columns: ["_time"]) after
        # group() guarantees that Flux last() (which returns the last
        # row in iteration order, not the row with max _time) actually
        # picks the time-wise newest record. Dropping either operator
        # silently re-introduces the stale-reading bug.
        mod = _import_fresh()
        api = MagicMock()
        api.query.return_value = [self._make_table(22.5, "last")]
        client = MagicMock()
        client.query_api.return_value = api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: client)

        mod.fetch_temperature()
        query = api.query.call_args[0][0]
        assert "|> group()" in query
        assert '|> sort(columns: ["_time"])' in query
        # Order must be: group() -> sort() -> yields. Otherwise the
        # per-series time ordering inherited from range/filter is
        # invalidated by group() but never restored before last().
        group_pos = query.index("|> group()")
        sort_pos = query.index('|> sort(columns: ["_time"])')
        first_yield_pos = query.index('yield(name: "last")')
        assert group_pos < sort_pos < first_yield_pos

    def test_multiple_last_tables_picks_newest_by_time(self, monkeypatch):
        # Defense in depth for the multi-host bug. Even if |> group()
        # is removed in a future refactor or a new tag dimension
        # silently splits the series, the Python loop should publish
        # the record with the newest _time, not whichever table the
        # client returned last. Three "last" tables, three different
        # timestamps, presented in non-monotonic order.
        older = datetime(2026, 4, 25, tzinfo=timezone.utc)
        middle = datetime(2026, 5, 5, tzinfo=timezone.utc)
        newest = datetime(2026, 5, 9, tzinfo=timezone.utc)
        tables = [
            self._make_table_at(22.4, "last", older),
            self._make_table_at(7.6, "last", newest),
            self._make_table_at(7.0, "last", middle),
        ]
        mod = self._wire(monkeypatch, tables)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["temperature"] == 7.6
        assert result["time"] == newest.isoformat()

    def test_multiple_min_36h_records_picks_smallest(self, monkeypatch):
        # If grouping is ever lost and several min_36h tables come back
        # (one per series), publish the smallest across all of them
        # rather than whichever the client returned last.
        when = datetime(2026, 5, 9, tzinfo=timezone.utc)
        tables = [
            self._make_table_at(22.5, "last", when),
            self._make_table(8.0, "min_36h"),
            self._make_table(5.1, "min_36h"),
            self._make_table(12.3, "min_36h"),
        ]
        mod = self._wire(monkeypatch, tables)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["min_36h"] == 5.1

    def test_multiple_max_36h_records_picks_largest(self, monkeypatch):
        # Mirror of the min test: across multiple max_36h tables, the
        # published value must be the largest.
        when = datetime(2026, 5, 9, tzinfo=timezone.utc)
        tables = [
            self._make_table_at(22.5, "last", when),
            self._make_table(18.0, "max_36h"),
            self._make_table(27.3, "max_36h"),
            self._make_table(11.2, "max_36h"),
        ]
        mod = self._wire(monkeypatch, tables)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["max_36h"] == 27.3

    def test_all_last_records_invalid_returns_none(self, monkeypatch):
        # If every "last" record fails validation (e.g. NaN across the
        # board), the function must still abort the publish rather than
        # falling back to a stale or default value.
        when = datetime(2026, 5, 9, tzinfo=timezone.utc)
        tables = [
            self._make_table_at(float("nan"), "last", when),
            self._make_table_at(float("inf"), "last", when),
        ]
        mod = self._wire(monkeypatch, tables)
        assert mod.fetch_temperature() is None

    def test_mixed_valid_and_invalid_last_records_picks_valid_newest(self, monkeypatch):
        # One invalid record (NaN) at the newest timestamp must not
        # poison the publish: the next-newest valid record should win,
        # rather than the function aborting on the first bad row.
        older = datetime(2026, 5, 5, tzinfo=timezone.utc)
        newer = datetime(2026, 5, 9, tzinfo=timezone.utc)
        tables = [
            self._make_table_at(float("nan"), "last", newer),
            self._make_table_at(7.0, "last", older),
        ]
        mod = self._wire(monkeypatch, tables)
        result = mod.fetch_temperature()
        assert result is not None
        assert result["temperature"] == 7.0
        assert result["time"] == older.isoformat()


# ---------------------------------------------------------------------------
# T-023: Pretty-print sensor name
# ---------------------------------------------------------------------------

class TestPrettyDeviceName:
    """T-023: Verify the device-name display transform and JSON shape."""

    @pytest.mark.parametrize("raw,pretty", [
        ("gisebo-01", "Gisebo 01"),
        ("living_room", "Living room"),
        ("temp-sensor_kitchen", "Temp sensor kitchen"),
        ("Foo-Bar", "Foo Bar"),  # case beyond the first char preserved
        ("", ""),
        ("a", "A"),
        ("x_y_z", "X y z"),
        ("123-abc", "123 abc"),  # leading digit: upper() is a no-op, dash still becomes space
    ], ids=[
        "hyphen-and-digits",
        "underscore",
        "mixed-separators",
        "case-preserved-past-first",
        "empty-string",
        "single-character",
        "multiple-underscores",
        "leading-digit",
    ])
    def test_pretty_device_name(self, raw, pretty):
        mod = _import_fresh()
        assert mod._pretty_device_name(raw) == pretty

    def test_fetch_returns_device_name_alongside_device_id(self, monkeypatch):
        # The raw device_id must stay in the payload (machine
        # consumers depend on it as a stable identifier), and the
        # new device_name must be the pretty-printed form.
        mod = _import_fresh()
        record = MagicMock()
        record.get_value.return_value = 22.5
        record.get_time.return_value = datetime(2026, 5, 2, tzinfo=timezone.utc)
        record.values = {"result": "last"}
        table = MagicMock()
        table.records = [record]
        table.get_group_key.return_value = {"result": "last"}
        api = MagicMock()
        api.query.return_value = [table]
        client = MagicMock()
        client.query_api.return_value = api
        monkeypatch.setattr(mod, "InfluxDBClient", lambda **kw: client)

        result = mod.fetch_temperature()
        assert result["device_id"] == "gisebo-01"
        assert result["device_name"] == "Gisebo 01"


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
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")
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
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

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
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

        calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw))

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        assert calls[0]["check"] is True

    def test_publish_has_deploy_timeout(self, monkeypatch, tmp_path):
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

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
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

        calls = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw))

        data = {"temperature": 22.5, "time": "t", "device_id": "d", "updated_at": "u"}
        mod.publish(data)

        assert calls[0]["timeout"] == 60

    def test_no_ssh_scp_calls(self, monkeypatch, tmp_path):
        mod = _import_fresh()

        site_dir = _make_site_dir(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

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
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

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


# ---------------------------------------------------------------------------
# T-024: HTML escaping in _update_og_meta
# ---------------------------------------------------------------------------

class TestOgMetaEscaping:
    """T-024: Verify that hostile device names cannot break the OG meta block.

    The OG/Twitter meta block is rewritten in place by _update_og_meta with
    values that originate in InfluxDB (device_id) or operator-controlled
    .env (SITE_URL). The CSP at site/_headers blocks runtime script
    execution, so the practical risk is structural breakage of the meta
    tags, which would silently break OG previews on social-media crawlers.
    These tests pin the escaping behaviour so a future refactor cannot
    quietly drop html.escape() and reintroduce the malformed-tag class.
    """

    # The regex inside _update_og_meta requires 4 leading spaces before
    # the OG_META_START marker (matching the indentation in the real
    # site/index.html). The shared _MINIMAL_INDEX_HTML fixture is
    # unindented to keep other tests compact, so this class uses its
    # own indented fixture so the rewrite actually fires.
    _INDENTED_INDEX_HTML = (
        "<html><head>\n"
        "    <!-- OG_META_START -->\n"
        '    <meta property="og:image" content="og-placeholder.png">\n'
        "    <!-- OG_META_END -->\n"
        "</head><body></body></html>"
    )

    def _make_indented_site(self, tmp_path):
        # The template lives under tmp_path/templates so it matches the
        # publish_temperature.py layout (TEMPLATE_DIR for source,
        # SITE_DIR for rendered output). The rewritten index.html is
        # written into the (initially empty) site directory.
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "index.html").write_text(self._INDENTED_INDEX_HTML)
        return site_dir

    def _payload(self, device_name):
        # Minimal payload shape required by _update_og_meta. The function
        # only reads temperature, device_name (preferred), and device_id
        # (fallback), so we keep the rest absent to make the test focus
        # crisp.
        return {
            "temperature": 22.5,
            "device_id": "gisebo-01",
            "device_name": device_name,
        }

    def test_hostile_device_name_is_escaped(self, monkeypatch, tmp_path):
        # The crafted device name embeds a closing quote, a closing tag,
        # and a script open tag. Without escaping, the rewritten meta
        # block would contain the literal '<script' inside a content
        # attribute and an unbalanced '>' that breaks tag boundaries.
        # With html.escape(quote=True), all three dangerous characters
        # ('"', '<', '>') become their entity equivalents and the meta
        # block stays well-formed.
        mod = _import_fresh()
        site_dir = self._make_indented_site(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

        hostile = 'Foo"><script>alert(1)</script>'
        mod._update_og_meta(self._payload(hostile), "og-test.png")
        rewritten = (site_dir / "index.html").read_text()

        # 1. The rewritten HTML must not contain the literal '<script'
        # substring inside any content attribute. We slice the OG block
        # out of the document and search inside it. A naive substring
        # search across the whole document would also pass because the
        # minimal index has no other <script>, but scoping to the OG
        # block makes the intent explicit and survives test fixtures
        # that grow a real <script> tag elsewhere in index.html.
        og_start = rewritten.index("<!-- OG_META_START -->")
        og_end = rewritten.index("<!-- OG_META_END -->")
        og_block = rewritten[og_start:og_end]
        assert "<script" not in og_block, (
            "Unescaped script tag leaked into the OG meta block. "
            "Check html.escape() usage in _update_og_meta()."
        )

        # 2. The dangerous characters must appear escaped at least once
        # (proving escape ran), not just be absent (which could mean
        # someone stripped them). We expect each of the three entities
        # to appear in the og:title or og:description fields.
        assert "&quot;" in og_block
        assert "&gt;" in og_block
        assert "&lt;" in og_block

        # 3. Every <meta> tag in the OG block must be well-formed: each
        # opening '<meta' is balanced by exactly one '>'. We count the
        # markers as a cheap structural well-formedness check, since a
        # full HTML parser is overkill for a regression guard.
        meta_open_count = og_block.count("<meta")
        meta_close_count = og_block.count(">")
        # Each <meta ...> closes with exactly one '>'. If the hostile
        # input had broken out of an attribute, we would see an extra
        # '>' from the injected payload pushing the count above the
        # number of <meta tags. The minimal block contains 11 meta
        # tags after rewriting, plus one '>' from the OG_META_START
        # comment that opens this slice, for 12 total. This pins the
        # exact shape so any future malformed output trips the test.
        assert meta_close_count == meta_open_count + 1, (
            f"OG block has {meta_open_count} <meta tags but {meta_close_count} '>' "
            f"characters. Mismatch indicates a malformed tag from unescaped input."
        )

    def test_ascii_device_name_unchanged_happy_path(self, monkeypatch, tmp_path):
        # Regression guard: a benign ASCII device name should produce a
        # readable OG block with no entity-escaped artefacts in the
        # human-visible fields. html.escape() on plain ASCII is a
        # no-op, so the rendered title and description should match
        # exactly what they looked like before T-024 added escaping.
        mod = _import_fresh()
        site_dir = self._make_indented_site(tmp_path)
        monkeypatch.setattr(mod, "SITE_DIR", site_dir)
        monkeypatch.setattr(mod, "TEMPLATE_DIR", tmp_path / "templates")

        mod._update_og_meta(self._payload("Gisebo 01"), "og-abcd1234.png")
        rewritten = (site_dir / "index.html").read_text()

        # The pretty device name flows verbatim into og:title and
        # og:description and twitter:title. We assert the human-readable
        # phrasing so a future refactor of the title format trips the
        # test and forces a deliberate decision.
        assert 'content="22.5°C — Gisebo 01 Temperature"' in rewritten
        assert "Current reading: 22.5°C from sensor Gisebo 01" in rewritten

        # And the OG image filename should land in the og:image and
        # twitter:image content attributes unmodified, since plain
        # filenames have no characters that html.escape() touches.
        assert 'og-abcd1234.png"' in rewritten
        # Negative assertion: there should be NO entity references in
        # the happy-path block. If escape ever starts mangling benign
        # input (e.g. by escaping a literal & to &amp; in a URL that
        # genuinely needed an &), this catches the regression.
        og_start = rewritten.index("<!-- OG_META_START -->")
        og_end = rewritten.index("<!-- OG_META_END -->")
        og_block = rewritten[og_start:og_end]
        assert "&quot;" not in og_block
        assert "&gt;" not in og_block
        assert "&lt;" not in og_block
        assert "&amp;" not in og_block
