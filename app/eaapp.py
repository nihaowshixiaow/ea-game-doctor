"""EA App（含旧版 Origin 组件）状态读取与安全的重启操作。"""

from __future__ import annotations

import os
import re
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

from .win32 import (
    close_window,
    enum_windows,
    is_admin,
    list_processes,
    run_command,
    start_process,
    terminate_pid,
    terminate_process_names,
)

EA_CLIENT_DIR = Path(r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop")
EA_DESKTOP_EXE = EA_CLIENT_DIR / "EADesktop.exe"
EA_LAUNCHER_EXE = EA_CLIENT_DIR / "EALauncher.exe"

LICENSE_DIR = Path(r"C:\ProgramData\Electronic Arts\EA Services\License")
ORIGIN_DOWNLOAD_CACHE = Path(r"C:\ProgramData\Origin\DownloadCache")
EA_CORE_CACHE = Path(r"C:\ProgramData\EA Core\cache")

# 老 BF3 在 EA Core / Origin 里用到的授权缓存文件名（社区修复共识）
LEGACY_BF3_LICENSE_FILES = ("71067.dlf", "70619.dlf", "70169.dlf")
LEGACY_BF3_STALE_DAYS = 60.0
EA_CORE_LOG_DIR = Path(r"C:\ProgramData\Electronic Arts\EA Core\logs")
EA_CORE_PREF_DIR = Path(r"C:\ProgramData\Electronic Arts\EA Core\prefs")
EA_LOG_DIR = Path(r"C:\ProgramData\EA Desktop\Logs")

EA_CLIENT_PROCESSES = {
    "eadestop.exe",
    "eabackgroundservice.exe",
    "ealocalhostsvc.exe",
    "ealauncher.exe",
    "link2ea.exe",
    "eaconnect_microsoft.exe",
    "eassteamlauncher.exe",
    "easteamproxy.exe",
    "easteamauthhelper.exe",
    "eacrashreporter.exe",
    "eaupdater.exe",
    "getgametoken.exe",
    "igoproxy32.exe",
    "igoproxy64.exe",
    "policyproxy32.exe",
    "policyproxy64.exe",
    "eacore.exe",
    "eacoreserver.exe",
    "eacorelauncher.exe",
}

ACTIVATION_PROCESS_HINTS = ("activation.exe", "activation64.exe", "eacoreactivation.exe")

PROTOCOLS = {
    "origin": "EALauncher.exe",
    "origin2": "EALauncher.exe",
    "link2ea": "Link2EA.exe",
}

ACTIVATION_LOG_KEYWORDS = (
    "activation", "entitle", "licens", "not activate", "could not activate",
    "product key", "unlock access", "drms", "drmerror",
)


# ---------------------------------------------------------------------------
# 基本信息
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class EAInfo:
    installed: bool
    directory: str | None
    exe: str | None
    version: str | None
    running: bool
    processes: list[str]


def _read_version() -> str | None:
    vp = EA_CLIENT_DIR / "version.properties"
    try:
        text = vp.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r"(\d+\.\d+[\w.\-]*)", text)
    return match.group(1) if match else None


def info() -> EAInfo:
    processes = list_processes()
    names = sorted({p.name.lower() for p in processes.values() if p.name.lower() in EA_CLIENT_PROCESSES})
    installed = EA_DESKTOP_EXE.is_file()
    return EAInfo(
        installed=installed,
        directory=str(EA_CLIENT_DIR) if installed else None,
        exe=str(EA_DESKTOP_EXE) if installed else None,
        version=_read_version(),
        running=any(name in names for name in ("eadestop.exe", "eabackgroundservice.exe")),
        processes=names,
    )


def ea_processes(processes: dict | None = None) -> list:
    processes = processes if processes is not None else list_processes()
    return [p for p in processes.values() if p.name.lower() in EA_CLIENT_PROCESSES]


def service_status(name: str) -> str:
    code, out = run_command(["sc", "query", name], timeout=6.0)
    if code != 0:
        return "MISSING"
    match = re.search(r"STATE\s*:\s*\d+\s+(\w+)", out)
    return match.group(1).upper() if match else "UNKNOWN"


# ---------------------------------------------------------------------------
# 授权缓存
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class LicenseSummary:
    path: str
    files: list[str]
    total_bytes: int
    newest_age_days: float | None

    @property
    def count(self) -> int:
        return len(self.files)


