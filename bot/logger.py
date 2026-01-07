import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from config import LOGS_DIR

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

    # Use the current date for the base log filename
    # However, TimedRotatingFileHandler will append its own suffix.
    # To have exactly YYYY-MM-DD.log as the primary file, we can do this:
    log_filename = LOGS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if setup_logging is called multiple times
    if logger.handlers:
        return

    # Create daily rotating file handler
    # 'when="D"' means daily, 'interval=1' means every 1 day
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_filename,
        when="D",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    
    # Format: [2026-01-07 20:35:46] [INFO] Message
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Also log to console
    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Redirect stdout and stderr
    sys.stdout = StreamToLogger(logger, logging.INFO)
    sys.stderr = StreamToLogger(logger, logging.ERROR)

    logging.info("Logging initialized. Output redirected to log file.")
