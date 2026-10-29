"""把「最近一次启动链路」直接打印出来，方便排查 / 反馈问题。

用法：
    .venv\\Scripts\\python.exe tools\\chain_report.py            # 自动选最近启动的 Steam 版 EA 游戏
    .venv\\Scripts\\python.exe tools\\chain_report.py bf3        # 指定游戏 key
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import chain, discovery, eaapp  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    games = discovery.discover_games().games
    key = sys.argv[1] if len(sys.argv) > 1 else ""
    if key:
        wanted = [game for game in games if key.lower() in game.key.lower() or key.lower() in game.name.lower()]
        candidates = [game for game in wanted if game.installed]
    else:
        candidates = [game for game in games if game.installed and game.steam_appid]
    if not candidates:
        print("没有找到已安装的 Steam 版 EA 游戏")
        return 1

    steam_text = chain.read_steam_log()
    core_text = chain.read_core_log()
    mode = eaapp.client_mode()
    analyses = [chain.analyze_game_text(game, steam_text, core_text, mode) for game in candidates]
    if key:
        picked = analyses[0]
    else:
        analyses.sort(
            key=lambda item: item.last_start.when.timestamp() if item.last_start and item.last_start.when else 0,
            reverse=True,
        )
        picked = analyses[0]

    print(f"游戏：{picked.game_name}（AppID {picked.appid}）")
    print(f"判定：{picked.cause_label}  [cause={picked.cause}, 置信度 {int(picked.confidence * 100)}%]")
    print("\n链路时间线：")
    for line in picked.lines:
        print("  ·", line)
    if picked.notes:
        print("\n说明：")
        for note in picked.notes:
            print("  -", note)
    account = eaapp.account_summary()
    if account:
        print("\nEA 账号 / Steam 绑定：", account)
    signed, stamp = eaapp.signin_state()
    print("EA 登录状态：", "已登录" if signed else ("未登录" if signed is False else "未知"), stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
