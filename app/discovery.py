"""游戏发现：EA Games 注册表 + Steam 清单（多库）+ 可执行文件识别。"""

from __future__ import annotations

import os
import re
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog
from .catalog import GameDef
from .win32 import norm_path, path_under

STEAM_LIBRARY_HINTS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"D:\Steam",
    r"E:\Steam",
    r"F:\Steam",
    r"F:\2\steam",
    r"G:\Steam",
)

# 第三方整合启动器 / 破解补丁的常见文件名特征（只做提示，不参与修复）
THIRD_PARTY_HINTS = (
    "联机娘", "联机", "hao", "frostbite_fix", "venice", "unleashed", "zlo",
    "一键", "工具", "启动器", "整合", "破解", "crack", "fixbf", "bf3fix",
)


@dataclass(slots=True)
class SteamApp:
    appid: int
    name: str
    install_dir: str
    manifest: str
    state_flags: str = ""
    size_bytes: int = 0


@dataclass(slots=True)
class InstalledGame:
    key: str
    name: str
    name_cn: str
    aliases: list[str]
    install_dir: str | None
    exe: str | None
    steam_appid: int | None
    platform: str  # steam / ea / unknown
    installed: bool
    accent: tuple[str, str]
    registry_name: str | None = None
    extras: list[str] = field(default_factory=list)
    size_bytes: int | None = None

    @property
    def display(self) -> str:
        if self.name_cn and self.name_cn.lower() not in self.name.lower():
            return f"{self.name}  ·  {self.name_cn}"
        return self.name

    @property
    def initials(self) -> str:
        words = [w for w in re.split(r"[\s:：\-–]+", self.name.replace("™", "")) if w]
        if not words:
            return "EA"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][:1] + words[1][:1]).upper()

    @property
    def platform_label(self) -> str:
        return {"steam": "STEAM", "ea": "EA APP", "unknown": "未知来源"}.get(self.platform, "未知来源")


@dataclass(slots=True)
class Discovery:
    games: list[InstalledGame]
    ea_installed: bool
    ea_dir: str | None
    steam_root: str | None
    steam_running: bool
    libraries: list[str]
    steam_apps: list[SteamApp]
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
def _enum_ea_registry() -> list[dict[str, str]]:
    """读取 HKLM\\SOFTWARE\\EA Games（32/64 两视图）。"""
    records: dict[str, dict[str, str]] = {}
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EA Games", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EA Games", winreg.KEY_WOW64_64KEY),
    )
    for hive, path, view in roots:
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
                count = winreg.QueryInfoKey(key)[0]
                for index in range(count):
                    try:
                        sub_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    values: dict[str, str] = {"_key": sub_name}
                    try:
                        with winreg.OpenKey(key, sub_name) as sub:
                            for vindex in range(winreg.QueryInfoKey(sub)[1]):
                                try:
                                    vname, vdata, _ = winreg.EnumValue(sub, vindex)
                                except OSError:
                                    break
                                if isinstance(vdata, str):
                                    values[vname] = vdata
                    except OSError:
                        pass
                    records.setdefault(sub_name.lower(), values)
        except OSError:
            continue
    return list(records.values())


def _clean_registry_name(raw: str) -> str:
    name = raw.replace("?", "").replace("�", "").strip()
    return re.sub(r"\s+", " ", name)


# ---------------------------------------------------------------------------
# Steam
# ---------------------------------------------------------------------------
def _steam_from_registry() -> str | None:
    candidates: list[str] = []
    for hive, path, view in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", 0),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", winreg.KEY_WOW64_64KEY),
    ):
        for value_name in ("SteamPath", "InstallPath"):
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
                    raw = winreg.QueryValueEx(key, value_name)[0]
            except OSError:
                continue
            if isinstance(raw, str) and raw:
                candidates.append(str(Path(raw.replace("/", os.sep))))
    for root in candidates + [Path(p) for p in STEAM_LIBRARY_HINTS]:
        exe = Path(root) / "steam.exe"
        if exe.is_file():
            return str(Path(root))
    return None


