import logging
from datetime import date as real_date

import bot.logger as logger_module
from bot.logger import DailyLogFileHandler


class FakeDate(real_date):
    current = real_date(2026, 4, 27)

    @classmethod
    def today(cls):
        return cls.current


def test_daily_log_handler_rolls_to_plain_date_filename(tmp_path, monkeypatch):
    """Daily logging should never append a second date suffix to log filenames."""
    monkeypatch.setattr(logger_module, "date", FakeDate)
    FakeDate.current = real_date(2026, 4, 27)
    handler = DailyLogFileHandler(tmp_path, backup_count=30, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))

    try:
        handler.emit(logging.LogRecord("test", logging.INFO, __file__, 1, "first", (), None))
        FakeDate.current = real_date(2026, 4, 28)
        handler.emit(logging.LogRecord("test", logging.INFO, __file__, 2, "second", (), None))
    finally:
        handler.close()

    assert (tmp_path / "2026-04-27.log").read_text(encoding="utf-8").strip() == "first"
    assert (tmp_path / "2026-04-28.log").read_text(encoding="utf-8").strip() == "second"
    assert not list(tmp_path.glob("*.log.*"))


def test_daily_log_handler_prunes_old_daily_logs(tmp_path, monkeypatch):
    """Daily log pruning should keep the newest configured date-stamped files."""
    monkeypatch.setattr(logger_module, "date", FakeDate)
    for day in range(24, 28):
        (tmp_path / f"2026-04-{day}.log").write_text("old\n", encoding="utf-8")

    FakeDate.current = real_date(2026, 4, 27)
    handler = DailyLogFileHandler(tmp_path, backup_count=2, encoding="utf-8")

    try:
        FakeDate.current = real_date(2026, 4, 28)
        handler.emit(logging.LogRecord("test", logging.INFO, __file__, 1, "new", (), None))
    finally:
        handler.close()

    assert sorted(path.name for path in tmp_path.glob("*.log")) == [
        "2026-04-27.log",
        "2026-04-28.log",
    ]
