"""EA Game Doctor 入口。

用法：
    python main.py                 启动界面
    python main.py --scan          只做一次检测（JSON 输出，便于排查）
    python main.py --diagnose      输出系统诊断
    python main.py --plan deep     输出修复方案
    python main.py --preview DIR   渲染界面预览图（开发用）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import actions, detect, diagnostics, discovery, eaapp  # noqa: E402
from app.config import APP_NAME_CN, APP_VERSION, Settings  # noqa: E402


def _print_json(payload) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cli_scan() -> int:
    found = discovery.discover_games()
    scanned = detect.scan(found.games)
    _print_json(
        {
            "games": [
                {
                    "key": game.key,
                    "name": game.name,
                    "installed": game.installed,
                    "platform": game.platform,
                    "steam_appid": game.steam_appid,
                    "install_dir": game.install_dir,
                    "exe": game.exe,
                    "third_party": game.extras,
                }
                for game in found.games
            ],
            "issues": [
                {
                    "kind": issue.kind,
                    "game": issue.game_name,
                    "confidence": issue.confidence,
                    "title": issue.title,
                    "process": issue.proc_name,
                    "evidence": issue.evidence,
                }
                for issue in scanned.issues
            ],
            "game_windows": [window.title for window in scanned.game_windows],
            "summary": scanned.summary(),
        }
    )
    return 0


def cli_diagnose() -> int:
    found = discovery.discover_games()
    diagnosis = diagnostics.run_checks(found, Settings())
    _print_json(
        {
            "health": diagnosis.health_score,
            "checks": [
                {
                    "id": check.id,
                    "title": check.title,
                    "status": check.status,
                    "detail": check.detail,
                    "hint": check.hint,
                }
                for check in diagnosis.sorted()
            ],
        }
    )
    return 0


def cli_plan(profile: str) -> int:
    _print_json({"profile": profile, "steps": actions.plan_payload(profile)})
    return 0


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
def run_smoke(out_path: str | None = None) -> int:
    """真实窗口冒烟测试：显示 3 秒后截图退出（开发自检用）。"""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from app.ui import theme

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    theme.init_theme(app)
    app.setStyleSheet(theme.build_qss())

    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    def _capture() -> None:
        if out_path:
            window.grab().save(out_path)
        issues = len(window.detection.issues)
        print(f"smoke: games={len(window.games)} installed={len([g for g in window.games if g.installed])} issues={issues}", flush=True)
        window._quitting = True
        window.close()
        app.quit()

    QTimer.singleShot(3200, _capture)
    return app.exec()


def run_gui(preview_dir: str | None = None) -> int:
    if preview_dir:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from app.ui import theme

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("EAGameDoctor")
    app.setApplicationDisplayName(APP_NAME_CN)
    app.setApplicationVersion(APP_VERSION)
    theme.init_theme(app)
    app.setStyleSheet(theme.build_qss())

    if preview_dir:
        from app.ui.preview import render_previews

        paths = render_previews(app, Path(preview_dir))
        for path in paths:
            print(path)
        return 0

    from app.ui.main_window import MainWindow
    from app.win32 import acquire_single_instance, find_window_by_title

    if not acquire_single_instance("EAGameDoctor.Desktop.Instance"):
        # 已有实例在跑：把它叫到前台，直接退出
        find_window_by_title(APP_NAME_CN)
        return 0

    window = MainWindow()
    window.show()
    return app.exec()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = sys.argv[1:]
    if not args:
        return run_gui()
    if args[0] in ("--scan",):
        return cli_scan()
    if args[0] in ("--diagnose", "--diag"):
        return cli_diagnose()
    if args[0] in ("--plan",):
        return cli_plan(args[1] if len(args) > 1 else "quick")
    if args[0] in ("--smoke",):
        return run_smoke(args[1] if len(args) > 1 else None)
    if args[0] in ("--preview",):
        return run_gui(args[1] if len(args) > 1 else "preview")
    if args[0] in ("--version", "-V"):
        print(f"{APP_NAME_CN} v{APP_VERSION}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
