"""基础组件测试：事件日志与配置默认值。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import EventLog, Settings, human_size, is_restricted_environment  # noqa: E402


def test_event_log_ring_and_subscribe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log = EventLog(max_items=5, file_path=Path(tmp) / "app.log")
        received = []
        log.subscribe(received.append)
        for index in range(8):
            log.info(f"事件 {index}", "内容")
        assert len(log.items()) == 5
        assert log.items()[-1].title == "事件 7"
        assert len(received) == 8
        text = (Path(tmp) / "app.log").read_text(encoding="utf-8")
        assert "事件 7" in text


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.monitor_enabled is True
    assert settings.auto_fix is True
    assert settings.auto_fix_profile in ("quick", "deep")
    assert settings.verify_timeout >= 20
    assert settings.total_fixes == 0


def test_restricted_environment_flag() -> None:
    value = is_restricted_environment()
    assert isinstance(value, bool)


def test_human_size() -> None:
    assert human_size(512) == "512 B"
    assert "KB" in human_size(4096)
    assert "MB" in human_size(5 * 1024 * 1024)


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"config: {len(tests)} tests passed")