def _read_library_folders(steam_root: Path) -> list[str]:
    libs: list[str] = []
    for folder in (steam_root, *[Path(p) for p in STEAM_LIBRARY_HINTS]):
        vdf = folder / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            candidate = Path(match.group(1).replace("\\\\", "\\"))
            if (candidate / "steamapps").is_dir():
                libs.append(str(candidate))
        for match in re.finditer(r'"\d+"\s+"([^"]+)"', text):  # 旧版 vdf
            candidate = Path(match.group(1).replace("\\\\", "\\"))
            if (candidate / "steamapps").is_dir():
                libs.append(str(candidate))
    # 补上当前库目录
    if (steam_root / "steamapps").is_dir():
        libs.append(str(steam_root))
    unique: list[str] = []
    seen: set[str] = set()
    for item in libs:
        key = norm_path(item)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _parse_appmanifest(path: Path) -> SteamApp | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    def grab(key: str) -> str:
        match = re.search(rf'"{key}"\s+"([^"]*)"', text)
        return match.group(1) if match else ""

    appid_raw = grab("appid")
    if not appid_raw.isdigit():
        match = re.search(r"appmanifest_(\d+)\.acf", path.name)
        appid_raw = match.group(1) if match else ""
    if not appid_raw.isdigit():
        return None
    install_dir = grab("installdir")
    if not install_dir:
        return None
    return SteamApp(
        appid=int(appid_raw),
        name=grab("name"),
        install_dir=install_dir,
        manifest=str(path),
        state_flags=grab("StateFlags"),
        size_bytes=int(grab("SizeOnDisk") or 0),
    )


