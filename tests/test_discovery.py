"""游戏发现测试：真实读取本机注册表 / Steam 库（缺少对应游戏时自动跳过）。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import catalog, discovery  # noqa: E402
from app.win32 import path_under  # noqa: E402


def test_discovery_real_machine() -> None:
    found = discovery.discover_games()
    assert found.games, "至少应该返回目录里的游戏条目"
    keys = [game.key for game in found.games]
    assert len(keys) == len(set(keys)), "游戏 key 不能重复"
    installed = [game for game in found.games if game.installed]
    assert installed, "本机应该至少识别到一个已安装 EA 游戏"
    for game in installed:
        assert game.exe and Path(game.exe).is_file(), f"{game.name} 的主程序不存在"
        assert game.install_dir and Path(game.install_dir).is_dir()

    bf3 = next((game for game in found.games if game.key == "bf3"), None)
    if bf3 is None or not bf3.installed:
        print("    (本机未安装 BF3，跳过 Steam AppID 校验)")
        return
    assert bf3.steam_appid == 1238820, bf3.steam_appid
    assert bf3.platform == "steam", bf3.platform
    assert isinstance(bf3.extras, list)
    resolved = discovery.resolve_game_for_path(bf3.exe, found.games)
    assert resolved is not None and resolved.key == "bf3"


def test_steam_libraries() -> None:
    found = discovery.discover_games()
    if not found.steam_root:
        print("    (本机没有 Steam，跳过)")
        return
    assert Path(found.steam_root).is_dir()
    assert found.libraries, "应该能解析出至少一个 Steam 游戏库"
    assert found.steam_apps, "应该能解析出 appmanifest"
    for app in found.steam_apps[:5]:
        assert app.appid > 0 and app.install_dir


def test_resolve_game_for_path_prefers_longest() -> None:
    nested = discovery.InstalledGame(
        key="nested",
        name="Nested",
        name_cn="",
        aliases=[],
        install_dir=r"C:\Games\Battlefield 3\dlc",
        exe=None,
        steam_appid=None,
        platform="ea",
        installed=True,
        accent=("#000", "#111"),
    )
    parent = discovery.InstalledGame(
        key="parent",
        name="Parent",
        name_cn="",
        aliases=[],
        install_dir=r"C:\Games\Battlefield 3",
        exe=None,
        steam_appid=None,
        platform="ea",
        installed=True,
        accent=("#000", "#111"),
    )
    resolved = discovery.resolve_game_for_path(r"C:\Games\Battlefield 3\dlc\bin\game.exe", [parent, nested])
    assert resolved is not None and resolved.key == "nested"


def test_guess_exe_skips_helpers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pbsvc.exe").write_bytes(b"x")
        (root / "unins000.exe").write_bytes(b"x")
        (root / "游戏启动器.exe").write_bytes(b"x")
        assert catalog.guess_exe_for(None, str(root)) is None
        (root / "bf3.exe").write_bytes(b"x" * 10)
        assert catalog.guess_exe_for(None, str(root)) == str(root / "bf3.exe")


def test_path_under() -> None:
    assert path_under(r"C:\Games\A\bin\game.exe", r"C:\Games\A")
    assert path_under(r"C:\Games\A\bin\game.exe", r"C:\Games\A\\")
    assert not path_under(r"C:\Games\AB\game.exe", r"C:\Games\A")
    assert path_under("F:/Steam/steamapps/common/BF3/bf3.exe", r"F:\Steam\steamapps\common\BF3")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"discovery: {len(tests)} tests passed")
