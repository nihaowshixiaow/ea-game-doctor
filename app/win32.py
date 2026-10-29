"""Windows 相关底层封装：窗口枚举、进程信息、关闭窗口、提权与启动。

全部使用 ctypes / psutil，不依赖 pywin32。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import psutil
except Exception:  # pragma: no cover - psutil 是硬依赖，缺失时给出清晰报错
    psutil = None  # type: ignore[assignment]


user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindow.restype = wt.BOOL
user32.IsIconic.argtypes = [wt.HWND]
user32.IsIconic.restype = wt.BOOL
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.SendMessageTimeoutW.argtypes = [
    wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT, ctypes.POINTER(ctypes.c_size_t)
]
user32.SendMessageTimeoutW.restype = wt.LPARAM
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.GetForegroundWindow.restype = wt.HWND
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

WM_CLOSE = 0x0010
WM_QUIT = 0x0012
SM_CXSCREEN = 0
SM_CYSCREEN = 1
CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class WindowInfo:
    hwnd: int
    title: str
    cls: str
    pid: int
    visible: bool
    minimized: bool
    rect: tuple[int, int, int, int]  # left, top, right, bottom

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def title_clean(self) -> str:
        return self.title.strip()


@dataclass(slots=True)
class ProcessInfo:
    pid: int
    name: str
    exe: str | None
    create_time: float | None = None

    @property
    def name_lower(self) -> str:
        return (self.name or "").lower()


# ---------------------------------------------------------------------------
# 窗口
# ---------------------------------------------------------------------------
def _read_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buf, length + 2)
    return buf.value


def _read_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_info(hwnd: int) -> WindowInfo | None:
    try:
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            rect = wt.RECT(0, 0, 0, 0)
        return WindowInfo(
            hwnd=int(hwnd),
            title=_read_title(hwnd),
            cls=_read_class(hwnd),
            pid=int(pid.value),
            visible=bool(user32.IsWindowVisible(hwnd)),
            minimized=bool(user32.IsIconic(hwnd)),
            rect=(rect.left, rect.top, rect.right, rect.bottom),
        )
    except Exception:
        return None


def enum_windows() -> list[WindowInfo]:
    """枚举全部顶层窗口。"""
    result: list[WindowInfo] = []
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def _callback(hwnd, _lparam):  # type: ignore[no-untyped-def]
        info = window_info(hwnd)
        if info is not None:
            result.append(info)
        return True

    callback = callback_type(_callback)
    user32.EnumWindows(callback, 0)
    return result


def close_window(hwnd: int) -> bool:
    """发送 WM_CLOSE（优雅关闭）。"""
    try:
        return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    except Exception:
        return False


def window_alive(hwnd: int) -> bool:
    try:
        return bool(user32.IsWindow(hwnd))
    except Exception:
        return False


def bring_to_front(hwnd: int) -> None:
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)


def foreground_hwnd() -> int:
    try:
        return int(user32.GetForegroundWindow())
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# 进程
# ---------------------------------------------------------------------------
def list_processes(include_exe: bool = True) -> dict[int, ProcessInfo]:
    if psutil is None:
        return {}
    result: dict[int, ProcessInfo] = {}
    attrs = ["pid", "name"]
    if include_exe:
        attrs += ["exe", "create_time"]
    for proc in psutil.process_iter(attrs, ad_value=None):
        try:
            info = proc.info
            pid = int(info["pid"])
            exe = info.get("exe") if include_exe else None
            result[pid] = ProcessInfo(
                pid=pid,
                name=info.get("name") or "",
                exe=str(exe) if exe else None,
                create_time=info.get("create_time") if include_exe else None,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, TypeError):
            continue
    return result


def process_running(name: str) -> bool:
    name = name.lower()
    if psutil is None:
        return False
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() == name:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def terminate_pid(pid: int, timeout: float = 3.0) -> bool:
    if psutil is None:
        return False
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=timeout)
        return True
    except psutil.NoSuchProcess:
        return True
    except psutil.TimeoutExpired:
        try:
            proc.kill()
            return True
        except Exception:
            return False
    except Exception:
        return False


def terminate_process_names(names: list[str] | tuple[str, ...], timeout: float = 4.0) -> list[str]:
    """按进程名结束进程，返回实际结束的名字列表。"""
    if psutil is None:
        return []
    targets = {n.lower() for n in names}
    killed: list[str] = []
    for proc in list(psutil.process_iter(["pid", "name"])):
        try:
            name = (proc.info["name"] or "").lower()
            if name in targets:
                proc.terminate()
                killed.append(name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if killed:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not any((p.info["name"] or "").lower() in targets for p in psutil.process_iter(["name"])):
                break
            time.sleep(0.15)
    return sorted(set(killed))


def start_process(path: str, args: list[str] | None = None, cwd: str | None = None) -> subprocess.Popen | None:
    try:
        return subprocess.Popen(
            [path, *(args or [])],
            cwd=cwd or str(Path(path).parent),
            close_fds=True,
            creationflags=CREATE_NO_WINDOW if path.lower().endswith(".exe") else 0,
        )
    except OSError:
        return None


def shell_execute(target: str) -> bool:
    """用系统默认方式打开 URL / 文件（等价于双击）。"""
    try:
        os.startfile(target)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def run_command(args: list[str], timeout: float = 15.0) -> tuple[int, str]:
    """静默执行命令，返回 (returncode, 输出)。"""
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode, out.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_elevated() -> bool:
    if is_admin():
        return True
    try:
        return bool(user32.GetShellWindow()) and os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


def relaunch_as_admin(extra_args: list[str] | None = None) -> bool:
    """以管理员身份重新启动当前程序（会弹出 UAC）。"""
    exe = sys.executable
    script = Path(sys.argv[0]).resolve()
    params = " ".join([f'"{script}"', *(extra_args or [])])
    try:
        result = shell32.ShellExecuteW(None, "runas", exe, params, str(script.parent), 1)
        return int(result) > 32
    except Exception:
        return False


_mutex_handle = None


def acquire_single_instance(name: str) -> bool:
    """命名互斥体：已有实例时返回 False。"""
    global _mutex_handle
    try:
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
        kernel32.CreateMutexW.restype = wt.HANDLE
        _mutex_handle = kernel32.CreateMutexW(None, False, name)
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def find_window_by_title(title: str) -> int:
    try:
        user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        user32.FindWindowW.restype = wt.HWND
        user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wt.BOOL
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return int(hwnd)
    except Exception:
        return 0
    return 0


def open_url(url: str) -> bool:
    try:
        os.startfile(url)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def open_folder(path: str) -> bool:
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def quote_path(path: str) -> str:
    return f'"{path}"' if " " in path else path


def norm_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def path_under(child: str | None, parent: str | None) -> bool:
    """判断 child 是否位于 parent 目录内（大小写、分隔符不敏感）。"""
    if not child or not parent:
        return False
    try:
        child_n = norm_path(child)
        parent_n = norm_path(parent).rstrip("\\/")
        return child_n == parent_n or child_n.startswith(parent_n + os.sep)
    except (OSError, ValueError):
        return False
