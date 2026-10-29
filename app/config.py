"""应用配置、目录与事件日志。"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

APP_NAME = "EA Game Doctor"
APP_NAME_CN = "EA 启动医生"
APP_VERSION = "1.2.1"
APP_TAGLINE = "检测并修复 EA 游戏的激活弹窗 / 启动被拦截问题"

BASE_DIR_CANDIDATES: list[Path] = []


def _pick_base_dir() -> Path:
    """优先用户 AppData；被安全策略拦截时退回到程序目录下的 data/。

    这样在受限环境（例如某些沙箱）里也能正常保存日志与备份。
    """
    candidates: list[Path] = []
    override = os.environ.get("EAGAMEDOCTOR_HOME")
    if override:
        candidates.append(Path(override))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "EAGameDoctor")
    candidates.append(Path.home() / ".eagamedoctor")
    candidates.append(Path(__file__).resolve().parents[1] / "data")
    for candidate in candidates:
        BASE_DIR_CANDIDATES.append(candidate)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return Path(__file__).resolve().parents[1] / "data"


BASE_DIR = _pick_base_dir()
BASE_DIR_KIND = "fallback" if BASE_DIR != (Path(os.environ.get("LOCALAPPDATA", "")) / "EAGameDoctor") else "user"
if os.environ.get("EAGAMEDOCTOR_HOME"):
    BASE_DIR_KIND = "custom"
LOGS_DIR = BASE_DIR / "logs"
BACKUPS_DIR = BASE_DIR / "backups"
REPORTS_DIR = BASE_DIR / "reports"
CONFIG_FILE = BASE_DIR / "config.json"

EA_SUPPORT_LINK = "https://help.ea.com/zh-cn/help/pc/link-ea-and-steam/"


def is_restricted_environment() -> bool:
    """是否为受限运行环境（写不了 AppData / 进程可见性可能不完整）。"""
    return BASE_DIR_KIND == "fallback"


def bootstrap_dirs() -> None:
    for directory in (BASE_DIR, LOGS_DIR, BACKUPS_DIR, REPORTS_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    monitor_enabled: bool = True
    interval_ms: int = 1800
    auto_fix: bool = True
    auto_fix_profile: str = "quick"
    deep_profile: str = "deep"
    verify_timeout: float = 75.0
    prefer_steam: bool = True
    notify: bool = True
    minimize_to_tray: bool = True
    confirm_deep: bool = True
    last_game_key: str = ""
    total_fixes: int = 0
    total_detections: int = 0

    def save(self) -> None:
        bootstrap_dirs()
        try:
            CONFIG_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    @classmethod
    def load(cls) -> "Settings":
        settings = cls()
        if CONFIG_FILE.is_file():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for key, value in data.items():
                        if hasattr(settings, key) and type(getattr(settings, key)) is type(value):
                            setattr(settings, key, value)
            except (OSError, json.JSONDecodeError):
                pass
        return settings


# ---------------------------------------------------------------------------
# 事件日志
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Event:
    ts: float
    level: str  # info / success / warn / error / action
    title: str
    message: str = ""
    source: str = "app"

    @property
    def time_text(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime("%H:%M:%S")


class EventLog:
    """内存环形缓冲 + 文件落盘；UI 通过 subscribe 收到实时事件。"""

    def __init__(self, max_items: int = 1200, file_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._items: list[Event] = []
        self._max = max_items
        self._subscribers: list[Callable[[Event], None]] = []
        self._file = file_path
        self._file_lock = threading.Lock()
        if self._file is not None:
            bootstrap_dirs()

    # -- 读取 ---------------------------------------------------------------
    def items(self) -> list[Event]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    # -- 订阅 ---------------------------------------------------------------
    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    # -- 写入 ---------------------------------------------------------------
    def add(self, level: str, title: str, message: str = "", source: str = "app") -> Event:
        event = Event(ts=time.time(), level=level, title=title, message=message, source=source)
        with self._lock:
            self._items.append(event)
            if len(self._items) > self._max:
                del self._items[: len(self._items) - self._max]
            subscribers = list(self._subscribers)
        self._write_file(event)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                continue
        return event

    def info(self, title: str, message: str = "", source: str = "app") -> Event:
        return self.add("info", title, message, source)

    def success(self, title: str, message: str = "", source: str = "app") -> Event:
        return self.add("success", title, message, source)

    def warn(self, title: str, message: str = "", source: str = "app") -> Event:
        return self.add("warn", title, message, source)

    def error(self, title: str, message: str = "", source: str = "app") -> Event:
        return self.add("error", title, message, source)

    def action(self, title: str, message: str = "", source: str = "app") -> Event:
        return self.add("action", title, message, source)

    def _write_file(self, event: Event) -> None:
        if self._file is None:
            return
        stamp = datetime.fromtimestamp(event.ts).strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] [{event.level.upper():7}] [{event.source}] {event.title} {event.message}".rstrip()
        with self._file_lock:
            try:
                with self._file.open("a", encoding="utf-8") as handle:  # type: ignore[union-attr]
                    handle.write(line + "\n")
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def write_report(name: str, payload: dict) -> Path:
    bootstrap_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    path = REPORTS_DIR / f"{stamp}-{safe_name}.json"
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass
    return path


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"
