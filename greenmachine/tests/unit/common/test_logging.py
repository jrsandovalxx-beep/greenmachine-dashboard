"""Structured logging: valid JSON, quiet by default, observational only."""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import subprocess
from collections.abc import Iterator

import pytest

from greenmachine.common.errors import ErrorContext, ProviderSchemaChangeError
from greenmachine.common.logging import (
    CONTEXT_ATTRIBUTE,
    DEFAULT_LEVEL,
    ERROR_ATTRIBUTE,
    LogContext,
    StructuredJsonFormatter,
    bind_context,
    configure_logger,
)

LOGGER_NAME = "greenmachine.test"


@pytest.fixture(autouse=True)
def clean_logger() -> Iterator[None]:
    """Leave the logging registry as we found it, and never touch the root."""
    root_before = (list(logging.root.handlers), logging.root.level)
    try:
        yield
    finally:
        for name in list(logging.Logger.manager.loggerDict):
            if name.startswith("greenmachine"):
                logger = logging.getLogger(name)
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                logger.setLevel(logging.NOTSET)
                logger.propagate = True
        assert (list(logging.root.handlers), logging.root.level) == root_before


def records_from(stream: io.StringIO) -> list[dict[str, object]]:
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


# --------------------------------------------------------------------------
# Quiet by default
# --------------------------------------------------------------------------


def test_the_default_path_emits_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    logger = configure_logger(LOGGER_NAME)

    logger.error("this must not appear")
    logger.critical("nor this")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_the_default_handler_is_a_null_handler() -> None:
    logger = configure_logger(LOGGER_NAME)

    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.NullHandler)


def test_the_default_level_is_quiet() -> None:
    assert DEFAULT_LEVEL == logging.WARNING
    assert configure_logger(LOGGER_NAME).level == logging.WARNING


def test_the_root_logger_is_never_touched() -> None:
    before_handlers = list(logging.root.handlers)
    before_level = logging.root.level

    configure_logger(LOGGER_NAME, stream=io.StringIO(), level=logging.DEBUG)

    assert logging.root.handlers == before_handlers
    assert logging.root.level == before_level


def test_records_do_not_propagate_to_the_root() -> None:
    logger = configure_logger(LOGGER_NAME, stream=io.StringIO())

    assert logger.propagate is False


# --------------------------------------------------------------------------
# JSON output
# --------------------------------------------------------------------------


def test_output_is_valid_json_with_the_fixed_fields() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)

    logger.info("hello")

    (record,) = records_from(stream)
    assert record == {"level": "INFO", "logger": LOGGER_NAME, "message": "hello"}


def test_message_formatting_arguments_are_rendered() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)

    logger.info("loaded %s components", 11)

    assert records_from(stream)[0]["message"] == "loaded 11 components"


def test_no_timestamp_is_emitted() -> None:
    """GreenMachine generates no time; the record's own timing is not read."""
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)

    logger.info("hello")

    record = records_from(stream)[0]
    assert not any(key in record for key in ("time", "timestamp", "asctime", "created"))


def test_two_identical_events_produce_identical_bytes() -> None:
    """Nothing varying — no clock, no counter — enters the record."""
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)

    logger.info("same event")
    logger.info("same event")

    lines = stream.getvalue().splitlines()
    assert lines[0] == lines[1]


def test_non_ascii_content_stays_valid_and_unescaped() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)

    logger.info("Recent — Last 7 Days ⚾")

    assert "Recent — Last 7 Days ⚾" in stream.getvalue()
    assert records_from(stream)[0]["message"] == "Recent — Last 7 Days ⚾"


# --------------------------------------------------------------------------
# Correlation context
# --------------------------------------------------------------------------


def test_correlation_fields_appear_when_supplied() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)
    adapter = bind_context(
        logger,
        LogContext(
            model_version="v0.1.0",
            config_hash="abc123",
            input_hash="def456",
            window_profile="RECENT_7D",
        ),
    )

    adapter.info("graded")

    record = records_from(stream)[0]
    assert record["model_version"] == "v0.1.0"
    assert record["config_hash"] == "abc123"
    assert record["input_hash"] == "def456"
    assert record["window_profile"] == "RECENT_7D"


def test_absent_correlation_fields_are_consistently_omitted() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)
    adapter = bind_context(logger, LogContext(model_version="v0.1.0"))

    adapter.info("first")
    adapter.info("second")

    first, second = records_from(stream)
    assert set(first) == set(second)
    assert "config_hash" not in first
    assert "window_profile" not in first


def test_a_partial_context_only_reports_what_it_knows() -> None:
    assert LogContext(model_version="v0.1.0").as_dict() == {"model_version": "v0.1.0"}
    assert LogContext().as_dict() == {}


