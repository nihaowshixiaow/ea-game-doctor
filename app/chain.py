"""启动链路分析：Steam 是否真的拉起了游戏、EA 授权握手有没有完成。

思路：不猜，直接读两份一手日志比对时间线：
1. Steam `logs\\gameprocess_log.txt`：Steam 有没有为 AppID 创建进程、进程活了几秒；
2. EA Core `logs\\<id>.log`：游戏起来后，EA 有没有拉起 activation.exe / 授权握手是否 20 秒超时；
3. 授权缓存 `.dlf`：这次启动之后，EA 有没有真的下发新的授权文件。

这三件事放在一起，就能把「启动方式问题」和「账号授权问题」分开。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import catalog, eaapp
from .discovery import InstalledGame
from .win32 import path_under

STEAM_TIME_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+AppID\s+(\d+)\s+(.*)$")
EA_TIME_RE = re.compile(r"\[\s*(\d{1,2}):(\d{2}):(\d{2})(?::(\d{1,3}))?\s*\]")


@dataclass(slots=True)
class SteamEvent:
    when: datetime | None
    kind: str  # start / stop
    pid: int | None
    detail: str

    @property
    def time_text(self) -> str:
        return self.when.strftime("%H:%M:%S") if self.when else "?"


@dataclass(slots=True)
class ActivationEvent:
    time_text: str
    time_of_day: float  # 秒
    exe: str
    game_dir: str | None
    portal_timeout: bool = False


@dataclass(slots=True)
class ChainAnalysis:
    appid: int | None
    game_name: str
    steam_events: list[SteamEvent] = field(default_factory=list)
    last_start: SteamEvent | None = None
    last_stop: SteamEvent | None = None
    activation_events: list[ActivationEvent] = field(default_factory=list)
    last_activation: ActivationEvent | None = None
    portal_timeouts: int = 0
    license_files_after: int = 0
    legacy_license_age_days: float | None = None
    ea_mode: str = "unknown"
    cause: str = "unknown"
    cause_label: str = ""
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[str]:
        out: list[str] = []
        if self.last_start:
            out.append(f"Steam 启动记录：{self.last_start.when.strftime('%m-%d %H:%M:%S') if self.last_start.when else '?'}（PID {self.last_start.pid or '?'}）")
        else:
            out.append("Steam 日志里没有该 AppID 的启动记录")
        if self.last_stop:
            out.append(f"游戏进程退出：{self.last_stop.time_text} {self.last_stop.detail[:60]}")
        if self.last_activation:
            out.append(f"EA 拉起激活界面：{self.last_activation.time_text}（activation.exe）")
        if self.portal_timeouts:
            out.append(f"EA 授权握手超时：{self.portal_timeouts} 次（每次 20 秒，cmd_portal_command 无响应）")
        out.append(f"启动后新增授权缓存：{self.license_files_after} 个")
        if self.ea_mode != "unknown":
            out.append(f"EA App 运行模式：{self.ea_mode}")
        if getattr(self, "legacy_license_age_days", None) is not None:
            out.append(f"BF3 老授权缓存年龄：{self.legacy_license_age_days:.0f} 天（>60 天视为过期，是本次修复的关键）")
        return out


# ---------------------------------------------------------------------------
# 纯解析函数（便于测试）
# ---------------------------------------------------------------------------
def parse_steam_events(text: str, appid: int) -> list[SteamEvent]:
    events: list[SteamEvent] = []
    for raw in text.splitlines():
        match = STEAM_TIME_RE.match(raw.strip())
        if not match or int(match.group(2)) != appid:
            continue
        try:
            when = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            when = None
        detail = match.group(3)
        kind = "stop" if "no longer tracking" in detail else "start"
        pid_match = re.search(r"PID\s+(\d+)", detail)
        events.append(
            SteamEvent(
                when=when,
                kind=kind,
                pid=int(pid_match.group(1)) if pid_match else None,
                detail=detail,
            )
        )
    return events


def parse_ea_core(text: str) -> tuple[list[ActivationEvent], int]:
    """返回 (activation.exe 启动事件, cmd_portal_command 超时次数)。"""
    activations: list[ActivationEvent] = []
    timeouts = 0
    events: list[ActivationEvent] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        stamp = EA_TIME_RE.search(line)
        if stamp:
            hours, minutes, seconds = int(stamp.group(1)), int(stamp.group(2)), int(stamp.group(3))
            millis = int(stamp.group(4) or 0)
            utc_seconds = hours * 3600 + minutes * 60 + seconds + millis / 1000
            # EA Core 日志用 UTC；Steam 日志用本地时间，统一成本地时间再比较
            local_seconds = (utc_seconds - time.timezone) % 86400
            time_of_day = local_seconds
            local_h = int(local_seconds // 3600)
            local_m = int((local_seconds % 3600) // 60)
            local_s = int(local_seconds % 60)
            time_text = f"{local_h:02d}:{local_m:02d}:{local_s:02d}"
        else:
            time_of_day = None
            time_text = ""
        if "cmd_portal_command" in line and "timed out" in line:
            timeouts += 1
            continue
        proc = re.search(r"CreateProcessW\(\s*([^,]+?)\s*,", line)
        if not proc:
            continue
        exe = proc.group(1).strip().strip('"')
        if "activation" not in Path(exe).name.lower():
            continue
        game_dir = None
        parent = Path(exe).parent
        if parent.name.lower() == "core":
            game_dir = str(parent.parent)
        events.append(
            ActivationEvent(
                time_text=time_text or "?",
                time_of_day=time_of_day if time_of_day is not None else 0.0,
                exe=exe,
                game_dir=game_dir,
                portal_timeout=False,
            )
        )
    activations = events
    return activations, timeouts


def _license_files_after(license_dir: Path, timestamp: float) -> int:
    try:
        return sum(1 for path in license_dir.glob("*.dlf") if path.stat().st_mtime > timestamp)
    except OSError:
        return 0


def analyze_texts(
    *,
    appid: int | None,
    game_name: str,
    steam_text: str,
    ea_core_text: str,
    license_after: int,
    ea_mode: str = "unknown",
    activation_after_launch: bool | None = None,
    game_dir: str | None = None,
    stale_legacy_license: bool = False,
    legacy_license_age_days: float | None = None,
) -> ChainAnalysis:
    analysis = ChainAnalysis(appid=appid, game_name=game_name, ea_mode=ea_mode)
    if appid:
        events = parse_steam_events(steam_text, appid)
        analysis.steam_events = events
        starts = [event for event in events if event.kind == "start"]
        stops = [event for event in events if event.kind == "stop"]
        # 展示时优先选「真正的启动入口」事件（EASteamLauncher / steam2ea / 游戏 exe），而不是随后派生的子进程
        launch_like = [
            event
            for event in starts
            if "EASteamLauncher" in event.detail or "steam2ea" in event.detail
        ]
        analysis.last_start = (launch_like or starts)[-1] if starts else None
        analysis.last_stop = stops[-1] if stops else None

    activations, timeouts = parse_ea_core(ea_core_text)
    if game_dir:
        # 只保留属于这个游戏的 activation.exe 记录（按安装目录归属）
        filtered = [event for event in activations if event.game_dir and path_under(event.game_dir, game_dir)]
        if filtered:
            activations = filtered
        elif any(event.game_dir for event in activations):
            activations = []
    analysis.activation_events = activations
    analysis.last_activation = activations[-1] if activations else None
    analysis.portal_timeouts = timeouts
    analysis.license_files_after = license_after
    if legacy_license_age_days is not None:
        analysis.legacy_license_age_days = legacy_license_age_days

    # 激活事件是否发生在某次 Steam 启动之后（比较本地时间；给 5 秒容差）
    if activation_after_launch is None:
        activation_after_launch = False
        if analysis.last_activation is not None:
            for event in analysis.steam_events:
                if event.kind != "start" or event.when is None:
                    continue
                start_seconds = event.when.hour * 3600 + event.when.minute * 60 + event.when.second
                if analysis.last_activation.time_of_day >= start_seconds - 5:
                    activation_after_launch = True
                    break

    if not analysis.last_start:
        analysis.cause = "steam_not_launched"
        analysis.confidence = 0.9
        analysis.cause_label = "Steam 没有真正启动游戏"
        analysis.notes.append("Steam 的 gameprocess_log 里没有该 AppID 的启动记录：可能是 Steam 没登录 / 没有授权 / 本地清单异常。")
    elif not activation_after_launch:
        analysis.cause = "no_activation"
        analysis.confidence = 0.6
        analysis.cause_label = "启动后没有出现激活流程"
        analysis.notes.append("Steam 确实启动了游戏，但没有在 EA Core 日志里看到对应的 activation.exe：可能游戏提前崩溃，或启动链路已修复。")
    elif analysis.portal_timeouts and analysis.license_files_after == 0 and stale_legacy_license:
        analysis.cause = "bf3_license_stale"
        analysis.confidence = 0.95
        analysis.cause_label = "BF3 授权缓存文件过期（可以自动修复）"
        analysis.notes.append("检测到 BF3 老式授权缓存文件（71067.dlf 等）已经很旧：EA 加载它时卡住 20 秒，随后退回到激活界面。")
        analysis.notes.append("修复方式：备份并删除这些陈旧授权缓存 → 重启 EA App（它会重新生成）→ 再从 Steam 启动。")
    elif analysis.portal_timeouts and analysis.license_files_after == 0:
        analysis.cause = "ea_portal_timeout_no_license"
        analysis.confidence = 0.93
        analysis.cause_label = "EA 授权握手超时，且没有下发新的授权"
        analysis.notes.append("Steam 票据已交给 EA（EASteamLauncher 已启动并解析 offerId），但 EA 在 20 秒内没有完成 cmd_portal_command 握手。")
        analysis.notes.append("启动后授权缓存没有新增：EA 服务端没有针对这个账号下发该游戏的授权。")
        analysis.notes.append("这属于「账号授权 / 账号绑定」问题，不是启动方式问题。")
    elif analysis.license_files_after > 0:
        analysis.cause = "license_cache_stale"
        analysis.confidence = 0.75
        analysis.cause_label = "EA 下发了新授权但游戏仍要求激活"
        analysis.notes.append("EA 在本次启动后下发了新的授权文件，说明账号有授权；问题更可能是旧缓存 / 客户端状态，重试或深度修复通常有效。")
    else:
        analysis.cause = "activation_no_entitlement"
        analysis.confidence = 0.7
        analysis.cause_label = "EA 要求激活（账号侧授权不匹配）"
        analysis.notes.append("Steam 已拉起游戏，但 EA 仍然要求激活：优先核对 EA 账号是否就是拥有该游戏的那个账号。")
    return analysis


def read_steam_log(steam_root: str | None = None) -> str:
    from . import discovery

    root = steam_root or discovery.steam_root_path()
    if not root:
        return ""
    path = Path(root) / "logs" / "gameprocess_log.txt"
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def read_core_log() -> str:
    core_log = eaapp.latest_core_log()
    if core_log is None:
        return ""
    try:
        return core_log.read_bytes().decode("utf-16", errors="ignore")
    except OSError:
        return ""


def analyze_game_text(
    game: InstalledGame,
    steam_text: str,
    ea_core_text: str,
    ea_mode: str | None = None,
) -> ChainAnalysis:
    last_start: float | None = None
    if game.steam_appid and steam_text:
        events = parse_steam_events(steam_text, game.steam_appid)
        starts = [event for event in events if event.kind == "start" and event.when]
        if starts:
            last_start = time.mktime(starts[-1].when.timetuple())
    license_after = _license_files_after(eaapp.LICENSE_DIR, last_start) if last_start else 0
    mode = ea_mode if ea_mode is not None else eaapp.client_mode()
    return analyze_texts(
        appid=game.steam_appid,
        game_name=game.name,
        steam_text=steam_text,
        ea_core_text=ea_core_text,
        license_after=license_after,
        ea_mode=mode,
        game_dir=game.install_dir,
        stale_legacy_license=bool(game.key == "bf3" and eaapp.bf3_license_info().get("stale")),
        legacy_license_age_days=(
            eaapp.bf3_license_info().get("newest_age_days") if game.key == "bf3" else None
        ),
    )


def analyze_game(game: InstalledGame, ea_mode: str | None = None) -> ChainAnalysis:
    return analyze_game_text(game, read_steam_log(), read_core_log(), ea_mode)


