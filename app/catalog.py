"""EA 游戏目录：名称、别名、进程名、Steam AppID 与配色。

这里的数据只用于「识别游戏」和「正确的启动方式」，
不包含、也不会用于任何授权绕过逻辑。

注意：Steam AppID 只登记已经过本地 appmanifest 验证的条目；
其余条目留空，由本地 Steam 清单自动补全，避免启动到错误的游戏。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GameDef:
    key: str
    name: str
    name_cn: str
    aliases: tuple[str, ...] = ()
    steam_appid: int | None = None
    exe_names: tuple[str, ...] = ()
    accent: tuple[str, str] = ("#5B8CFF", "#9B8CFF")
    family: str = ""

    @property
    def display(self) -> str:
        return f"{self.name} · {self.name_cn}" if self.name_cn else self.name


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------
# accent 用来渲染游戏卡片的封面渐变（不涉及任何官方素材）。
GAMES: tuple[GameDef, ...] = (
    GameDef(
        "bf3", "Battlefield 3", "战地 3",
        aliases=("battlefield 3", "bf3", "战地 3", "战地3"),
        steam_appid=1238820,
        exe_names=("bf3.exe",),
        accent=("#F0B34A", "#E5603A"), family="battlefield",
    ),
    GameDef(
        "bf4", "Battlefield 4", "战地 4",
        aliases=("battlefield 4", "bf4", "战地 4", "战地4"),
        exe_names=("bf4.exe",),
        accent=("#5B9BFF", "#2D6CF0"), family="battlefield",
    ),
    GameDef(
        "bf1", "Battlefield 1", "战地 1",
        aliases=("battlefield 1", "bf1", "战地 1", "战地1"),
        steam_appid=1238840,
        exe_names=("bf1.exe",),
        accent=("#C8A165", "#8A5B2D"), family="battlefield",
    ),
    GameDef(
        "bfv", "Battlefield V", "战地 5",
        aliases=("battlefield v", "battlefield 5", "bfv", "战地 5", "战地5"),
        steam_appid=1238810,
        exe_names=("bfv.exe",),
        accent=("#7FC7D9", "#2E7D95"), family="battlefield",
    ),
    GameDef(
        "bf2042", "Battlefield 2042", "战地 2042",
        aliases=("battlefield 2042", "bf2042", "bf 2042", "战地 2042", "战地2042"),
        exe_names=("bf2042.exe",),
        accent=("#59E0C0", "#1F7A66"), family="battlefield",
    ),
    GameDef(
        "bfh", "Battlefield Hardline", "战地：硬仗",
        aliases=("battlefield hardline", "hardline", "bfh", "硬仗"),
        exe_names=("bfh.exe",),
        accent=("#8FA7BF", "#3C536B"), family="battlefield",
    ),
    GameDef(
        "bfbc2", "Battlefield: Bad Company 2", "战地：叛逆连队 2",
        aliases=("bad company 2", "bfbc2", "叛逆连队"),
        exe_names=("bfbc2game.exe",),
        accent=("#9CB86A", "#4F6B2E"), family="battlefield",
    ),
    GameDef(
        "apex", "Apex Legends", "Apex 英雄",
        aliases=("apex legends", "apex", "apex英雄"),
        steam_appid=1172470,
        exe_names=("r5apex.exe", "r5apex_dx12.exe"),
        accent=("#FF5C6C", "#B3122E"), family="apex",
    ),
    GameDef(
        "titanfall2", "Titanfall 2", "泰坦陨落 2",
        aliases=("titanfall 2", "titanfall2", "泰坦陨落"),
        exe_names=("titanfall2.exe",),
        accent=("#67C5D8", "#226E85"), family="titanfall",
    ),
    GameDef(
        "swbf2", "Star Wars Battlefront II", "星球大战：前线 2",
        aliases=("battlefront ii", "battlefront 2", "star wars battlefront", "前线 2"),
        exe_names=("starwarsbattlefrontii.exe",),
        accent=("#D6E4F0", "#3E5C7A"), family="starwars",
    ),
    GameDef(
        "jedi_fo", "Star Wars Jedi: Fallen Order", "星球大战 绝地：陨落的武士团",
        aliases=("fallen order", "jedi fallen order", "陨落的武士团"),
        exe_names=("starwarsjedifallenorder.exe",),
        accent=("#8FC1E3", "#2E4A6B"), family="starwars",
    ),
    GameDef(
        "jedi_survivor", "Star Wars Jedi: Survivor", "星球大战 绝地：幸存者",
        aliases=("jedi survivor", "survivor", "幸存者"),
        exe_names=("starwarsjedisurvivor.exe",),
        accent=("#79D0A8", "#265A45"), family="starwars",
    ),
    GameDef(
        "sims4", "The Sims 4", "模拟人生 4",
        aliases=("the sims 4", "sims 4", "模拟人生 4", "模拟人生4"),
        exe_names=("ts4_x64.exe", "ts4.exe"),
        accent=("#6FD6C3", "#1C8B78"), family="sims",
    ),
    GameDef(
        "nfs_heat", "Need for Speed Heat", "极品飞车：热度",
        aliases=("need for speed heat", "nfs heat", "热度"),
        exe_names=("needforspeedheat.exe",),
        accent=("#FF7AC6", "#7A2E86"), family="nfs",
    ),
    GameDef(
        "nfs_unbound", "Need for Speed Unbound", "极品飞车：不羁",
        aliases=("need for speed unbound", "nfs unbound", "不羁"),
        exe_names=("needforspeedunbound.exe",),
        accent=("#B18CFF", "#4A2E8A"), family="nfs",
    ),
    GameDef(
        "me_legendary", "Mass Effect Legendary Edition", "质量效应 传奇版",
        aliases=("mass effect legendary", "质量效应"),
        exe_names=("masseffectlegendaryedition.exe",),
        accent=("#6FB3FF", "#1F4E8C"), family="masseffect",
    ),
    GameDef(
        "me_andromeda", "Mass Effect: Andromeda", "质量效应：仙女座",
        aliases=("mass effect andromeda", "andromeda", "仙女座"),
        exe_names=("masseffectandromeda.exe",),
        accent=("#8C9BFF", "#2E3A8C"), family="masseffect",
    ),
    GameDef(
        "da_inquisition", "Dragon Age: Inquisition", "龙腾世纪：审判",
        aliases=("dragon age inquisition", "inquisition", "龙腾世纪"),
        exe_names=("dragonageinquisition.exe",),
        accent=("#D89B5A", "#6B3A1F"), family="dragonage",
    ),
    GameDef(
        "ittakestwo", "It Takes Two", "双人成行",
        aliases=("it takes two", "双人成行"),
        exe_names=("ittakestwo.exe",),
        accent=("#FF8FB1", "#B0306A"), family="ittakestwo",
    ),
    GameDef(
        "unravel2", "Unravel Two", "毛线小精灵 2",
        aliases=("unravel two", "unravel 2", "毛线小精灵"),
        exe_names=("unraveltwo.exe",),
        accent=("#8AD8A8", "#2E7A4A"), family="unravel",
    ),
    GameDef(
        "anthem", "Anthem", "圣歌",
        aliases=("anthem", "圣歌"),
        exe_names=("anthem.exe",),
        accent=("#7FD4E8", "#1F6B85"), family="anthem",
    ),
    GameDef(
        "deadspace_remake", "Dead Space", "死亡空间",
        aliases=("dead space", "deadspace", "死亡空间"),
        exe_names=("deadspace.exe",),
        accent=("#C0C8D0", "#4A5560"), family="deadspace",
    ),
    GameDef(
        "crysis_remastered", "Crysis Remastered", "孤岛危机 重制版",
        aliases=("crysis remastered", "crysis", "孤岛危机"),
        exe_names=("crysisremastered.exe",),
        accent=("#8FE3C8", "#1F6B5A"), family="crysis",
    ),
    GameDef(
        "cnc_remastered", "Command & Conquer Remastered", "命令与征服 重制版",
        aliases=("command & conquer", "command and conquer", "命令与征服"),
        exe_names=("cnc.exe",),
        accent=("#FFD166", "#9C6B00"), family="cnc",
    ),
    GameDef(
        "pvz_gw2", "Plants vs. Zombies: Garden Warfare 2", "植物大战僵尸：花园战争 2",
        aliases=("garden warfare 2", "pvz gw2", "花园战争"),
        exe_names=("pvzgow2.exe",),
        accent=("#9BE06F", "#3C7A1F"), family="pvz",
    ),
    GameDef(
        "f1_24", "F1 24", "F1 24",
        aliases=("f1 24", "f1 23", "f1 22", "f1"),
        exe_names=("f1_24.exe", "f1_23.exe", "f1_22.exe"),
        accent=("#FF6B6B", "#8C1F1F"), family="f1",
    ),
    GameDef(
        "ea_fc_24", "EA SPORTS FC 24", "EA SPORTS FC 24",
        aliases=("ea sports fc 24", "fc 24", "fifa 23", "fifa"),
        exe_names=("fc24.exe", "fifa23.exe"),
        accent=("#7FE0B0", "#1F7A4A"), family="fc",
    ),
    GameDef(
        "mirrors_edge_catalyst", "Mirror's Edge Catalyst", "镜之边缘：催化剂",
        aliases=("mirror's edge catalyst", "mirrors edge catalyst", "镜之边缘"),
        steam_appid=1233570,
        exe_names=("mirrorsedgecatalyst.exe",),
        accent=("#E8E8F0", "#8C8CB0"), family="me_catalyst",
    ),
    # 老游戏：EA app 通常不再管理，仅用于识别，避免误判
    GameDef(
        "bf1942", "Battlefield 1942", "战地 1942",
        aliases=("battlefield 1942", "bf1942", "战地 1942"),
        exe_names=("bf1942.exe",),
        accent=("#B8A06A", "#5E4A22"), family="battlefield",
    ),
    GameDef(
        "bf2", "Battlefield 2", "战地 2",
        aliases=("battlefield 2", "bf2", "战地 2"),
        exe_names=("bf2.exe",),
        accent=("#A8B86A", "#4A5E22"), family="battlefield",
    ),
)


BY_KEY: dict[str, GameDef] = {g.key: g for g in GAMES}


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------
def normalize_title(text: str) -> str:
    """把窗口标题 / 目录名归一化：去商标符号、标点、多余空白、全角。"""
    text = text.lower()
    text = text.replace("™", "").replace("®", "").replace("©", "")
    text = text.replace("‘", "'").replace("’", "'").replace("　", " ")
    text = re.sub(r"[_\-–—:：]+", " ", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff'& ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ALIAS_INDEX: tuple[tuple[str, GameDef], ...] = tuple(
    sorted(
        (
            (normalize_title(alias), game)
            for game in GAMES
            for alias in (game.name, game.name_cn, *game.aliases)
            if alias
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def match_game_text(text: str) -> GameDef | None:
    """按窗口标题 / 目录名模糊匹配游戏（长别名优先，避免 BF1 命中 BF1942）。"""
    if not text:
        return None
    norm = normalize_title(text)
    if not norm:
        return None
    for alias, game in _ALIAS_INDEX:
        if len(alias) < 2:
            continue
        if alias in norm:
            return game
    return None


def match_game_dir(name: str) -> GameDef | None:
    """按安装目录名匹配游戏。"""
    return match_game_text(name)


def guess_exe_for(game: GameDef | None, install_dir: str | None) -> str | None:
    """在安装目录里找到游戏主程序。"""
    if not install_dir:
        return None
    from pathlib import Path

    root = Path(install_dir)
    if not root.is_dir():
        return None
    if game:
        for exe in game.exe_names:
            candidate = root / exe
            if candidate.is_file():
                return str(candidate)
    try:
        exes = [p for p in root.glob("*.exe") if p.is_file()]
    except OSError:
        return None
    # 排除安装器 / 第三方整合启动器 / 辅助组件
    blocked = (
        "unins", "setup", "install", "eacore", "activation", "pbsvc", "helper",
        "launcher", "updater", "crash", "report", "diagnos", "config", "bench",
    )
    candidates: list[Path] = []
    for path in sorted(exes, key=lambda p: p.stat().st_size, reverse=True):
        low = path.name.lower()
        if any(token in low for token in blocked):
            continue
        if re.search(r"[\u4e00-\u9fff]", path.name):  # 中文命名的多为整合启动器
            continue
        candidates.append(path)
    return str(candidates[0]) if candidates else None