def license_summary() -> LicenseSummary:
    files: list[str] = []
    total = 0
    newest: float | None = None
    try:
        entries = list(LICENSE_DIR.glob("*.dlf"))
    except OSError:
        entries = []
    for entry in entries:
        files.append(entry.name)
        try:
            stat = entry.stat()
        except OSError:
            continue
        total += stat.st_size
        if newest is None or stat.st_mtime > newest:
            newest = stat.st_mtime
    age = (time.time() - newest) / 86400 if newest else None
    return LicenseSummary(str(LICENSE_DIR), sorted(files), total, age)


def license_files() -> list[Path]:
    try:
        return sorted(LICENSE_DIR.glob("*.dlf"))
    except OSError:
        return []


# ---------------------------------------------------------------------------
# 协议注册
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ProtocolStatus:
    protocol: str
    command: str
    target: str
    ok: bool
    expected: str


def _reg_read_command(protocol: str) -> str:
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Classes\{protocol}\shell\open\command", 0, winreg.KEY_READ | view) as key:
                value = winreg.QueryValueEx(key, "")[0]
                if isinstance(value, str):
                    return value
        except OSError:
            continue
    return ""


def protocol_status() -> list[ProtocolStatus]:
    result: list[ProtocolStatus] = []
    for protocol, exe_name in PROTOCOLS.items():
        command = _reg_read_command(protocol)
        target = ""
        stripped = command.strip()
        if stripped.startswith('"'):
            match = re.match(r'"([^"]+\.exe)"', stripped, re.IGNORECASE)
            if match:
                target = match.group(1)
        if not target:
            match = re.match(r"(.*?\.exe)", stripped, re.IGNORECASE)
            if match:
                target = match.group(1).strip().strip('"')
        expected = str(EA_CLIENT_DIR / exe_name)
        result.append(
            ProtocolStatus(
                protocol=protocol,
                command=command,
                target=target,
                ok=bool(target) and Path(target).is_file(),
                expected=expected,
            )
        )
    return result


def protocol_repair_plan() -> list[ProtocolStatus]:
    return [item for item in protocol_status() if not item.ok]


def apply_protocol_repairs() -> tuple[bool, str]:
    """修复 URL 协议注册。写 HKLM 需要管理员权限。"""
    plan = protocol_repair_plan()
    if not plan:
        return True, "协议注册正常，无需修复。"
    if not is_admin():
        return False, "修复协议注册需要管理员权限，请以管理员身份重启本工具。"
    fixed: list[str] = []
    failed: list[str] = []
    for item in plan:
        exe = EA_CLIENT_DIR / PROTOCOLS[item.protocol]
        if not exe.is_file():
            failed.append(f"{item.protocol}: 缺少 {exe.name}")
            continue
        command = f'"{exe}" "%1"'
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.CreateKeyEx(
                    winreg.HKEY_LOCAL_MACHINE,
                    rf"SOFTWARE\Classes\{item.protocol}\shell\open\command",
                    0,
                    winreg.KEY_SET_VALUE | view,
                ) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
                fixed.append(item.protocol)
            except PermissionError:
                failed.append(f"{item.protocol}: 权限不足")
            except OSError as exc:
                failed.append(f"{item.protocol}: {exc}")
    ok = not failed
    message = "已修复: " + ", ".join(sorted(set(fixed))) if fixed else "没有可修复项。"
    if failed:
        message += "；失败: " + "；".join(failed)
    return ok, message


# ---------------------------------------------------------------------------
# 运行模式 / 登录状态 / 账号信息
# ---------------------------------------------------------------------------
def _tail_lines(path: Path, max_bytes: int = 800_000) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="ignore").splitlines()


def client_mode(processes: dict | None = None) -> str:
    """EA App 的运行模式：ui（完整界面）/ silent（Steam 唤起的后台模式）/ stopped。"""
    try:
        import psutil
    except Exception:
        psutil = None  # type: ignore[assignment]
    target = None
    for proc in (processes or list_processes()).values():
        if proc.name.lower() == "eadestop.exe":
            target = proc
            break
    if target is None:
        return "stopped"
    cmdline = ""
    if psutil is not None:
        try:
            cmdline = " ".join(psutil.Process(target.pid).cmdline())
        except Exception:
            cmdline = ""
    lowered = cmdline.lower()
    if "-silent" in lowered or "-ls=backgroundservice" in lowered or "-mode=razor" in lowered:
        return "silent"
    return "ui"


