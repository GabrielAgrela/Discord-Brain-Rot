import logging
import logging.handlers
import os
import sys
from datetime import date
from pathlib import Path
from config import LOGS_DIR


class DailyLogFileHandler(logging.FileHandler):
    """
    File handler that writes directly to YYYY-MM-DD.log and rolls by date.
    """

    def __init__(
        self,
        logs_dir: Path,
        backup_count: int = 30,
        encoding: str | None = None,
    ) -> None:
        """
        Initialize the handler for the current day's log file.

        Args:
            logs_dir: Directory where daily log files are stored.
            backup_count: Number of daily log files to keep.
            encoding: File encoding for log output.
        """
        self.logs_dir = Path(logs_dir)
        self.backup_count = backup_count
        self.current_date = date.today()
        super().__init__(
            self._filename_for(self.current_date),
            mode="a",
            encoding=encoding,
        )

    def emit(self, record: logging.LogRecord) -> None:
        """
        Write a log record, switching files first if the date changed.

        Args:
            record: Log record emitted by the logging framework.
        """
        self._rollover_if_needed()
        super().emit(record)

    def _filename_for(self, log_date: date) -> str:
        return str(self.logs_dir / f"{log_date:%Y-%m-%d}.log")

    def _rollover_if_needed(self) -> None:
        today = date.today()
        if today == self.current_date:
            return

        if self.stream:
            self.stream.close()
            self.stream = None

        self.current_date = today
        self.baseFilename = self._filename_for(today)
        self.stream = self._open()
        self._delete_old_logs()

    def _delete_old_logs(self) -> None:
        if self.backup_count <= 0:
            return

        daily_logs = sorted(self.logs_dir.glob("????-??-??.log"))
        for old_log in daily_logs[:-self.backup_count]:
            try:
                old_log.unlink()
            except OSError:
                logging.getLogger(__name__).warning(
                    "Failed to delete old log file %s",
                    old_log,
                    exc_info=True,
                )


class StreamToLogger:
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

def setup_logging():
    """
    Sets up daily rotating logging and redirects stdout/stderr to the logger.
    """
    # Ensure logs directory exists
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Suppress noisy discord.player errors (fallback probe works fine, tracebacks are spam)
    logging.getLogger('discord.player').setLevel(logging.CRITICAL)

    # Prevent duplicate handlers if setup_logging is called multiple times
    if logger.handlers:
        return

    # Write directly to YYYY-MM-DD.log. TimedRotatingFileHandler appends its
    # own date suffix during rollover, which can create doubled names when the
    # active file is already date-stamped.
    file_handler = DailyLogFileHandler(
        logs_dir=LOGS_DIR,
        backup_count=30,
        encoding="utf-8"
    )
    
    # Format: [2026-01-07 20:35:46] [INFO] Message
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Add dedicated error file handler for ERROR and CRITICAL logs
    error_filename = LOGS_DIR / "errors.log"
    error_handler = logging.handlers.RotatingFileHandler(
        filename=error_filename,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)  # Only ERROR and CRITICAL
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    # Also log to console
    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Redirect stdout and stderr
    sys.stdout = StreamToLogger(logger, logging.INFO)
    sys.stderr = StreamToLogger(logger, logging.ERROR)

    logging.info("Logging initialized. Output redirected to log file.")
