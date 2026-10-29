"""激活弹窗检测：把「窗口 + 进程 + 安装目录」综合成一个可解释的判定。

设计原则：
1. 先看进程，再看窗口。activation.exe 从游戏目录启动 = EA 的激活 UI，置信度最高。
2. 任何一个信号都不单独成立，输出带证据链，UI 里可以给用户看。
3. 纯函数 classify() 便于单元测试，真实扫描另走 scan()。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog, discovery, eaapp
from .discovery import InstalledGame
from .win32 import ProcessInfo, WindowInfo, enum_windows, list_processes, path_under, screen_size

KIND_ACTIVATION = "activation_dialog"

_CORE_SIGNAL_CACHE: dict = {"mtime": 0.0, "checked": 0.0, "data": None}
KIND_EA_WINDOW = "ea_game_window"
KIND_BLOCKED = "blocked_launch"

ACTIVATION_KEYWORDS = (
    "could not activate",
    "cannot activate",
    "couldn't activate",
    "unable to activate",
    "not activate",
    "activation",
    "product key",
    "无法激活",
    "未能激活",
    "激活失败",
    "需要激活",
    "产品密钥",
    "激活码",
    "输入密钥",
)


@dataclass(slots=True)
class Issue:
    kind: str
    game_key: str | None
    game_name: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    hwnd: int | None = None
    pid: int | None = None
    proc_name: str = ""
    title: str = ""
    cls: str = ""

    @property
    def signature(self) -> str:
        return f"{self.kind}|{self.game_key or '-'}|{self.hwnd or '-'}|{self.pid or '-'}"

    @property
    def kind_label(self) -> str:
        return {
            KIND_ACTIVATION: "激活弹窗",
            KIND_EA_WINDOW: "EA 窗口疑似激活失败",
            KIND_BLOCKED: "游戏被拦截",
        }.get(self.kind, self.kind)

    @property
    def requires_action(self) -> bool:
        return self.kind in (KIND_ACTIVATION, KIND_BLOCKED, KIND_EA_WINDOW)


@dataclass(slots=True)
class Detection:
    issues: list[Issue]
    game_windows: list[WindowInfo]
    ea_windows: list[WindowInfo]
    game_processes: list[ProcessInfo]
    screen: tuple[int, int]
    scanned_at: float = field(default_factory=time.time)
    running_keys: set[str] = field(default_factory=set)

    @property
    def primary(self) -> Issue | None:
        return self.issues[0] if self.issues else None

    @property
    def healthy(self) -> bool:
        return not self.issues

    @property
    def issue_games(self) -> list[str]:
        return sorted({issue.game_name for issue in self.issues if issue.game_name})

    def summary(self) -> str:
        if not self.issues:
            if self.game_windows:
                names = "、".join({catalog.match_game_text(w.title).name if catalog.match_game_text(w.title) else w.title for w in self.game_windows})
                return f"运行正常（游戏窗口: {names}）"
            return "未发现异常窗口"
        primary = self.issues[0]
        return f"发现 {len(self.issues)} 个问题，首要：{primary.kind_label}（{primary.game_name or '未知游戏'}）"


# ---------------------------------------------------------------------------
# 纯函数：判定
# ---------------------------------------------------------------------------
def _normalized(text: str) -> str:
    return catalog.normalize_title(text or "")


def _has_activation_keyword(text: str) -> bool:
    norm = _normalized(text)
    return any(keyword in norm for keyword in ACTIVATION_KEYWORDS)


def _dialog_like(window: WindowInfo, screen: tuple[int, int]) -> bool:
    width, height = window.width, window.height
    if width <= 0 or height <= 0:
        return False
    if not (160 <= width <= 1400 and 90 <= height <= 1000):
        return False
    screen_area = max(1, screen[0] * screen[1])
    if (width * height) / screen_area > 0.6:
        return False
    return not window.minimized


def _game_from_title(title: str, games: list[InstalledGame]) -> InstalledGame | None:
    definition = catalog.match_game_text(title)
    if definition is None:
        return None
    for game in games:
        if game.key == definition.key:
            return game
    return None


def _game_from_exe(exe: str | None, games: list[InstalledGame]) -> InstalledGame | None:
    """按 exe 路径定位游戏；路径不匹配时按 exe 文件名 / 目录名兜底（覆盖移动过的安装目录）。"""
    game = discovery.resolve_game_for_path(exe, games)
    if game is not None or not exe:
        return game
    name = Path(exe).name.lower()
    parent = Path(exe).parent.name
    for candidate in games:
        if candidate.exe and Path(candidate.exe).name.lower() == name:
            return candidate
        definition = catalog.BY_KEY.get(candidate.key)
        if definition is not None and name in {item.lower() for item in definition.exe_names}:
            return candidate
        if parent and catalog.match_game_text(parent) is not None:
            matched = catalog.match_game_text(parent)
            if matched is not None and matched.key == candidate.key:
                return candidate
    return None


def _game_from_process(proc: ProcessInfo, games: list[InstalledGame]) -> InstalledGame | None:
    """进程 -> 游戏：先看 exe 路径，再看进程名（bf3.exe 等），最后看窗口标题在别处处理。"""
    game = _game_from_exe(proc.exe, games)
    if game is not None:
        return game
    name = proc.name_lower
    if not name:
        return None
    for candidate in games:
        definition = catalog.BY_KEY.get(candidate.key)
        if definition is not None and name in {item.lower() for item in definition.exe_names}:
            return candidate
        if candidate.exe and Path(candidate.exe).name.lower() == name:
            return candidate
    return None


def _activation_processes(processes: dict[int, ProcessInfo], games: list[InstalledGame]) -> list[tuple[ProcessInfo, InstalledGame | None]]:
    result: list[tuple[ProcessInfo, InstalledGame | None]] = []
    for proc in processes.values():
        low = proc.name_lower
        if not low.startswith("activation"):
            continue
        game = _game_from_exe(proc.exe, games)
        result.append((proc, game))
    return result


def classify(
    windows: list[WindowInfo],
    processes: dict[int, ProcessInfo],
    games: list[InstalledGame],
    screen: tuple[int, int] = (0, 0),
    core_signal: dict | None = None,
) -> Detection:
    if not screen or screen[0] <= 1:
        screen = screen_size()
    issues: list[Issue] = []
    game_windows: list[WindowInfo] = []
    ea_windows: list[WindowInfo] = []
    game_processes: list[ProcessInfo] = []
    running_keys: set[str] = set()
    seen_signatures: set[str] = set()

    def push(issue: Issue) -> None:
        if issue.signature in seen_signatures:
            return
        seen_signatures.add(issue.signature)
        issues.append(issue)

    ea_running = [p for p in processes.values() if p.name_lower in eaapp.EA_CLIENT_PROCESSES]

    # 1) activation.exe 进程（最可靠的信号）
    for proc, game in _activation_processes(processes, games):
        game_name = game.name if game else "未知游戏"
        evidence = ["EA 激活程序 activation.exe 正在运行"]
        if proc.exe:
            evidence.append(f"程序路径: {proc.exe}")
        if game:
            evidence.append(f"归属游戏目录: {game.install_dir}")
        push(
            Issue(
                kind=KIND_ACTIVATION,
                game_key=game.key if game else None,
                game_name=game_name,
                confidence=0.97 if game else 0.8,
                evidence=evidence,
                pid=proc.pid,
                proc_name=proc.name,
            )
        )

    # 2) 逐窗口判定
    activation_hwnds: set[int] = set()
    for window in windows:
        if not window.visible:
            continue
        owner = processes.get(window.pid)
        owner_name = owner.name_lower if owner else ""
        owner_exe = owner.exe if owner else None
        title = window.title.strip()

        if not title:
            continue

        game_by_path = _game_from_exe(owner_exe, games)
        game_by_title = _game_from_title(title, games)
        dialog_like = _dialog_like(window, screen)

        # 2a) activation.exe 的窗口
        if owner_name.startswith("activation"):
            game = game_by_path or game_by_title
            activation_hwnds.add(window.hwnd)
            evidence = [f"窗口标题: {title}", f"窗口类: {window.cls}", f"尺寸: {window.width}×{window.height}"]
            if game:
                evidence.append(f"归属游戏目录: {game.install_dir}")
            push(
                Issue(
                    kind=KIND_ACTIVATION,
                    game_key=game.key if game else None,
                    game_name=game.name if game else "未知游戏",
                    confidence=0.98 if (game and dialog_like) else 0.9,
                    evidence=evidence,
                    hwnd=window.hwnd,
                    pid=window.pid,
                    proc_name=owner.name if owner else "",
                    title=title,
                    cls=window.cls,
                )
            )
            continue

        # 2b) EA 客户端窗口
        if owner_name in eaapp.EA_CLIENT_PROCESSES or (owner_exe and path_under(owner_exe, str(eaapp.EA_CLIENT_DIR))):
            ea_windows.append(window)
            if _has_activation_keyword(title):
                game = game_by_title or game_by_path
                push(
                    Issue(
                        kind=KIND_ACTIVATION,
                        game_key=game.key if game else None,
                        game_name=game.name if game else "未知游戏",
                        confidence=0.94 if game else 0.9,
                        evidence=[
                            f"EA 客户端窗口标题含激活关键字: {title}",
                            f"进程: {owner.name if owner else '?'}",
                            f"窗口类: {window.cls}",
                        ],
                        hwnd=window.hwnd,
                        pid=window.pid,
                        proc_name=owner.name if owner else "",
                        title=title,
                        cls=window.cls,
                    )
                )
                continue
            if game_by_title and dialog_like:
                push(
                    Issue(
                        kind=KIND_EA_WINDOW,
                        game_key=game_by_title.key,
                        game_name=game_by_title.name,
                        confidence=0.76,
                        evidence=[
                            f"EA 客户端弹出了以游戏命名的窗口: {title}",
                            "窗口尺寸符合错误 / 提示对话框",
                            f"进程: {owner.name if owner else '?'}",
                        ],
                        hwnd=window.hwnd,
                        pid=window.pid,
                        proc_name=owner.name if owner else "",
                        title=title,
                        cls=window.cls,
                    )
                )
                continue
            continue

        # 2c) 游戏自己的窗口（按 exe 路径或窗口标题识别）
        if game_by_path is not None:
            game_windows.append(window)
            running_keys.add(game_by_path.key)
            continue
        if game_by_title is not None and dialog_like and _has_activation_keyword(title):
            push(
                Issue(
                    kind=KIND_EA_WINDOW,
                    game_key=game_by_title.key,
                    game_name=game_by_title.name,
                    confidence=0.78,
                    evidence=[
                        f"窗口标题匹配游戏且含激活关键字: {title}",
                        f"进程: {owner.name if owner else '未知（可能权限受限）'}",
                        f"窗口类: {window.cls}",
                    ],
                    hwnd=window.hwnd,
                    pid=window.pid,
                    proc_name=owner.name if owner else "",
                    title=title,
                    cls=window.cls,
                )
            )
            continue
        if game_by_title is not None and (not dialog_like or (window.width >= 800 and window.height >= 600)):
            game_windows.append(window)
            running_keys.add(game_by_title.key)
            continue
        if game_by_title is not None and _has_activation_keyword(title):
            push(
                Issue(
                    kind=KIND_EA_WINDOW,
                    game_key=game_by_title.key,
                    game_name=game_by_title.name,
                    confidence=0.78,
                    evidence=[
                        f"窗口标题匹配游戏且含激活关键字: {title}",
                        f"进程: {owner.name if owner else '未知（可能权限受限）'}",
                        f"窗口类: {window.cls}",
                    ],
                    hwnd=window.hwnd,
                    pid=window.pid,
                    proc_name=owner.name if owner else "",
                    title=title,
                    cls=window.cls,
                )
            )
            continue

        # 2d) 未知进程但标题明确是激活失败（例如 EA 的辅助程序）
        if _has_activation_keyword(title) and dialog_like and (ea_running or activation_hwnds):
            game = game_by_title
            push(
                Issue(
                    kind=KIND_ACTIVATION,
                    game_key=game.key if game else None,
                    game_name=game.name if game else "未知游戏",
                    confidence=0.62,
                    evidence=[
                        f"未知进程的窗口标题含激活关键字: {title}",
                        f"进程: {owner.name if owner else '?'}",
                    ],
                    hwnd=window.hwnd,
                    pid=window.pid,
                    proc_name=owner.name if owner else "",
                    title=title,
                    cls=window.cls,
                )
            )

    # 3) 游戏进程在跑，但只有激活弹窗、没有游戏窗口
    for proc in processes.values():
        game = _game_from_process(proc, games)
        if game is None:
            continue
        if proc.name_lower.startswith("activation"):
            continue
        game_processes.append(proc)
        running_keys.add(game.key)
        if any(window.pid == proc.pid for window in game_windows):
            continue
        has_activation = any(issue.game_key == game.key for issue in issues if issue.kind == KIND_ACTIVATION)
        if has_activation:
            hwnd = next((issue.hwnd for issue in issues if issue.game_key == game.key and issue.hwnd), None)
            push(
                Issue(
                    kind=KIND_BLOCKED,
                    game_key=game.key,
                    game_name=game.name,
                    confidence=0.88,
                    evidence=[
                        f"游戏进程 {proc.name} 已启动，但没有出现游戏窗口",
                        "同时检测到激活 / 授权提示界面",
                    ],
                    hwnd=hwnd,
                    pid=proc.pid,
                    proc_name=proc.name,
                )
            )

    # 4) 兜底：进程枚举 / 窗口枚举拿不到时，用 EA Core 日志里的 activation.exe 启动记录判定
    if (
        core_signal is not None
        and not game_windows
        and not any(issue.kind == KIND_ACTIVATION for issue in issues)
    ):
        game = None
        signal_dir = core_signal.get("game_dir")
        if signal_dir:
            for candidate in games:
                if candidate.install_dir and path_under(signal_dir, candidate.install_dir):
                    game = candidate
                    break
        evidence = [
            f"EA Core 日志：activation.exe 于 {core_signal.get('time_text') or '最近'} 被拉起（日志兜底检测，进程/窗口枚举可能受限）"
        ]
        if core_signal.get("portal_timeouts"):
            evidence.append(f"EA 授权握手在 20 秒内没有响应（{core_signal['portal_timeouts']} 次）")
        if game is not None:
            evidence.append(f"归属游戏目录: {game.install_dir}")
        push(
            Issue(
                kind=KIND_ACTIVATION,
                game_key=game.key if game else None,
                game_name=game.name if game else "未知游戏",
                confidence=0.9 if game else 0.72,
                evidence=evidence,
                proc_name="activation.exe",
            )
        )

    issues.sort(key=lambda item: item.confidence, reverse=True)
    return Detection(
        issues=issues,
        game_windows=game_windows,
        ea_windows=ea_windows,
        game_processes=game_processes,
        screen=screen,
        running_keys=running_keys,
    )


def parse_core_activation_summary(text: str) -> dict | None:
    """从 EA Core 日志文本里提取最近一次 activation.exe 启动信息。"""
    from . import chain as chain_mod

    events, timeouts = chain_mod.parse_ea_core(text)
    if not events:
        return None
    lines = text.splitlines()
    last_index = -1
    core_server_index = -1
    for index, line in enumerate(lines):
        if "activation" in line and "CreateProcessW" in line:
            last_index = index
        elif "EACoreServer.exe" in line and "CreateProcessW" in line:
            core_server_index = index
    # 只有靠近日志末尾、且之后没有新的游戏会话，才算「当前正在发生」
    if last_index < 0 or len(lines) - last_index > 200:
        return None
    if core_server_index > last_index:
        return None
    last = events[-1]
    return {
        "time_text": last.time_text,
        "game_dir": last.game_dir,
        "portal_timeouts": timeouts,
    }


def recent_core_activation_signal(max_age_seconds: float = 300.0) -> dict | None:
    """EA Core 日志 5 分钟内有写入且末尾出现 activation.exe 时，返回信号（带缓存）。"""
    log = eaapp.latest_core_log()
    if log is None:
        return None
    try:
        stat = log.stat()
    except OSError:
        return None
    now = time.time()
    if now - stat.st_mtime > max_age_seconds:
        return None
    cache = _CORE_SIGNAL_CACHE
    if cache["mtime"] == stat.st_mtime and now - cache["checked"] < 3.0:
        return cache["data"]
    try:
        text = log.read_bytes().decode("utf-16", errors="ignore")
    except OSError:
        return None
    data = parse_core_activation_summary(text)
    cache.update({"mtime": stat.st_mtime, "checked": now, "data": data})
    return data


def scan(games: list[InstalledGame] | None = None) -> Detection:
    games = games if games is not None else discovery.discover_games().games
    windows = enum_windows()
    processes = list_processes()
    signal = recent_core_activation_signal()
    return classify(windows, processes, games, core_signal=signal)


def find_target_window(issue: Issue) -> WindowInfo | None:
    """重新定位问题窗口（hwnd 可能已失效）。"""
    if issue.hwnd and issue.hwnd > 0:
        for window in enum_windows():
            if window.hwnd == issue.hwnd and window.visible:
                return window
    for window in enum_windows():
        if not window.visible:
            continue
        if issue.game_name and catalog.match_game_text(window.title) is not None:
            return window
        if _has_activation_keyword(window.title):
            return window
    return None