def signin_state() -> tuple[bool | None, str]:
    """从 EA 后台服务日志判断当前 EA 会话是否已登录。"""
    log = EA_LOG_DIR / "EABackgroundServiceVerbose.log"
    lines = _tail_lines(log)
    authenticated: bool | None = None
    stamp = ""
    for raw in lines:
        if "User Session Started/Modified" in raw and "authenticated=" in raw:
            match = re.search(r"authenticated=(\d)", raw)
            if match:
                authenticated = match.group(1) == "1"
                time_match = re.search(r"\[(\d{4}-\d{2}-\d{2}T[^\]]+)\]", raw)
                stamp = time_match.group(1) if time_match else ""
        elif "AuthToken set to" in raw and authenticated is None:
            authenticated = True
    return authenticated, stamp


def decode_token(token: str) -> dict | None:
    """解析 EA Core 日志里的账号 token（仅解码，不校验签名）。"""
    import base64
    import json

    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    nexus = data.get("nexus") or {}
    result: dict = {"platform": nexus.get("pty") or "", "country": (nexus.get("uif") or {}).get("cty") or ""}
    for persona in nexus.get("psif") or []:
        namespace = persona.get("ns")
        if namespace == "cem_ea_id":
            result["ea_id"] = persona.get("dis") or ""
            result["ea_nick"] = persona.get("nic") or ""
        elif namespace == "steam":
            result["steam_nick"] = persona.get("nic") or ""
            result["steam_id"] = persona.get("extref") or ""
    return result


def latest_account_token() -> dict | None:
    log = latest_core_log()
    if log is None:
        return None
    text = _decode_any(log)
    tokens = re.findall(r"keyvalue=([A-Za-z0-9_\-\.]+)", text)
    for token in reversed(tokens):
        payload = decode_token(token)
        if payload and payload.get("ea_id"):
            return payload
    return None


def account_summary() -> str:
    payload = latest_account_token()
    if not payload:
        return ""
    ea = payload.get("ea_id") or ""
    nick = payload.get("ea_nick") or ""
    steam = payload.get("steam_nick") or ""
    steam_id = payload.get("steam_id") or ""
    text = f"EA 账号 {ea}" + (f"（{nick}）" if nick else "")
    if steam:
        text += f" · 绑定 Steam {steam}" + (f"（{steam_id}）" if steam_id else "")
    return text


# ---------------------------------------------------------------------------
# 日志解析（用于定位「激活弹窗」的真实来源）
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ActivationEvent:
    source_log: str
    timestamp: str
    exe_path: str
    game_dir: str | None
    line: str


def _decode_any(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) >= 2 and data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="ignore")
    if data.count(b"\x00") > len(data) * 0.2:
        return data.decode("utf-16-le", errors="ignore")
    return data.decode("utf-8", errors="ignore")