def _collect_steam_apps(libraries: list[str]) -> list[SteamApp]:
    apps: list[SteamApp] = []
    for lib in libraries:
        steamapps = Path(lib) / "steamapps"
        if not steamapps.is_dir():
            continue
        try:
            manifests = list(steamapps.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifest in manifests:
            app = _parse_appmanifest(manifest)
            if app is not None:
                apps.append(app)
    return apps


def steam_running() -> bool:
    from .win32 import process_running

    return process_running("steam.exe") or process_running("steamwebhelper.exe")


def steam_root_path() -> str | None:
    return _steam_from_registry()


def steam_executable() -> str | None:
    root = _steam_from_registry()
    if root:
        exe = Path(root) / "steam.exe"
        if exe.is_file():
            return str(exe)
    return None


# ---------------------------------------------------------------------------
# 发现
# ---------------------------------------------------------------------------
def _find_third_party(install_dir: str | None, main_exe: str | None) -> list[str]:
    if not install_dir:
        return []
    root = Path(install_dir)
    if not root.is_dir():
        return []
    findings: list[str] = []
    try:
        entries = [p for p in root.iterdir() if p.is_file()]
    except OSError:
        return findings
    main_name = Path(main_exe).name.lower() if main_exe else ""
    for entry in entries:
        low = entry.name.lower()
        if low == main_name or entry.suffix.lower() not in {".exe", ".bat", ".cmd"}:
            continue
        if any(token in low for token in THIRD_PARTY_HINTS):
            findings.append(entry.name)
    return sorted(set(findings))


def _scan_common_folders(libraries: list[str]) -> dict[str, str]:
    """扫描 steamapps\\common 下的目录名，作为注册表缺失时的兜底。"""
    found: dict[str, str] = {}
    for library in libraries:
        common = Path(library) / "steamapps" / "common"
        if not common.is_dir():
            continue
        try:
            for child in common.iterdir():
                if child.is_dir():
                    found.setdefault(child.name.lower(), str(child))
        except OSError:
            continue
    return found


def _pick_install_dir(install_folder: str, libraries: list[str], definition: GameDef | None) -> str | None:
    """多库同名目录时，选真正有游戏主程序的那个。"""
    existing: list[str] = []
    for library in libraries:
        candidate = Path(library) / "steamapps" / "common" / install_folder
        if candidate.is_dir():
            existing.append(str(candidate))
    for candidate in existing:
        if catalog.guess_exe_for(definition, candidate):
            return candidate
    return existing[0] if existing else None


def discover_games() -> Discovery:
    errors: list[str] = []
    ea_dir = r"C:\Program Files\Electronic Arts\EA Desktop"
    ea_installed = Path(ea_dir).is_dir()

    registry = _enum_ea_registry()
    steam_root = _steam_from_registry()
    libraries = _read_library_folders(Path(steam_root)) if steam_root else []
    steam_apps = _collect_steam_apps(libraries)
    common_folders = _scan_common_folders(libraries)

    games: dict[str, InstalledGame] = {}

    def add_or_update(game: InstalledGame) -> None:
        existing = games.get(game.key)
        if existing is None:
            games[game.key] = game
            return
        # 合并：保留非空信息
        if not existing.install_dir and game.install_dir:
            existing.install_dir = game.install_dir
        if not existing.exe and game.exe:
            existing.exe = game.exe
        if not existing.steam_appid and game.steam_appid:
            existing.steam_appid = game.steam_appid
        if existing.platform == "unknown" and game.platform != "unknown":
            existing.platform = game.platform
        existing.installed = existing.installed or game.installed
        existing.extras = sorted(set(existing.extras + game.extras))
        if game.registry_name and not existing.registry_name:
            existing.registry_name = game.registry_name

    # 1) 目录内建条目
    for definition in catalog.GAMES:
        game = InstalledGame(
            key=definition.key,
            name=definition.name,
            name_cn=definition.name_cn,
            aliases=list(dict.fromkeys([definition.name, definition.name_cn, *definition.aliases])),
            install_dir=None,
            exe=None,
            steam_appid=definition.steam_appid,
            platform="unknown",
            installed=False,
            accent=definition.accent,
        )
        # Steam 清单
        steam_app = None
        for app in steam_apps:
            matched = catalog.match_game_text(app.name)
            if matched is not None and matched.key == definition.key:
                steam_app = app
                break
        if steam_app is not None:
            install_path = _pick_install_dir(steam_app.install_dir, libraries, definition)
            game.steam_appid = steam_app.appid
            game.platform = "steam"
            if install_path:
                game.install_dir = install_path
                game.installed = True
                game.size_bytes = steam_app.size_bytes or None
        # EA 注册表
        for record in registry:
            display = _clean_registry_name(record.get("DisplayName") or record.get("_key", ""))
            key_name = record.get("_key", "")
            matched = catalog.match_game_text(key_name) or catalog.match_game_text(display)
            if matched is None or matched.key != definition.key:
                continue
            install_dir = record.get("Install Dir") or record.get("Install Dir ") or ""
            install_dir = install_dir.strip().strip('"')
            game.registry_name = display or key_name
            if not game.install_dir and install_dir and Path(install_dir).is_dir():
                game.install_dir = install_dir
                game.installed = True
            if game.platform == "unknown":
                game.platform = "ea"
            break
        # Steam 库目录兜底（EA app 可能把游戏装进 steamapps\common）
        if not game.install_dir:
            for folder_name, folder_path in common_folders.items():
                matched = catalog.match_game_text(folder_name)
                if matched is not None and matched.key == definition.key:
                    game.install_dir = folder_path
                    game.installed = True
                    if game.platform == "unknown":
                        game.platform = "ea"
                    break

        if game.install_dir:
            game.exe = catalog.guess_exe_for(definition, game.install_dir)
            game.extras = _find_third_party(game.install_dir, game.exe)
            # 只有真正找到主程序才算「已安装」；否则是残留目录 / 残缺安装
            if not game.exe:
                game.installed = False
                errors.append(f"{definition.name}: 目录存在但缺少主程序（残留安装）")
        add_or_update(game)

    # 2) 注册表里目录未收录的游戏（例如新作 / 老作）
    for record in registry:
        key_name = record.get("_key", "")
        display_raw = record.get("DisplayName") or key_name
        display = _clean_registry_name(display_raw)
        if not display:
            continue
        matched = catalog.match_game_text(key_name) or catalog.match_game_text(display)
        if matched is not None:
            continue  # 已处理
        install_dir = (record.get("Install Dir") or "").strip().strip('"')
        if not install_dir or not Path(install_dir).is_dir():
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", key_name.lower()).strip("-") or f"ea-{len(games)}"
        exe = catalog.guess_exe_for(None, install_dir)
        if not exe:
            continue  # 空目录 / 残留注册表项，不当作已安装游戏
        add_or_update(
            InstalledGame(
                key=f"reg-{slug}",
                name=display or key_name,
                name_cn="",
                aliases=list(dict.fromkeys([key_name, display])),
                install_dir=install_dir,
                exe=exe,
                steam_appid=None,
                platform="ea",
                installed=bool(exe),
                accent=("#6F7C96", "#3A4256"),
                registry_name=display,
                extras=_find_third_party(install_dir, exe),
            )
        )

    ordered = sorted(games.values(), key=lambda g: (not g.installed, g.name.lower()))
    return Discovery(
        games=ordered,
        ea_installed=ea_installed,
        ea_dir=ea_dir if ea_installed else None,
        steam_root=steam_root,
        steam_running=steam_running(),
        libraries=libraries,
        steam_apps=steam_apps,
        errors=errors,
    )


def resolve_game_for_path(path: str | None, games: list[InstalledGame]) -> InstalledGame | None:
    """根据进程 / 窗口 exe 路径定位游戏（最长匹配）。"""
    if not path:
        return None
    best: InstalledGame | None = None
    best_len = -1
    for game in games:
        if not game.install_dir:
            continue
        if path_under(path, game.install_dir):
            length = len(norm_path(game.install_dir))
            if length > best_len:
                best, best_len = game, length
    return best


def game_running_processes(game: InstalledGame, processes: dict) -> list:
    """返回该游戏目录下正在运行的进程。"""
    result = []
    if not game.install_dir:
        return result
    for proc in processes.values():
        if proc.exe and path_under(proc.exe, game.install_dir):
            result.append(proc)
    return result
