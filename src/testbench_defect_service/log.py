import logging
import re
import sys
from logging.config import dictConfig

from sanic.logging.color import LEVEL_COLORS, Colors
from sanic.logging.formatter import CONTROL_LIMIT_END, EXCEPTION_LINE_RE, FILE_LINE_RE

from testbench_defect_service.models.logging import LoggingConfig


class BaseFormatter(logging.Formatter):
    """Base formatter with shared time formatting and access log detection."""

    ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    default_time_format = "%Y-%m-%d %H:%M:%S"
    default_msec_format = "%s,%03d"

    def formatTime(self, record: logging.LogRecord, datefmt=None):  # noqa: N802
        """Format time with milliseconds and optional colorization."""
        timestamp = super().formatTime(record, datefmt)
        return self._colorize_time(timestamp)

    def _colorize_time(self, timestamp: str) -> str:
        """Override in subclasses to add/remove colors."""
        return timestamp

    def _is_access_log(self, record: logging.LogRecord) -> bool:
        """Check if record is from sanic.access logger."""
        return record.name == "sanic.access"

    def _get_access_attrs(self, record: logging.LogRecord) -> dict[str, str]:
        """Safely extract access log attributes."""
        return {
            "host": getattr(record, "host", "-"),
            "request": getattr(record, "request", "-"),
            "status": getattr(record, "status", "-"),
            "byte": getattr(record, "byte", "-"),
            "duration": getattr(record, "duration", "-"),
        }


class ConsoleFormatter(BaseFormatter):
    """Formatter with Sanic-style colors for console output."""

    default_time_format = "%H:%M:%S"

    def format(self, record: logging.LogRecord):
        record_copy = self._make_record_copy(record)

        if self._is_access_log(record_copy):
            return self._format_access_log(record_copy)

        color = LEVEL_COLORS.get(record_copy.levelno, "")
        record_copy.levelname = f"{color}{record_copy.levelname}{Colors.END}"

        return super().format(record_copy)

    def _colorize_time(self, timestamp: str) -> str:
        return f"{Colors.GREY}{timestamp}{Colors.END}"

    def _format_access_log(self, record: logging.LogRecord):
        """Format access log with Sanic-style colors and layout."""
        if record.levelno == logging.INFO:
            record.levelname = f"{Colors.SANIC}ACCESS{Colors.END}"

        attrs = self._get_access_attrs(record)

        # Calculate alignment for terminal
        right_padding = CONTROL_LIMIT_END.format(
            right=len(str(attrs["status"]))
            + len(str(attrs["byte"]))
            + len(str(attrs["duration"]))
            + 1
        )

        # Build colored message
        record.msg = (
            f"{Colors.PURPLE}{attrs['host']} "
            f"{Colors.BLUE}{Colors.BOLD}{attrs['request']}{Colors.END} "
            f"{right_padding}{attrs['status']} "
            f"{attrs['byte']} "
            f"{Colors.GREY}{attrs['duration']}{Colors.END}"
        )
        record.args = ()

        return super().format(record)

    def _make_record_copy(self, record: logging.LogRecord) -> logging.LogRecord:
        """Create a shallow copy to avoid side effects."""
        return logging.makeLogRecord(record.__dict__)


class DebugConsoleFormatter(ConsoleFormatter):
    """Formatter that adds colored tracebacks for debug console output."""

    def formatException(self, ei):  # noqa: N802
        """Format exception with colored traceback lines."""
        orig = super().formatException(ei)
        lines = orig.splitlines()

        return "\n".join(
            self._colorize_traceback_line(line, idx, len(lines)) for idx, line in enumerate(lines)
        )

    def _colorize_traceback_line(self, line: str, idx: int, total: int) -> str:
        """Colorize a single traceback line based on its pattern."""
        if line.startswith("  File"):
            return self._color_file_line(line)
        if line.startswith("    "):
            return f"{Colors.YELLOW}{line}{Colors.END}"
        if self._is_exception_line(line, idx, total):
            return self._color_exception_line(line)
        return line

    def _is_exception_line(self, line: str, idx: int, total: int) -> bool:
        """Check if line is an exception message."""
        return "Error" in line or "Exception" in line or idx == total - 1

    def _color_exception_line(self, line: str) -> str:
        """Color exception name and message."""
        if match := EXCEPTION_LINE_RE.match(line):
            exc = match.group("exc")
            message = match.group("message")
            return (
                f"{Colors.SANIC}{Colors.BOLD}{exc}{Colors.END}: {Colors.BOLD}{message}{Colors.END}"
            )
        return line

    def _color_file_line(self, line: str) -> str:
        """Color file path, line number, and function name."""
        if match := FILE_LINE_RE.search(line):
            path = match.group("path")
            line_num = match.group("line_num")
            location = match.group("location")
            return (
                f'  File "{path}", line {Colors.CYAN}{Colors.BOLD}{line_num}{Colors.END}, '
                f"in {Colors.BLUE}{Colors.BOLD}{location}{Colors.END}"
            )
        return line


