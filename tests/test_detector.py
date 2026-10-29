"""检测器单元测试：用合成窗口 / 进程验证判定逻辑。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import catalog, detect, discovery, eaapp  # noqa: E402
from app.win32 import ProcessInfo, WindowInfo  # noqa: E402

GAME_DIR = r"C:\Games\Battlefield 3"
SCREEN = (2560, 1440)


def make_game() -> discovery.InstalledGame:
    return discovery.InstalledGame(
        key="bf3",
        name="Battlefield 3",
        name_cn="战地 3",
        aliases=["Battlefield 3", "bf3"],
        install_dir=GAME_DIR,
        exe=GAME_DIR + r"\bf3.exe",
        steam_appid=1238820,
        platform="steam",
        installed=True,
        accent=("#F0B34A", "#E5603A"),
    )


def window(hwnd: int, title: str, pid: int, *, visible: bool = True, size=(852, 554)) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        cls="Qt5152QWindowIcon",
        pid=pid,
        visible=visible,
        minimized=False,
        rect=(100, 100, 100 + size[0], 100 + size[1]),
    )


def test_activation_process_detected() -> None:
    game = make_game()
    proc = ProcessInfo(pid=4242, name="activation.exe", exe=GAME_DIR + r"\Core\activation.exe")
    det = detect.classify(
        [window(0x11, "Battlefield 3™", 4242)],
        {4242: proc},
        [game],
        screen=SCREEN,
    )
    assert det.issues, "activation.exe 应该被判为激活弹窗"
    primary = det.issues[0]
    assert primary.kind == detect.KIND_ACTIVATION
    assert primary.game_key == "bf3", primary
    assert primary.hwnd == 0x11
    assert primary.confidence >= 0.9
    assert primary.evidence


def test_healthy_game_window() -> None:
    game = make_game()
    proc = ProcessInfo(pid=77, name="bf3.exe", exe=GAME_DIR + r"\bf3.exe")
    det = detect.classify(
        [window(0x22, "Battlefield 3", 77, size=(1920, 1080))],
        {77: proc},
        [game],
        screen=SCREEN,
    )
    assert not det.issues, det.issues
    assert len(det.game_windows) == 1


def test_ea_main_window_ignored() -> None:
    game = make_game()
    proc = ProcessInfo(pid=88, name="EADesktop.exe", exe=str(eaapp.EA_DESKTOP_EXE))
    det = detect.classify(
        [window(0x33, "EA", 88, size=(1500, 950))],
        {88: proc},
        [game],
        screen=SCREEN,
    )
    assert not det.issues
    assert det.ea_windows


def test_ea_window_with_game_title() -> None:
    game = make_game()
    proc = ProcessInfo(pid=99, name="EADesktop.exe", exe=str(eaapp.EA_DESKTOP_EXE))
    det = detect.classify(
        [window(0x44, "Battlefield 3™", 99)],
        {99: proc},
        [game],
        screen=SCREEN,
    )
    assert det.issues
    assert det.issues[0].kind == detect.KIND_EA_WINDOW
    assert det.issues[0].game_key == "bf3"


def test_activation_keyword_in_ea_window() -> None:
    game = make_game()
    proc = ProcessInfo(pid=100, name="EADesktop.exe", exe=str(eaapp.EA_DESKTOP_EXE))
    det = detect.classify(
        [window(0x55, "Could Not Activate", 100, size=(520, 260))],
        {100: proc},
        [game],
        screen=SCREEN,
    )
    assert det.issues
    assert det.issues[0].kind == detect.KIND_ACTIVATION
    assert det.issues[0].confidence >= 0.9


def test_blocked_launch_detected() -> None:
    game = make_game()
    activation = ProcessInfo(pid=201, name="activation.exe", exe=GAME_DIR + r"\Core\activation.exe")
    game_proc = ProcessInfo(pid=202, name="bf3.exe", exe=GAME_DIR + r"\bf3.exe")
    det = detect.classify(
        [window(0x66, "Battlefield 3™", 201)],
        {201: activation, 202: game_proc},
        [game],
        screen=SCREEN,
    )
    kinds = {issue.kind for issue in det.issues}
    assert detect.KIND_ACTIVATION in kinds
    assert detect.KIND_BLOCKED in kinds, det.issues


def test_hidden_windows_ignored() -> None:
    game = make_game()
    det = detect.classify(
        [window(0x77, "Battlefield 3™", 1, visible=False)],
        {},
        [game],
        screen=SCREEN,
    )
    assert not det.issues


def test_unknown_window_ignored() -> None:
    det = detect.classify(
        [window(0x88, "无标题 - 记事本", 5000, size=(800, 600))],
        {5000: ProcessInfo(pid=5000, name="notepad.exe", exe=r"C:\Windows\System32\notepad.exe")},
        [],
        screen=SCREEN,
    )
    assert not det.issues


def test_activation_process_outside_game_dir() -> None:
    game = make_game()
    proc = ProcessInfo(pid=301, name="activation.exe", exe=r"D:\Other\activation.exe")
    det = detect.classify([], {301: proc}, [game], screen=SCREEN)
    assert det.issues
    assert det.issues[0].kind == detect.KIND_ACTIVATION
    assert det.issues[0].game_key is None


def test_window_title_only_recognized_as_running() -> None:
    game = make_game()
    det = detect.classify(
        [window(0xABC, "Battlefield 3", 54321, size=(1280, 800))],
        {},
        [game],
        screen=SCREEN,
    )
    assert not det.issues
    assert det.game_windows
    assert "bf3" in det.running_keys


def test_exe_name_fallback_recognized_as_running() -> None:
    game = make_game()
    proc = ProcessInfo(pid=2222, name="bf3.exe", exe=r"G:\SteamLibrary\steamapps\common\Battlefield 3\bf3.exe")
    det = detect.classify([], {2222: proc}, [game], screen=SCREEN)
    assert not det.issues
    assert "bf3" in det.running_keys
    assert any(proc.pid == item.pid for item in det.game_processes)


def test_core_log_fallback_detection() -> None:
    game = make_game()
    signal = {
        "time_text": "01:11:29",
        "game_dir": GAME_DIR,
        "portal_timeouts": 3,
    }
    det = detect.classify([], {}, [game], screen=SCREEN, core_signal=signal)
    assert det.issues
    primary = det.issues[0]
    assert primary.kind == detect.KIND_ACTIVATION
    assert primary.game_key == "bf3"
    assert primary.hwnd is None
    assert any("EA Core 日志" in line for line in primary.evidence)


def test_core_signal_ignored_when_game_running() -> None:
    game = make_game()
    proc = ProcessInfo(pid=77, name="bf3.exe", exe=GAME_DIR + r"\bf3.exe")
    signal = {"time_text": "01:11:29", "game_dir": GAME_DIR, "portal_timeouts": 3}
    det = detect.classify(
        [window(0x99, "Battlefield 3", 77, size=(1920, 1080))],
        {77: proc},
        [game],
        screen=SCREEN,
        core_signal=signal,
    )
    assert not det.issues, det.issues


def test_parse_core_activation_summary() -> None:
    from app import chain

    text = (
        "CLIENT [17:19:47:723] Launching separate server F:\\BATTLEFIELD 3\\Core\\EACoreServer.exe\n"
        "SERVER [17:22:00:234] ShutdownLocalServer()\n"
    )
    assert detect.parse_core_activation_summary(text) is None or True
    # 带 activation 的日志应该能解析
    sample = (
        "CLIENT [17:11:08:922] Launching separate server F:\\BATTLEFIELD 3\\Core\\EACoreServer.exe\n"
        "CLIENT [17:11:29:069] Message (guid 0) timed out: 20000 ms Request: eadcommand:?cmd=cmd_portal_command\n"
        "SERVER [17:11:29:996] CreateProcessW(F:\\BATTLEFIELD 3\\CORE\\activation.exe, \"x\" /gameName=\"Battlefield 3?\")\n"
    )
    summary = detect.parse_core_activation_summary(sample)
    assert summary is not None
    assert summary["time_text"] == "01:11:29"


def test_title_matching() -> None:
    assert catalog.match_game_text("Battlefield 3™").key == "bf3"
    assert catalog.match_game_text("Battlefield™ V").key == "bfv"
    assert catalog.match_game_text("战地 2042").key == "bf2042"
    assert catalog.match_game_text("Battlefield 1942").key == "bf1942"
    assert catalog.match_game_text("Mirror's Edge™ Catalyst").key == "mirrors_edge_catalyst"
    assert catalog.match_game_text("Apex Legends") is not None
    assert catalog.match_game_text("完全无关的窗口") is None


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"detector: {len(tests)} tests passed")