def latest_core_log() -> Path | None:
    try:
        logs = sorted(EA_CORE_LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return logs[0] if logs else None


def parse_activation_events(max_events: int = 6) -> list[ActivationEvent]:
    """从 EA Core 日志里找出 activation.exe 的启动记录。"""
    log = latest_core_log()
    if log is None:
        return []
    text = _decode_any(log)
    if not text:
        return []
    events: list[ActivationEvent] = []
    core_server_dirs: list[str] = []
    current_stamp = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        stamp_match = re.search(r"\[\s*(\d{1,2}:\d{2}:\d{2}(?::\d{1,3})?)\s*\]", line)
        if stamp_match:
            current_stamp = stamp_match.group(1)
        proc_match = re.search(r"CreateProcessW\(\s*([^,]+?)\s*,", line)
        if not proc_match:
            continue
        exe_path = proc_match.group(1).strip().strip('"')
        low = exe_path.lower()
        if "eacoreserver.exe" in low:
            core_server_dirs.append(str(Path(exe_path).parent))
        if "activation" in Path(low).name:
            game_dir = None
            for candidate in reversed(core_server_dirs):
                game_dir = str(Path(candidate).parent) if Path(candidate).name.lower() == "core" else candidate
                break
            events.append(
                ActivationEvent(
                    source_log=str(log),
                    timestamp=current_stamp,
                    exe_path=exe_path,
                    game_dir=game_dir,
                    line=line[:400],
                )
            )
            if len(events) >= max_events:
                break
    return events


def recent_problem_lines(max_lines: int = 20) -> list[str]:
    """返回 EA App 日志里最近的错误 / 授权相关行。"""
    files = []
    for name in ("EABackgroundService.log", "EADesktop.log"):
        path = EA_LOG_DIR / name
        if path.is_file():
            files.append(path)
    if not files:
        return []
    lines: list[str] = []
    for path in files:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                tail = handle.readlines()[-400:]
        except OSError:
            continue
        for raw in tail:
            low = raw.lower()
            if any(keyword in low for keyword in ACTIVATION_LOG_KEYWORDS) or " error " in low:
                lines.append(raw.strip()[:300])
    return lines[-max_lines:]


# ---------------------------------------------------------------------------
# 进程控制
# ---------------------------------------------------------------------------
def _window_pids(names: set[str]) -> dict[int, list[int]]:
    processes = list_processes()
    by_name = {p.pid: p for p in processes.values() if p.name.lower() in names}
    result: dict[int, list[int]] = {}
    for window in enum_windows():
        if window.pid in by_name:
            result.setdefault(window.pid, []).append(window.hwnd)
    return result


def stop_client(include_service: bool = False, timeout: float = 12.0) -> tuple[bool, str]:
    """优雅关闭 EA App（可含后台服务）。"""
    names = {
        "eadestop.exe",
        "ealauncher.exe",
        "eaconnect_microsoft.exe",
        "eassteamlauncher.exe",
        "easteamproxy.exe",
    }
    windows = _window_pids(names)
    for hwnds in windows.values():
        for hwnd in hwnds:
            close_window(hwnd)
    deadline = time.time() + 4
    while time.time() < deadline:
        if not ea_processes():
            break
        time.sleep(0.25)

    killed = terminate_process_names(sorted(names | {"link2ea.exe"}), timeout=timeout)
    details = f"已结束客户端进程: {', '.join(killed) if killed else '无'}"

    if include_service:
        if is_admin():
            for service in ("EABackgroundService", "EALocalHostSvc"):
                code, out = run_command(["sc", "stop", service], timeout=20)
                details += f"；{service}: {'已停止' if code == 0 else out.splitlines()[-1] if out else '停止失败'}"
        else:
            details += "；后台服务需要管理员权限才能重启（已跳过）"
    return True, details


def start_client(wait_seconds: float = 25.0) -> tuple[bool, str]:
    if not EA_DESKTOP_EXE.is_file():
        return False, "没有找到 EA App，请先安装 / 修复 EA App。"
    if any(p.name.lower() == "eadestop.exe" for p in ea_processes()):
        return True, "EA App 已在运行。"
    proc = start_process(str(EA_DESKTOP_EXE), cwd=str(EA_CLIENT_DIR))
    if proc is None:
        return False, "启动 EA App 失败。"
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if any(p.name.lower() == "eadestop.exe" for p in ea_processes()):
            return True, "EA App 已启动，等待其完成登录 / 加载授权。"
        time.sleep(0.4)
    return False, f"EA App 启动后在 {int(wait_seconds)} 秒内没有完成初始化。"


def restart_client(include_service: bool = False) -> tuple[bool, str]:
    ok_stop, stop_msg = stop_client(include_service=include_service)
    time.sleep(1.0)
    ok_start, start_msg = start_client()
    return ok_stop and ok_start, f"{stop_msg}；{start_msg}"


def ensure_running() -> tuple[bool, str]:
    if any(p.name.lower() == "eadestop.exe" for p in ea_processes()):
        return True, "EA App 正在运行。"
    return start_client()


def bf3_license_info() -> dict:
    """检查 BF3 老式授权缓存文件是否存在、有多旧（过期是「无法激活」的常见原因）。"""
    items: list[dict] = []
    newest_age: float | None = None
    for name in LEGACY_BF3_LICENSE_FILES:
        path = LICENSE_DIR / name
        if not path.is_file():
            continue
        try:
            age_days = (time.time() - path.stat().st_mtime) / 86400
        except OSError:
            age_days = 0.0
        items.append({"name": name, "path": str(path), "age_days": round(age_days, 1)})
        if newest_age is None or age_days < newest_age:
            newest_age = age_days
    stale = any(item["age_days"] >= LEGACY_BF3_STALE_DAYS for item in items)
    return {"files": items, "stale": stale, "newest_age_days": newest_age}


def legacy_cache_items() -> list[Path]:
    """老 Origin 下载缓存 / EA Core 临时缓存里的条目（清理授权时会一起挪走）。"""
    items: list[Path] = []
    for directory in (ORIGIN_DOWNLOAD_CACHE,):
        try:
            items.extend(path for path in directory.iterdir())
        except OSError:
            continue
    return items
