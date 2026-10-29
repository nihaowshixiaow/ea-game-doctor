"""真实窗口集成测试：创建 Tk 窗口 → Win32 枚举能找到 → 判定 → 关闭。

不依赖游戏，验证「窗口枚举 + 归属判定 + 关闭窗口」这条真实链路。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import detect, discovery  # noqa: E402
from app.win32 import ProcessInfo, close_window, enum_windows, screen_size, window_alive  # noqa: E402

WINDOW_TITLE = "无法激活 · Battlefield 3™"
GAME_DIR = r"C:\Games\Battlefield 3"


def make_game() -> discovery.InstalledGame:
    return discovery.InstalledGame(
        key="bf3",
        name="Battlefield 3",
        name_cn="战地 3",
        aliases=["Battlefield 3"],
        install_dir=GAME_DIR,
        exe=GAME_DIR + r"\bf3.exe",
        steam_appid=1238820,
        platform="steam",
        installed=True,
        accent=("#F0B34A", "#E5603A"),
    )


def test_real_window_detected_and_closed() -> None:
    import tkinter as tk

    assert screen_size()[0] > 100, "拿不到屏幕尺寸"

    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.geometry("420x160+-3200+-3200")  # 放到屏幕外，避免打扰
    root.update()
    try:
        hwnd = 0
        for candidate in enum_windows():
            if candidate.title == WINDOW_TITLE and candidate.visible:
                hwnd = candidate.hwnd
                break
        assert hwnd, f"EnumWindows 没有找到测试窗口：{[w.title for w in enum_windows() if w.title][:10]}"

        proc = ProcessInfo(pid=os.getpid(), name="activation.exe", exe=GAME_DIR + r"\Core\activation.exe")
        detection = detect.classify(
            enum_windows(),
            {os.getpid(): proc},
            [make_game()],
            screen=screen_size(),
        )
        matched = [issue for issue in detection.issues if issue.hwnd == hwnd]
        assert matched, detection.issues
        assert matched[0].kind == detect.KIND_ACTIVATION
        assert matched[0].game_key == "bf3"

        # 关闭窗口：应该真的消失
        assert close_window(hwnd)
        deadline = time.time() + 5
        while time.time() < deadline and window_alive(hwnd):
            try:
                root.update()
            except tk.TclError:
                break
            time.sleep(0.05)
        assert not window_alive(hwnd), "WM_CLOSE 之后窗口仍然存在"
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_real_game_window_recognized_by_title() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title("Battlefield 3")
    root.geometry("900x650+-2500+-2500")
    root.update()
    try:
        detection = detect.classify(enum_windows(), {}, [make_game()], screen=screen_size())
        assert "bf3" in detection.running_keys, detection.running_keys
        assert detection.game_windows, detection.issues
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    test_real_window_detected_and_closed()
    print("  ok  test_real_window_detected_and_closed")
    print("integration: 1 test passed")
