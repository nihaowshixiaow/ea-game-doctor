"""后端自检脚本：不启动 UI，直接跑一遍发现 / 检测 / 诊断链路。

用法：.venv\\Scripts\\python.exe tools\\backend_check.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import catalog, detect, diagnostics, discovery, eaapp  # noqa: E402
from app.config import Settings, bootstrap_dirs  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    bootstrap_dirs()
    started = time.perf_counter()

    print("== EA App ==")
    ea = eaapp.info()
    print(json.dumps({
        "installed": ea.installed,
        "version": ea.version,
        "running": ea.running,
        "processes": ea.processes,
        "service": eaapp.service_status("EABackgroundService"),
    }, ensure_ascii=False, indent=2))

    print("\n== 授权缓存 ==")
    lic = eaapp.license_summary()
    print(f"路径: {lic.path}")
    print(f"文件: {lic.count} 个, 最新 {lic.newest_age_days:.1f} 天前" if lic.newest_age_days else f"文件: {lic.count} 个")
    print(f"文件列表: {lic.files[:8]}")

    print("\n== 协议注册 ==")
    for proto in eaapp.protocol_status():
        print(f"{proto.protocol:8} ok={proto.ok} target={proto.target}")

    print("\n== 激活日志事件 ==")
    events = eaapp.parse_activation_events()
    for event in events[:5]:
        print(f"- {event.timestamp} {event.exe_path} (game_dir={event.game_dir})")
    if not events:
        print("(无)")

    print("\n== 游戏发现 ==")
    found = discovery.discover_games()
    print(f"EA installed={found.ea_installed} steam_root={found.steam_root} steam_running={found.steam_running}")
    print(f"libraries={found.libraries}")
    print(f"steam apps ({len(found.steam_apps)}): {[a.name for a in found.steam_apps][:60]}")
    print(f"errors={found.errors}")
    for game in found.games:
        if game.installed:
            print(f"  [{'x' if game.installed else ' '}] {game.key:22} {game.name:38} {game.platform:8} appid={game.steam_appid} exe={game.exe}")
            if game.extras:
                print(f"      extras: {game.extras}")

    print("\n== 检测扫描 ==")
    started_scan = time.perf_counter()
    scanned = detect.scan(found.games)
    print(f"耗时 {(time.perf_counter() - started_scan) * 1000:.1f} ms")
    print(f"game_windows={[(w.title, w.cls) for w in scanned.game_windows]}")
    print(f"ea_windows={[(w.title, w.cls) for w in scanned.ea_windows]}")
    print(f"issues={[(i.kind, i.game_name, i.confidence, i.title) for i in scanned.issues]}")
    print(f"summary={scanned.summary()}")

    print("\n== 诊断 ==")
    diagnosis = diagnostics.run_checks(found, Settings())
    for check in diagnosis.sorted():
        print(f"[{check.status:5}] {check.title}: {check.detail}")
    print(f"health={diagnosis.health_score} summary={diagnostics.summary_text(diagnosis)}")

    print(f"\n总耗时 {time.perf_counter() - started:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
