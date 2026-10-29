"""修复动作链：从「检测到激活弹窗」到「游戏窗口正常出现」。

所有破坏性操作都是「移动到备份目录」，可一键还原；
不做任何授权绕过 —— 只修启动链、缓存与服务，把游戏交还给官方启动方式。
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import catalog, chain, detect, discovery, eaapp
from .config import (
    BACKUPS_DIR,
    EA_SUPPORT_LINK,
    EventLog,
    Settings,
    human_size,
    write_report,
)
from .detect import Detection, Issue
from .discovery import InstalledGame
from .win32 import (
    WindowInfo,
    close_window,
    enum_windows,
    is_admin,
    list_processes,
    path_under,
    shell_execute,
    start_process,
    terminate_pid,
    window_alive,
    window_info,
)

RISK_LABELS = {
    "safe": "安全",
    "low": "低风险",
    "medium": "需确认",
    "admin": "需管理员",
}

PROFILE_LABELS = {"quick": "快速修复", "deep": "深度修复"}


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------
class BackupStore:
    """把要清理的文件移动到带时间戳的目录，并记录清单，支持还原。"""

    def __init__(self, root: Path | None = None, label: str = "") -> None:
        self.root = Path(root or BACKUPS_DIR)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = f"-{label}" if label else ""
        self.dir = self.root / f"{stamp}{suffix}"
        self.label = label
        self.created_at = time.time()
        self.items: list[dict] = []
        self._created = False
        self._lock = threading.Lock()

    # -- 生命周期 -----------------------------------------------------------
    def ensure(self) -> Path:
        if not self._created:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._created = True
        return self.dir

    @property
    def exists(self) -> bool:
        return self._created or self.dir.is_dir()

    def manifest_path(self) -> Path:
        return self.ensure() / "manifest.json"

    def save(self) -> None:
        if not self._created:
            return
        payload = {
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(timespec="seconds"),
            "label": self.label,
            "directory": str(self.dir),
            "items": self.items,
        }
        try:
            self.manifest_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # -- 操作 ---------------------------------------------------------------
    def move_files(self, paths: list[Path], subdir: str = "files") -> tuple[list[str], list[str]]:
        moved: list[str] = []
        failed: list[str] = []
        destination = self.ensure() / subdir
        destination.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for path in paths:
                if not path.is_file():
                    continue
                target = destination / path.name
                counter = 1
                while target.exists():
                    target = destination / f"{path.stem}.{counter}{path.suffix}"
                    counter += 1
                try:
                    size = path.stat().st_size
                    shutil.move(str(path), str(target))
                except OSError as exc:
                    failed.append(f"{path.name}: {exc}")
                    continue
                moved.append(path.name)
                self.items.append(
                    {"src": str(path), "dst": str(target), "size": size, "kind": "file"}
                )
            self.save()
        return moved, failed

    def write_text(self, name: str, content: str) -> Path:
        directory = self.ensure()
        path = directory / name
        try:
            path.write_text(content, encoding="utf-8")
        except OSError:
            pass
        return path

    def write_json(self, name: str, payload: dict) -> Path:
        directory = self.ensure()
        path = directory / name
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass
        return path

    @property
    def total_bytes(self) -> int:
        return sum(int(item.get("size") or 0) for item in self.items)

    def duplicates_note(self) -> str:
        return f"{len(self.items)} 个文件，共 {human_size(self.total_bytes)}"


def list_backups() -> list[Path]:
    try:
        directories = [p for p in BACKUPS_DIR.iterdir() if p.is_dir()]
    except OSError:
        return []
    return sorted(directories, key=lambda p: p.name, reverse=True)


def restore_backup(directory: Path) -> tuple[int, list[str]]:
    """把备份目录里的文件搬回原位置。"""
    manifest = Path(directory) / "manifest.json"
    if not manifest.is_file():
        return 0, ["没有找到 manifest.json"]
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return 0, [f"读取清单失败: {exc}"]
    restored = 0
    errors: list[str] = []
    for item in reversed(payload.get("items") or []):
        src = Path(item.get("dst") or "")
        dst = Path(item.get("src") or "")
        if not src.is_file():
            errors.append(f"备份文件已不存在: {src.name}")
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_file():
                dst = dst.with_name(f"{dst.stem}.restored{dst.suffix}")
            shutil.move(str(src), str(dst))
            restored += 1
        except OSError as exc:
            errors.append(f"{src.name}: {exc}")
    return restored, errors


# ---------------------------------------------------------------------------
# 步骤定义
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class StepResult:
    status: str  # ok / warn / fail / skip / simulated
    message: str
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "simulated")


@dataclass(slots=True)
class StepSpec:
    id: str
    title: str
    detail: str
    risk: str
    func: Callable[["RepairContext"], StepResult]


@dataclass
class RepairContext:
    settings: Settings
    log: EventLog
    game: InstalledGame | None = None
    issue: Issue | None = None
    detection: Detection | None = None
    games: list[InstalledGame] = field(default_factory=list)
    dry_run: bool = False
    profile: str = "quick"
    verify_timeout: float = 75.0
    cancel_event: threading.Event = field(default_factory=threading.Event)
    backup: BackupStore | None = None
    results: dict[str, StepResult] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    verify_data: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    concluded: dict = field(default_factory=dict)
    chain_analysis: object | None = None

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def backup_store(self) -> BackupStore:
        if self.backup is None:
            label = self.game.key if self.game else "general"
            self.backup = BackupStore(label=label)
        return self.backup

    def add_evidence(self, text: str) -> None:
        if text and text not in self.evidence:
            self.evidence.append(text)

    @property
    def game_name(self) -> str:
        return self.game.name if self.game else (self.issue.game_name if self.issue else "未知游戏")


def _result(status: str, message: str, **data) -> StepResult:
    return StepResult(status=status, message=message, data=data)


# ---------------------------------------------------------------------------
# 步骤实现
# ---------------------------------------------------------------------------
def step_snapshot(ctx: RepairContext) -> StepResult:
    """记录现场：窗口、进程、授权缓存、日志证据，方便回溯。"""
    snapshot = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "game": _game_dict(ctx.game),
        "issue": _issue_dict(ctx.issue),
        "detection": {
            "summary": ctx.detection.summary() if ctx.detection else "",
            "issues": [_issue_dict(item) for item in (ctx.detection.issues if ctx.detection else [])],
            "game_windows": [w.title for w in (ctx.detection.game_windows if ctx.detection else [])],
            "ea_windows": [w.title for w in (ctx.detection.ea_windows if ctx.detection else [])],
        },
        "ea": {
            "installed": eaapp.info().installed,
            "version": eaapp.info().version,
            "running": eaapp.info().running,
            "processes": eaapp.info().processes,
            "service": eaapp.service_status("EABackgroundService"),
        },
        "protocols": [
            {"protocol": p.protocol, "ok": p.ok, "command": p.command} for p in eaapp.protocol_status()
        ],
        "license": {
            "path": eaapp.license_summary().path,
            "count": eaapp.license_summary().count,
            "age_days": eaapp.license_summary().newest_age_days,
        },
        "activation_events": [
            {
                "timestamp": event.timestamp,
                "exe": event.exe_path,
                "game_dir": event.game_dir,
            }
            for event in eaapp.parse_activation_events(max_events=3)
        ],
        "steam_running": discovery.steam_running(),
    }
    # 启动链路分析：Steam 有没有真的拉起游戏、EA 授权握手有没有完成
    chain_analysis = None
    if ctx.game is not None and ctx.game.steam_appid:
        try:
            chain_analysis = chain.analyze_game(ctx.game)
        except Exception:
            chain_analysis = None
    if chain_analysis is not None:
        ctx.chain_analysis = chain_analysis
        snapshot["chain"] = {
            "cause": chain_analysis.cause,
            "cause_label": chain_analysis.cause_label,
            "confidence": chain_analysis.confidence,
            "lines": chain_analysis.lines,
            "notes": chain_analysis.notes,
        }
        ctx.add_evidence("链路分析：" + chain_analysis.cause_label)
    snapshot["account"] = eaapp.account_summary()

    report = write_report("snapshot", snapshot)
    if ctx.backup is not None:
        ctx.backup.write_json("snapshot.json", snapshot)
    else:
        ctx.backup_store().write_json("snapshot.json", snapshot)
    ctx.add_evidence(f"现场快照已保存：{report.name}")
    for item in (ctx.issue.evidence if ctx.issue else []):
        ctx.add_evidence(item)
    return _result("ok", f"已记录现场（{report.name}）", report=str(report))


def _activation_targets(issue: Issue | None, game: InstalledGame | None) -> list[WindowInfo]:
    """找出真正的激活弹窗窗口：activation.exe 的窗口，或 EA 客户端弹出的相关窗口。"""
    processes = list_processes()
    activation_pids = {proc.pid for proc in processes.values() if proc.name_lower.startswith("activation")}
    targets: list[WindowInfo] = []
    for window in enum_windows():
        if not window.visible or not window.title.strip():
            continue
        owner = processes.get(window.pid)
        name = owner.name_lower if owner else ""
        title = window.title.strip()
        is_activation = window.pid in activation_pids or name.startswith("activation")
        matched = catalog.match_game_text(title)
        game_match = bool(game is not None and matched is not None and matched.key == game.key)
        normalized = catalog.normalize_title(title)
        keyword_match = any(keyword in normalized for keyword in detect.ACTIVATION_KEYWORDS)
        ea_dialog = name in eaapp.EA_CLIENT_PROCESSES and (game_match or keyword_match)
        if is_activation or ea_dialog:
            targets.append(window)
    return targets


def step_close_dialog(ctx: RepairContext) -> StepResult:
    """关闭 EA 的激活 / 错误提示窗口（先等它出现，再关，不行就结束 activation.exe）。"""
    if ctx.dry_run:
        return _result("simulated", "模拟：关闭激活弹窗")
    if ctx.issue is None:
        return _result("skip", "没有待处理的弹窗")

    targets: list[WindowInfo] = []
    deadline = time.time() + 10
    while time.time() < deadline:
        if ctx.cancelled():
            break
        targets = _activation_targets(ctx.issue, ctx.game)
        if targets:
            break
        if ctx.issue.hwnd and window_alive(ctx.issue.hwnd):
            info = window_info(ctx.issue.hwnd)
            if info is not None:
                targets = [info]
                break
        time.sleep(0.35)

    closed = 0
    killed = 0
    names: list[str] = []
    for window in targets:
        names.append(f"{window.title.strip() or '(无标题)'}[{window.cls}]")
        close_window(window.hwnd)
        window_deadline = time.time() + 3
        while time.time() < window_deadline and window_alive(window.hwnd):
            time.sleep(0.15)
        if window_alive(window.hwnd):
            if terminate_pid(window.pid, timeout=3):
                killed += 1
        else:
            closed += 1

    # 兜底：清掉属于该游戏的 activation.exe 残留
    for proc in list_processes().values():
        if not proc.name_lower.startswith("activation"):
            continue
        if ctx.game is not None and ctx.game.install_dir and proc.exe and not path_under(proc.exe, ctx.game.install_dir):
            continue
        if terminate_pid(proc.pid, timeout=3):
            killed += 1

    if closed or killed:
        detail = []
        if closed:
            detail.append(f"关闭 {closed} 个窗口")
        if killed:
            detail.append(f"结束 {killed} 个进程")
        message = "，".join(detail) + ("（" + "、".join(names[:2]) + "）" if names else "")
        ctx.add_evidence(message)
        return _result("ok", message, windows=closed, processes=killed)
    if targets:
        return _result("warn", f"找到 {len(targets)} 个候选窗口但没能关闭（可能已被占用）")
    return _result("warn", "10 秒内没有等到激活窗口出现（可能已经消失），已尝试清理 activation.exe")


def step_kill_stale_game(ctx: RepairContext) -> StepResult:
    """结束卡住、且没有窗口的残留游戏进程。"""
    if ctx.game is None or not ctx.game.install_dir:
        return _result("skip", "没有识别到游戏，跳过")
    if ctx.dry_run:
        return _result("simulated", "模拟：结束残留游戏进程")

    processes = list_processes()
    windows = enum_windows()
    window_pids = {w.pid for w in windows if w.visible}
    killed: list[str] = []
    for proc in processes.values():
        if not proc.exe or not path_under(proc.exe, ctx.game.install_dir):
            continue
        if proc.name_lower.startswith("activation"):
            continue
        if proc.pid in window_pids:
            continue
        age = time.time() - (proc.create_time or time.time())
        if age < 20:
            continue
        if terminate_pid(proc.pid, timeout=4):
            killed.append(proc.name)
    if killed:
        message = f"已结束 {len(killed)} 个残留进程：{', '.join(sorted(set(killed)))}"
        ctx.add_evidence(message)
        return _result("ok", message)
    return _result("ok", "没有需要结束的残留游戏进程")


def step_stop_ea(ctx: RepairContext) -> StepResult:
    if ctx.dry_run:
        return _result("simulated", "模拟：关闭 EA App")
    if not eaapp.info().installed:
        return _result("skip", "EA App 未安装，跳过")
    ok, message = eaapp.stop_client(include_service=is_admin())
    ctx.add_evidence(message)
    return _result("ok" if ok else "warn", message)


def license_cleanup_targets(game: InstalledGame | None, license_dir: str | Path | None = None) -> tuple[list[Path], list[Path]]:
    """要清理的授权缓存：BF3 走精准清理（71067.dlf 等），其它游戏清理全部 .dlf。"""
    directory = Path(license_dir or eaapp.LICENSE_DIR)
    files: list[Path] = []
    if game is not None and game.key == "bf3":
        for name in eaapp.LEGACY_BF3_LICENSE_FILES:
            path = directory / name
            if path.is_file():
                files.append(path)
        if not files:
            try:
                files = sorted(directory.glob("*.dlf"))
            except OSError:
                files = []
    else:
        try:
            files = sorted(directory.glob("*.dlf"))
        except OSError:
            files = []
    return files, eaapp.legacy_cache_items()


def step_clear_license(ctx: RepairContext) -> StepResult:
    """备份并清理授权缓存，让 EA App 下次启动时重新生成（BF3 会精准清理老式授权文件）。"""
    files, cache_items = license_cleanup_targets(ctx.game)
    if ctx.dry_run:
        return _result("simulated", f"模拟：备份并清理 {len(files)} 个授权文件、{len(cache_items)} 个缓存条目")
    if not files and not cache_items:
        return _result("warn", "没有找到需要清理的授权缓存")

    store = ctx.backup_store()
    moved, failed = store.move_files(files, subdir="license")
    cache_moved: list[str] = []
    if cache_items:
        cache_moved, _ = store.move_files(cache_items, subdir="cache")

    parts: list[str] = []
    if moved:
        parts.append(f"已备份并清理 {len(moved)} 个授权文件")
        if ctx.game is not None and ctx.game.key == "bf3":
            parts.append("（含 BF3 老授权缓存 71067.dlf）")
    if cache_moved:
        parts.append(f"清理 {len(cache_moved)} 个老下载缓存条目")
    if not moved and not cache_moved:
        return _result("fail", "授权缓存清理失败：" + "；".join(failed[:3]))
    message = "，".join(parts) + "；EA App 重启后会重新生成授权"
    ctx.add_evidence(message)
    if failed:
        return _result("warn", message + "；部分失败：" + "；".join(failed[:3]))
    return _result("ok", message, moved=len(moved), cache_moved=len(cache_moved), backup=str(store.dir))


def step_repair_protocols(ctx: RepairContext) -> StepResult:
    plan = eaapp.protocol_repair_plan()
    if not plan:
        return _result("ok", "EA 启动协议注册正常，无需修复")
    if ctx.dry_run:
        return _result("simulated", f"模拟：修复 {len(plan)} 个协议注册")
    if not is_admin():
        return _result("warn", "协议注册需要管理员权限：请以管理员身份重启本工具后再修复（本次已跳过）")
    ok, message = eaapp.apply_protocol_repairs()
    ctx.add_evidence(message)
    return _result("ok" if ok else "warn", message)


def step_start_ea(ctx: RepairContext) -> StepResult:
    if ctx.dry_run:
        return _result("simulated", "模拟：启动 EA App")
    ok, message = eaapp.start_client(wait_seconds=30)
    ctx.add_evidence(message)
    if ok:
        time.sleep(2.0)
    return _result("ok" if ok else "warn", message)


def step_launch(ctx: RepairContext) -> StepResult:
    """按游戏归属选择正确的启动方式：Steam 版走 Steam，其余走 exe。"""
    game = ctx.game
    if game is None:
        return _result("fail", "没有识别到要启动的游戏")
    if ctx.dry_run:
        return _result("simulated", f"模拟：启动 {game.name}")
    if _game_window_visible(game):
        return _result("ok", f"{game.name} 已经有游戏窗口在运行，跳过重复启动", channel="existing")

    prefer_steam = ctx.settings.prefer_steam and bool(game.steam_appid)
    if prefer_steam:
        ok, message = _launch_via_steam(game)
        ctx.add_evidence(message)
        return _result("ok" if ok else "fail", message, channel="steam", appid=game.steam_appid)

    if not game.exe or not Path(game.exe).is_file():
        return _result("fail", f"{game.name} 的主程序不存在，请先在平台里修复游戏")
    if not eaapp.info().running:
        eaapp.ensure_running()
    proc = start_process(game.exe, cwd=str(Path(game.exe).parent))
    if proc is None:
        # 有的游戏必须通过 EA 协议 / 平台启动
        if shell_execute(game.exe):
            message = f"已通过系统方式启动 {game.name}"
            ctx.add_evidence(message)
            return _result("ok", message, channel="exe")
        return _result("fail", f"启动 {game.name} 失败（{game.exe}）")
    message = f"已直接启动 {game.name}（{Path(game.exe).name}）"
    ctx.add_evidence(message)
    return _result("ok", message, channel="exe", pid=proc.pid)


def _launch_via_steam(game: InstalledGame) -> tuple[bool, str]:
    steam_exe = discovery.steam_executable()
    if not steam_exe:
        return False, "没有找到 Steam，无法用 Steam 启动"
    if not discovery.steam_running():
        start_process(steam_exe, args=["-silent"], cwd=str(Path(steam_exe).parent))
        deadline = time.time() + 45
        while time.time() < deadline and not discovery.steam_running():
            time.sleep(0.8)
        if not discovery.steam_running():
            return False, "Steam 启动超时，请手动打开 Steam 后重试"
        time.sleep(5.0)  # 等 Steam 完成登录恢复
    url = f"steam://rungameid/{game.steam_appid}"
    if not shell_execute(url):
        return False, f"调用 Steam 启动失败（{url}）"
    return True, f"已通过 Steam 请求启动 {game.name}（AppID {game.steam_appid}）"


def launch_game_now(game: InstalledGame, prefer_steam: bool = True) -> tuple[bool, str]:
    """不跑完整修复链，只按正确方式启动游戏（供「启动」按钮使用）。"""
    if game.steam_appid and prefer_steam:
        ok, message = _launch_via_steam(game)
        return ok, message
    if not game.exe or not Path(game.exe).is_file():
        return False, f"{game.name} 的主程序不存在，请先在平台里修复游戏"
    if not eaapp.info().running:
        eaapp.ensure_running()
    proc = start_process(game.exe, cwd=str(Path(game.exe).parent))
    if proc is not None:
        return True, f"已直接启动 {game.name}（{Path(game.exe).name}）"
    if shell_execute(game.exe):
        return True, f"已通过系统方式启动 {game.name}"
    return False, f"启动 {game.name} 失败"


def step_verify(ctx: RepairContext) -> StepResult:
    """等待游戏窗口出现；如果激活弹窗再次出现则判为失败并说明原因。"""
    if ctx.dry_run:
        return _result("simulated", "模拟：等待游戏窗口")
    if ctx.game is None:
        return _result("skip", "没有识别到游戏，跳过验证")

    timeout = max(15.0, float(ctx.verify_timeout))
    deadline = time.time() + timeout
    activation_hits = 0
    game_process_seen = False
    last_progress = 0.0
    while time.time() < deadline:
        if ctx.cancelled():
            return _result("warn", "验证被取消")
        if _game_window_visible(ctx.game):
            ctx.verify_data = {"result": "window", "elapsed": round(timeout - (deadline - time.time()), 1)}
            return _result("ok", f"游戏窗口已出现，用时约 {round(timeout - (deadline - time.time()), 1)} 秒")
        detection = detect.scan([ctx.game])
        if any(issue.kind == detect.KIND_ACTIVATION and issue.game_key == ctx.game.key for issue in detection.issues):
            activation_hits += 1
            if activation_hits >= 2:
                ctx.verify_data = {"result": "activation_returned", "elapsed": round(timeout - (deadline - time.time()), 1)}
                return _result(
                    "fail",
                    "激活弹窗再次出现：说明 EA 仍然认为当前启动没有有效授权",
                    activation_hits=activation_hits,
                )
        if any(proc.exe and path_under(proc.exe, ctx.game.install_dir) for proc in detection.game_processes):
            game_process_seen = True
        if time.time() - last_progress > 8:
            last_progress = time.time()
            ctx.add_evidence("等待游戏窗口…")
    if game_process_seen:
        ctx.verify_data = {"result": "process_only", "elapsed": timeout}
        return _result("warn", "检测到游戏进程仍在运行，但没有出现游戏窗口（可能加载较慢或已无响应）")
    ctx.verify_data = {"result": "nothing", "elapsed": timeout}
    return _result("fail", f"等待 {int(timeout)} 秒后没有检测到游戏启动")


def _game_window_visible(game: InstalledGame) -> bool:
    """判断游戏窗口是否出现：优先按 exe 路径，路径/权限异常时按窗口标题与进程名兜底。"""
    processes = list_processes()
    exe_name = Path(game.exe).name.lower() if game.exe else ""
    for window in enum_windows():
        if not window.visible or window.minimized:
            continue
        if window.width < 200 or window.height < 120:
            continue
        owner = processes.get(window.pid)
        if owner and owner.exe and game.install_dir and path_under(owner.exe, game.install_dir):
            return True
        matched = catalog.match_game_text(window.title) if window.title else None
        if matched is not None and matched.key == game.key:
            return True
        if exe_name and owner and owner.name_lower == exe_name:
            return True
    return False


def step_conclude(ctx: RepairContext) -> StepResult:
    """汇总结果 + 给出可执行的建议（不会给出任何绕过授权的做法）。"""
    verify = ctx.results.get("verify")
    launch = ctx.results.get("launch")
    success = bool(verify and verify.status == "ok")
    activation_returned = bool(verify and verify.status == "fail" and "激活弹窗再次出现" in verify.message)

    chain_analysis = ctx.chain_analysis
    cause = getattr(chain_analysis, "cause", "") if chain_analysis is not None else ""
    cause_label = getattr(chain_analysis, "cause_label", "") if chain_analysis is not None else ""
    chain_lines = list(getattr(chain_analysis, "lines", []) or []) if chain_analysis is not None else []
    account = eaapp.account_summary()

    analysis: list[str] = []
    if success:
        analysis.append("弹窗已关闭，游戏窗口已正常出现。")
        if launch and launch.data.get("channel") == "steam":
            analysis.append("本次通过 Steam 启动 —— Steam 版 EA 游戏必须由 Steam 拉起，才能把 Steam 票据交给 EA App 完成授权。")
        if launch and launch.data.get("channel") == "exe":
            analysis.append("本次通过主程序直接启动，并已确认 EA App 在运行。")
    else:
        if cause == "bf3_license_stale":
            analysis.append("定位到原因：BF3 的老式授权缓存文件（71067.dlf 等）已经过期/损坏，EA 加载它时卡了 20 秒，随后退回激活界面。")
            analysis.append("这不是账号授权缺失，也不是启动方式问题：深度修复会备份并删除这些缓存文件，EA App 重启后会重新生成一份新的授权缓存。")
            analysis.append("刚才这台机器上正是用这个方法恢复的：删除旧 71067.dlf → EA 重新生成 → 从 Steam 启动成功。")
        elif cause == "ea_portal_timeout_no_license":
            analysis.append("Steam 已经成功拉起了游戏（Steam 日志里有该 AppID 的启动记录），但 EA 的授权握手在 20 秒内没有完成，而且启动后没有下发新的授权缓存。")
            analysis.append("这说明问题出在 EA 账号侧：当前登录的 EA 账号没有被授予这款游戏，或授权绑定在另一个 EA 账号上，而不是启动方式或缓存问题。")
            if account:
                analysis.append(f"工具从 EA token 里解出的账号信息：{account}。")
        elif cause == "activation_no_entitlement":
            analysis.append("Steam 已拉起游戏，EA 仍然要求激活：优先核对当前 EA 账号是否就是拥有该游戏的那个账号。")
        elif cause == "license_cache_stale":
            analysis.append("EA 本次下发了新的授权文件，说明账号有授权；更像是旧缓存 / 客户端状态问题，重试或深度修复通常有效。")
        elif activation_returned:
            analysis.append("EA 在启动后又要求激活：这通常不是缓存问题，而是「当前账号没有被授权」或「启动链没有携带平台票据」。")
        analysis.extend(_recommendations(ctx))

    payload = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "profile": ctx.profile,
        "game": _game_dict(ctx.game),
        "success": success,
        "steps": {key: {"status": value.status, "message": value.message} for key, value in ctx.results.items()},
        "evidence": ctx.evidence,
        "analysis": analysis,
        "verify": ctx.verify_data,
        "chain": {
            "cause": cause,
            "cause_label": cause_label,
            "lines": chain_lines,
            "notes": list(getattr(chain_analysis, "notes", []) or []) if chain_analysis is not None else [],
        },
        "account": account,
        "backup": str(ctx.backup.dir) if ctx.backup and ctx.backup.exists else "",
        "links": [EA_SUPPORT_LINK],
    }
    report = write_report("repair" if not success else "repair-success", payload)
    if ctx.backup is not None and ctx.backup.exists:
        ctx.backup.write_json("result.json", payload)
    ctx.concluded = {
        "success": success,
        "analysis": analysis,
        "report": str(report),
        "chain_lines": chain_lines,
        "chain_cause": cause,
        "account": account,
    }
    if success:
        return _result("ok", "修复完成：游戏已正常启动", report=str(report))
    return _result("warn", "未能让游戏正常出现窗口，已生成诊断建议", report=str(report))


def _recommendations(ctx: RepairContext) -> list[str]:
    tips: list[str] = []
    game = ctx.game
    chain_analysis = ctx.chain_analysis
    cause = getattr(chain_analysis, "cause", "") if chain_analysis is not None else ""
    account = eaapp.account_summary()
    if game is None:
        return ["没有识别到具体游戏，请先手动启动一次游戏，出现弹窗后回到本工具扫描。"]
    if cause == "bf3_license_stale":
        tips.append("直接点「运行深度修复」：它会备份并删除过期的 BF3 授权缓存（71067.dlf 等）、清掉老下载缓存、重启 EA App，然后从 Steam 重新启动。")
        tips.append("修复后如果还有残留弹窗，在修复中心点「重新扫描」确认；授权缓存文件会自动重新生成。")
        tips.append("手动做法：关闭 EA App → 把 C:\\ProgramData\\Electronic Arts\\EA Services\\License\\71067.dlf 改成 .bak → 启动 EA App → 从 Steam 启动 BF3。")
    if cause == "steam_not_launched":
        tips.append("Steam 没有启动游戏：先在 Steam 里确认已登录、游戏在库中可点「开始游戏」，再回到本工具重试。")
    if cause == "ea_portal_timeout_no_license":
        tips.append("核对 EA 账号：" + (account or "打开 EA App 查看左下角头像") + "。只有「拥有该游戏的 EA 账号」才能通过授权。")
        tips.append("如果以前用另一个 EA/Origin 账号激活过这款游戏，请退出当前 EA App 登录，换那个账号再启动。")
        tips.append("在 Steam 里确认这款游戏是「自己购买」而不是家庭共享 / 借用（库 → 右键游戏 → 管理 → 账户明细）。")
        tips.append("若确认是自购仍失败：带 Steam 购买凭证联系 EA 客服处理授权绑定（EA 支持可以重新落授权），或先在 Steam 退款后重新购买触发重新绑定。")
        tips.append("备用尝试：在修复中心执行「深度修复」（以完整界面重启 EA App + 刷新授权缓存），之后从 Steam 重新启动。")
    if game.extras:
        tips.append("安装目录里检测到第三方启动器/补丁（" + "、".join(game.extras[:4]) + "）：它们绕过了官方启动链，本工具不会修复这类绕过逻辑，建议只用 Steam 启动。")
    tips.append("在 Steam 里对游戏执行一次「验证游戏文件完整性」，排除被第三方补丁改坏的文件。")
    if cause not in ("ea_portal_timeout_no_license",):
        tips.append("确认 EA App 已登录，并且登录的账号就是拥有该游戏的账号。")
        tips.append("Steam 版游戏：确认 Steam 已登录、且 Steam 账号已绑定 EA 账号；只从 Steam 启动游戏。")
    tips.append(f"仍然无法激活时，按 EA 官方步骤核对账号绑定：{EA_SUPPORT_LINK}")
    return tips


def _game_dict(game: InstalledGame | None) -> dict | None:
    if game is None:
        return None
    return {
        "key": game.key,
        "name": game.name,
        "name_cn": game.name_cn,
        "install_dir": game.install_dir,
        "exe": game.exe,
        "steam_appid": game.steam_appid,
        "platform": game.platform,
        "installed": game.installed,
        "extras": game.extras,
    }


def _issue_dict(issue: Issue | None) -> dict | None:
    if issue is None:
        return None
    return {
        "kind": issue.kind,
        "kind_label": issue.kind_label,
        "game_key": issue.game_key,
        "game_name": issue.game_name,
        "confidence": issue.confidence,
        "evidence": issue.evidence,
        "hwnd": issue.hwnd,
        "pid": issue.pid,
        "proc_name": issue.proc_name,
        "title": issue.title,
        "cls": issue.cls,
    }


# ---------------------------------------------------------------------------
# 方案
# ---------------------------------------------------------------------------
STEPS: dict[str, StepSpec] = {
    "snapshot": StepSpec("snapshot", "记录现场快照", "保存窗口 / 进程 / 授权缓存 / 日志证据，便于回溯", "safe", step_snapshot),
    "close_dialog": StepSpec("close_dialog", "关闭激活弹窗", "关闭 EA 的激活提示窗口（必要时结束 activation.exe）", "safe", step_close_dialog),
    "kill_stale_game": StepSpec("kill_stale_game", "结束残留游戏进程", "清理已经没有窗口、卡住的游戏进程", "low", step_kill_stale_game),
    "stop_ea": StepSpec("stop_ea", "关闭 EA App", "为清理缓存做准备的优雅退出", "low", step_stop_ea),
    "clear_license": StepSpec("clear_license", "刷新授权缓存", "备份并移走 .dlf 授权缓存，让 EA App 重新拉取", "medium", step_clear_license),
    "repair_protocol": StepSpec("repair_protocol", "修复 EA 启动协议", "修复 origin / origin2 / link2ea 的 URL 协议注册", "admin", step_repair_protocols),
    "start_ea": StepSpec("start_ea", "重新启动 EA App", "启动客户端并等待其加载完成", "safe", step_start_ea),
    "launch": StepSpec("launch", "按平台正确启动", "Steam 版交给 Steam 拉起，其他版本直接运行主程序", "safe", step_launch),
    "verify": StepSpec("verify", "等待游戏窗口", "轮询窗口，确认游戏真的起来了；弹窗再现会立刻判定失败", "safe", step_verify),
    "conclude": StepSpec("conclude", "生成结论与建议", "汇总证据，给出下一步该做什么", "safe", step_conclude),
}

PROFILES: dict[str, list[str]] = {
    "quick": ["snapshot", "close_dialog", "repair_protocol", "launch", "verify", "conclude"],
    "deep": [
        "snapshot",
        "close_dialog",
        "kill_stale_game",
        "stop_ea",
        "clear_license",
        "repair_protocol",
        "start_ea",
        "launch",
        "verify",
        "conclude",
    ],
}


def build_plan(profile: str = "quick") -> list[StepSpec]:
    return [STEPS[step_id] for step_id in PROFILES.get(profile, PROFILES["quick"])]


def plan_payload(profile: str = "quick") -> list[dict]:
    return [
        {
            "id": step.id,
            "title": step.title,
            "detail": step.detail,
            "risk": step.risk,
            "risk_label": RISK_LABELS.get(step.risk, step.risk),
        }
        for step in build_plan(profile)
    ]


# ---------------------------------------------------------------------------
# 执行器
# ---------------------------------------------------------------------------
@dataclass
class RunnerCallbacks:
    on_start: Callable[[StepSpec], None] = lambda step: None
    on_done: Callable[[StepSpec, StepResult], None] = lambda step, result: None
    on_log: Callable[[str, str], None] = lambda level, message: None
    on_finished: Callable[[RepairContext], None] = lambda ctx: None


class RepairRunner(threading.Thread):
    def __init__(self, ctx: RepairContext, profile: str, callbacks: RunnerCallbacks | None = None) -> None:
        super().__init__(daemon=True, name="repair-runner")
        self.ctx = ctx
        self.profile = profile
        self.callbacks = callbacks or RunnerCallbacks()
        self.outcome: RepairContext | None = None

    def run(self) -> None:  # noqa: D401
        try:
            for spec in build_plan(self.profile):
                if self.ctx.cancelled():
                    self.callbacks.on_log("warn", "修复流程已取消")
                    break
                self.callbacks.on_start(spec)
                started = time.time()
                try:
                    result = spec.func(self.ctx)
                except Exception as exc:  # 单步异常不应中断整个流程
                    result = StepResult(status="fail", message=f"步骤异常：{exc}")
                self.ctx.results[spec.id] = result
                elapsed = time.time() - started
                self.callbacks.on_log("info", f"{spec.title} · {result.message}（{elapsed:.1f}s）")
                self.callbacks.on_done(spec, result)
        finally:
            self.ctx.results.setdefault("conclude", StepResult(status="skip", message="流程未完成"))
            self.outcome = self.ctx
            try:
                self.callbacks.on_finished(self.ctx)
            except Exception:
                pass