class FileFormatter(BaseFormatter):
    """Formatter that removes ANSI sequences for file output."""

    def format(self, record: logging.LogRecord):
        record_copy = self._make_record_copy(record)

        if self._is_access_log(record_copy):
            return self._format_access_log(record_copy)

        # Format normally then strip ANSI
        message = super().format(record_copy)
        return self.ANSI_RE.sub("", message)

    def _format_access_log(self, record: logging.LogRecord) -> str:
        """Format access log without colors or alignment."""
        if record.levelno == logging.INFO:
            record.levelname = "ACCESS"

        attrs = self._get_access_attrs(record)

        # Simple space-separated format (no alignment needed for files)
        record.msg = (
            f"{attrs['host']} {attrs['request']} "
            f"{attrs['status']} {attrs['byte']} {attrs['duration']}"
        )
        record.args = ()

        message = super().format(record)
        return self.ANSI_RE.sub("", message)

    def _make_record_copy(self, record: logging.LogRecord) -> logging.LogRecord:
        return logging.makeLogRecord(record.__dict__)


def get_logging_dict(config: LoggingConfig, debug: bool = False) -> dict:
    """
    Create a logging configuration dictionary compatible with logging.config.dictConfig.

    This configuration ensures that:
    - Sanic's loggers (sanic.root, sanic.error, sanic.access) use our settings
    - Both console and file handlers are configured
    - Logger level is set to minimum of handler levels to allow all messages through
    - Debug mode overrides log levels to DEBUG and uses DebugConsoleFormatter

    Args:
        config: LoggingConfig instance with console and file settings
        debug: Whether debug mode is active (overrides log levels to DEBUG)
    Returns:
        Dictionary compatible with logging.config.dictConfig
    """

    if debug:
        console_level = logging.DEBUG
        file_level = logging.DEBUG
        console_formatter_class = "testbench_defect_service.log.DebugConsoleFormatter"
    else:
        console_level = getattr(logging, config.console.log_level)
        file_level = getattr(logging, config.file.log_level)
        console_formatter_class = "testbench_defect_service.log.ConsoleFormatter"

    min_level = min(console_level, file_level)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            "sanic.root": {
                "level": min_level,
                "handlers": ["console", "file"],
            },
            "sanic.error": {
                "level": min_level,
                "handlers": ["console", "file"],
                "propagate": True,
                "qualname": "sanic.error",
            },
            "sanic.access": {
                "level": min_level,
                "handlers": ["console", "file"],
                "propagate": True,
                "qualname": "sanic.access",
            },
            "sanic.server": {
                "level": min_level,
                "handlers": ["console", "file"],
                "propagate": True,
                "qualname": "sanic.server",
            },
            "sanic.websockets": {
                "level": min_level,
                "handlers": ["console", "file"],
                "propagate": True,
                "qualname": "sanic.websockets",
            },
            "asyncio": {
                "level": "ERROR",
                "handlers": ["console", "file"],
                "propagate": True,
            },
            "testbench_defect_service": {
                "level": min_level,
                "handlers": ["console", "file"],
                "propagate": True,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "level": console_level,
                "stream": sys.stdout,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "file",
                "level": file_level,
                "filename": config.file.file_path,
                "maxBytes": 10 * 1024 * 1024,  # 10 MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "formatters": {
            "console": {
                "()": console_formatter_class,
                "format": config.console.log_format,
            },
            "file": {
                "()": "testbench_defect_service.log.FileFormatter",
                "format": config.file.log_format,
            },
        },
    }


def setup_logging(config: LoggingConfig, debug: bool = False) -> None:
    """
    Configure Python logging to handle both console and file output.

    This function configures all loggers (including Sanic's) to use the specified
    console and file logging settings. In debug mode, forces DEBUG level and uses
    colored traceback formatter.

    Args:
        config: LoggingConfig instance with console and file settings
        debug: Whether debug mode is active (overrides log levels to DEBUG)
    """
    logging_dict = get_logging_dict(config, debug=debug)
    dictConfig(logging_dict)


logger = logging.getLogger("testbench_defect_service")