def test_log_context_is_frozen_and_hashable() -> None:
    context = LogContext(model_version="v0.1.0")

    assert hash(context) == hash(LogContext(model_version="v0.1.0"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.model_version = "v9"


def test_log_context_rejects_non_string_fields() -> None:
    with pytest.raises(TypeError, match=r"LogContext\.model_version must be a string"):
        LogContext(model_version=7)  # type: ignore[arg-type]


def test_binding_does_not_mutate_the_supplied_context() -> None:
    context = LogContext(model_version="v0.1.0")
    stream = io.StringIO()
    adapter = bind_context(configure_logger(LOGGER_NAME, stream=stream), context)

    adapter.warning("something")

    assert context == LogContext(model_version="v0.1.0")
    assert context.as_dict() == {"model_version": "v0.1.0"}


def test_a_caller_supplied_extra_dictionary_is_not_mutated() -> None:
    stream = io.StringIO()
    adapter = bind_context(
        configure_logger(LOGGER_NAME, stream=stream), LogContext(model_version="v0.1.0")
    )
    extra: dict[str, object] = {"unrelated": "value"}

    adapter.warning("something", extra=extra)

    assert extra == {"unrelated": "value"}
    assert CONTEXT_ATTRIBUTE not in extra


def test_bind_context_validates_its_arguments() -> None:
    with pytest.raises(TypeError, match=r"logger must be a logging.Logger"):
        bind_context("not a logger", LogContext())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"context must be a LogContext"):
        bind_context(configure_logger(LOGGER_NAME), {"model_version": "v"})  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Errors in records
# --------------------------------------------------------------------------


def test_a_greenmachine_error_is_logged_structurally() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)
    error = ProviderSchemaChangeError(
        "column renamed",
        ErrorContext(provider="baseball_savant", expected="launch_speed", observed="ev"),
    )

    logger.error("ingestion failed", extra={ERROR_ATTRIBUTE: error})

    record = records_from(stream)[0]
    assert record["error"] == {
        "error_type": "ProviderSchemaChangeError",
        "message": "column renamed",
        "context": {
            "provider": "baseball_savant",
            "expected": "launch_speed",
            "observed": "ev",
        },
    }


def test_an_error_raised_in_context_is_captured_from_exc_info() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)

    try:
        raise ProviderSchemaChangeError("boom", ErrorContext(provider="p"))
    except ProviderSchemaChangeError:
        logger.exception("caught")

    record = records_from(stream)[0]
    assert record["error"]["error_type"] == "ProviderSchemaChangeError"  # type: ignore[index]


def test_logging_an_error_does_not_alter_it() -> None:
    """Observational only: the exception is unchanged by being logged."""
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)
    context = ErrorContext(provider="p", expected="a", observed="b")
    error = ProviderSchemaChangeError("boom", context)

    logger.error("failed", extra={ERROR_ATTRIBUTE: error})

    assert error.message == "boom"
    assert error.context == context
    assert error.context is context


def test_a_record_without_an_error_has_no_error_field() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)

    logger.info("fine")

    assert "error" not in records_from(stream)[0]


# --------------------------------------------------------------------------
# Levels and repeated configuration
# --------------------------------------------------------------------------


def test_level_filtering_works() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.WARNING)

    logger.debug("debug")
    logger.info("info")
    logger.warning("warning")
    logger.error("error")

    messages = [record["message"] for record in records_from(stream)]
    assert messages == ["warning", "error"]


def test_the_level_is_explicitly_configurable() -> None:
    stream = io.StringIO()
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.DEBUG)

    logger.debug("now visible")

    assert records_from(stream)[0]["message"] == "now visible"


def test_repeated_configuration_does_not_duplicate_records() -> None:
    stream = io.StringIO()

    configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)
    configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)
    logger = configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO)
    logger.info("once")

    assert len(logger.handlers) == 1
    assert [record["message"] for record in records_from(stream)] == ["once"]


def test_reconfiguring_to_quiet_silences_a_previously_loud_logger() -> None:
    stream = io.StringIO()
    configure_logger(LOGGER_NAME, stream=stream, level=logging.INFO).info("loud")

    configure_logger(LOGGER_NAME).info("silent")

    assert [record["message"] for record in records_from(stream)] == ["loud"]


def test_configure_logger_validates_its_arguments() -> None:
    with pytest.raises(TypeError, match=r"logger name must be a string"):
        configure_logger(7)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"must not be blank"):
        configure_logger("   ")
    with pytest.raises(TypeError, match=r"level must be an int logging level, not a bool"):
        configure_logger(LOGGER_NAME, level=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"level must be an int"):
        configure_logger(LOGGER_NAME, level="INFO")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Formatter used directly
# --------------------------------------------------------------------------


def test_the_formatter_produces_sorted_compact_json() -> None:
    record = logging.LogRecord(
        name="gm",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    text = StructuredJsonFormatter().format(record)

    assert text == '{"level":"INFO","logger":"gm","message":"hello"}'


def test_the_formatter_ignores_a_foreign_context_object() -> None:
    """Only a real LogContext contributes fields; no repr fallback."""
    record = logging.LogRecord(
        name="gm",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.__dict__[CONTEXT_ATTRIBUTE] = {"model_version": "sneaky"}

    parsed = json.loads(StructuredJsonFormatter().format(record))

    assert "model_version" not in parsed


# --------------------------------------------------------------------------
# Import side effects
# --------------------------------------------------------------------------


IMPORT_PROBE = """
import io, sys
captured_out, captured_err = io.StringIO(), io.StringIO()
sys.stdout, sys.stderr = captured_out, captured_err
import greenmachine
import greenmachine.common
import greenmachine.common.logging
import greenmachine.domain
import logging as stdlib_logging
sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
print("OUT:" + captured_out.getvalue())
print("ERR:" + captured_err.getvalue())
print("ROOT_HANDLERS:" + str(len(stdlib_logging.root.handlers)))
print("ROOT_LEVEL:" + str(stdlib_logging.root.level))
"""


def test_importing_the_package_emits_nothing_and_installs_no_handler() -> None:
    """Checked in a fresh subprocess, so no earlier test can mask a side effect."""
    from tests.network_guard.guarded_child import guarded_python_command

    completed = subprocess.run(
        guarded_python_command("-c", IMPORT_PROBE),
        capture_output=True,
        text=True,
        check=True,
    )
    lines = dict(
        line.split(":", 1) for line in completed.stdout.strip().splitlines() if ":" in line
    )

    assert lines["OUT"] == ""
    assert lines["ERR"] == ""
    assert lines["ROOT_HANDLERS"] == "0"
    assert lines["ROOT_LEVEL"] == str(logging.WARNING)
