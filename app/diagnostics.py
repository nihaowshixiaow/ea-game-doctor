"""诊断项：把「为什么启动不出来」拆成一条条可验证的结论。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog, chain, discovery, eaapp
from .config import EA_SUPPORT_LINK, Settings, is_restricted_environment
from .discovery import Discovery
from .win32 import is_admin

STATUS_ORDER = {"error": 0, "warn": 1, "info": 2, "ok": 3}


@dataclass(slots=True)
class Check:
    id: str
    title: str
    status: str  # ok / info / warn / error
    detail: str
    hint: str = ""
    action: str = ""  # 供 UI 绑定按钮：elevate / restart_ea / open_logs / link_help
    weight: int = 1


@dataclass(slots=True)
class Diagnosis:
    checks: list[Check] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def sorted(self) -> list[Check]:
        return sorted(self.checks, key=lambda item: STATUS_ORDER.get(item.status, 9))

    @property
    def errors(self) -> list[Check]:
        return [c for c in self.checks if c.status == "error"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def health_score(self) -> int:
        if not self.checks:
            return 0
        total = sum(max(1, c.weight) for c in self.checks)
        gained = sum(max(1, c.weight) * {"ok": 1.0, "info": 0.9, "warn": 0.45, "error": 0.1}[c.status] for c in self.checks)
        return int(round(100 * gained / total))


def _check_third_party(game) -> Check | None:
    if not game.extras:
        return None
    names = "、".join(game.extras[:4])
    return Check(
        id=f"third-party-{game.key}",
        title=f"{game.name}：检测到第三方启动器",
        status="warn",
        detail=f"安装目录里存在非官方启动器 / 补丁：{names}",
        hint="这类启动器会绕过 Steam / EA 的正常启动链，激活弹窗通常就是这么来的。本工具不会修复绕过逻辑，只走官方链路。",
        action="",
    )


def run_checks(discovered: Discovery | None = None, settings: Settings | None = None) -> Diagnosis:
    settings = settings or Settings()
    discovered = discovered or discovery.discover_games()
    checks: list[Check] = []

    if is_restricted_environment():
        checks.append(
            Check(
                id="runtime",
                title="运行环境",
                status="warn",
                detail="当前实例运行在受限环境：数据目录回退到了程序目录，进程/窗口识别可能不完整。",
                hint="从桌面双击「启动 EA 启动医生.bat」重新启动即可恢复正常检测（日志会写回 %LOCALAPPDATA%\\EAGameDoctor）。",
                weight=3,
            )
        )

    admin = is_admin()
    checks.append(
        Check(
            id="admin",
            title="管理员权限",
            status="ok" if admin else "info",
            detail="当前以管理员身份运行。" if admin else "当前不是管理员，协议注册修复 / 后台服务重启会被跳过（其余功能不受影响）。",
            hint="" if admin else "如需完整修复能力，可在设置页点击「以管理员身份重启」。",
            action="" if admin else "elevate",
            weight=1,
        )
    )

    ea = eaapp.info()
    if ea.installed:
        checks.append(
            Check(
                id="ea-app",
                title="EA App",
                status="ok" if ea.running else "warn",
                detail=f"已安装 {ea.version or '未知版本'}，当前{'正在运行' if ea.running else '未运行'}。",
                hint="" if ea.running else "启动游戏前需要 EA App 在后台运行并完成登录。",
                action="" if ea.running else "restart_ea",
                weight=2,
            )
        )
    else:
        checks.append(
            Check(
                id="ea-app",
                title="EA App",
                status="error",
                detail="没有在默认位置找到 EA App。",
                hint="所有 EA 游戏（包括 Steam 版）都需要 EA App 完成授权，请先安装。",
                weight=3,
            )
        )

    service_state = eaapp.service_status("EABackgroundService")
    checks.append(
        Check(
            id="ea-service",
            title="EA 后台服务",
            status="ok" if service_state == "RUNNING" else ("warn" if service_state != "MISSING" else "error"),
            detail=f"EABackgroundService: {service_state}",
            hint="" if service_state == "RUNNING" else "后台服务未运行会导致启动游戏时无法完成授权握手。",
            weight=2,
        )
    )

    protocols = eaapp.protocol_status()
    broken = [p.protocol for p in protocols if not p.ok]
    checks.append(
        Check(
            id="protocols",
            title="EA 启动协议注册",
            status="ok" if not broken else "warn",
            detail="origin / origin2 / link2ea 均正常。" if not broken else f"异常协议：{', '.join(broken)}",
            hint="" if not broken else "协议损坏时，从 Steam 或网页启动会被 EA App 拒绝，表现为激活失败。",
            action="" if not broken else "elevate",
            weight=2,
        )
    )

    license_info = eaapp.license_summary()
    if license_info.count == 0:
        checks.append(
            Check(
                id="license",
                title="授权缓存",
                status="warn",
                detail=f"没有找到授权文件（{license_info.path}）。",
                hint="授权缓存缺失时 EA App 会重新向服务器申请；如果账号确实没有该游戏，就会弹「无法激活」。",
                weight=2,
            )
        )
    else:
        age_text = "未知" if license_info.newest_age_days is None else f"{license_info.newest_age_days:.0f} 天"
        stale = license_info.newest_age_days is not None and license_info.newest_age_days > 45
        checks.append(
            Check(
                id="license",
                title="授权缓存",
                status="warn" if stale else "ok",
                detail=f"{license_info.count} 个授权文件，最新一条更新于 {age_text} 前。",
                hint="缓存较旧时可以先做一次「刷新授权缓存」再启动。" if stale else "",
                weight=1,
            )
        )

    authenticated, session_stamp = eaapp.signin_state()
    if authenticated is True:
        checks.append(
            Check(
                id="ea-session",
                title="EA 登录状态",
                status="ok",
                detail="EA App 会话已登录" + (f"（最近会话 {session_stamp}）" if session_stamp else ""),
                weight=2,
            )
        )
    elif authenticated is False:
        checks.append(
            Check(
                id="ea-session",
                title="EA 登录状态",
                status="warn",
                detail="检测到 EA 会话处于未登录状态。",
                hint="先打开 EA App 完成登录，再启动游戏；未登录时 EA 无法完成授权握手。",
                weight=3,
            )
        )
    else:
        checks.append(
            Check(
                id="ea-session",
                title="EA 登录状态",
                status="info",
                detail="无法从日志判断登录状态（EA App 可能从未启动过）。",
                weight=1,
            )
        )

    account_text = eaapp.account_summary()
    if account_text:
        checks.append(
            Check(
                id="ea-account",
                title="EA 账号绑定信息",
                status="info",
                detail=account_text,
                hint="确认这个 EA 账号就是拥有游戏的账号；如果以前用别的 EA/Origin 账号激活过该游戏，需要登录那个账号。",
                weight=2,
            )
        )

    mode = eaapp.client_mode()
    if mode == "silent":
        checks.append(
            Check(
                id="ea-mode",
                title="EA App 运行模式",
                status="info",
                detail="Steam 拉起的是后台静默模式（-silent）。",
                hint="老游戏（如 BF3）在静默模式下授权握手可能失败；可以试「深度修复」，它会以完整界面重启 EA App。",
                weight=1,
            )
        )

    if discovered.steam_root:
        checks.append(
            Check(
                id="steam",
                title="Steam",
                status="ok" if discovered.steam_running else "info",
                detail=f"Steam 路径：{discovered.steam_root}，{'正在运行' if discovered.steam_running else '未运行'}，共 {len(discovered.libraries)} 个游戏库。",
                hint="" if discovered.steam_running else "Steam 版 EA 游戏必须由 Steam 启动，Steam 没运行或没登录时会退回「激活」流程。",
                weight=1,
            )
        )
    else:
        checks.append(
            Check(
                id="steam",
                title="Steam",
                status="info",
                detail="未检测到 Steam。",
                weight=1,
            )
        )

    activation_events = eaapp.parse_activation_events(max_events=3)
    if activation_events:
        latest = activation_events[0]
        game_hint = ""
        if latest.game_dir:
            matched = catalog.match_game_dir(Path(latest.game_dir).name)
            game_hint = f"（{matched.name}）" if matched else ""
        checks.append(
            Check(
                id="core-activation",
                title="EA Core 日志：发现激活程序启动记录",
                status="warn",
                detail=f"最近一次 activation.exe 于 {latest.timestamp or '未知时间'} 被拉起{game_hint}：{Path(latest.exe_path).parent}",
                hint="这说明 EA Core 走到了「需要激活」分支，通常和启动方式 / 账号授权有关。",
                weight=3,
            )
        )
    elif eaapp.latest_core_log() is not None:
        checks.append(
            Check(
                id="core-activation",
                title="EA Core 日志",
                status="ok",
                detail="最近的 Core 日志里没有 activation.exe 启动记录。",
                weight=1,
            )
        )

    installed_games = [g for g in discovered.games if g.installed]
    if installed_games:
        checks.append(
            Check(
                id="games",
                title="游戏库",
                status="ok",
                detail=f"识别到 {len(installed_games)} 个已安装的 EA 游戏。",
                weight=1,
            )
        )
    else:
        checks.append(
            Check(
                id="games",
                title="游戏库",
                status="warn",
                detail="没有识别到已安装的 EA 游戏。",
                hint="如果游戏装在非默认目录，请在设置里确认 Steam 库 / 注册表信息。",
                weight=1,
            )
        )

    chain_check = _chain_check(discovered)
    if chain_check is not None:
        checks.append(chain_check)

    stubs = [g for g in discovered.games if g.install_dir and not g.installed and not g.exe]
    if stubs:
        checks.append(
            Check(
                id="stub-folders",
                title="残留安装目录",
                status="info",
                detail=f"{len(stubs)} 个游戏只有残留目录 / 注册表项，缺少主程序：" + "、".join(g.name for g in stubs[:5]),
                hint="这些条目无法启动，通常是在 Steam / EA App 里删除或移动过游戏文件，需要重新安装。",
                weight=1,
            )
        )

    for game in installed_games:
        if not game.exe or not Path(game.exe).is_file():
            checks.append(
                Check(
                    id=f"exe-{game.key}",
                    title=f"{game.name}：主程序缺失",
                    status="error",
                    detail=f"安装目录 {game.install_dir or '未记录'} 里没有找到可执行文件。",
                    hint="请在 EA App / Steam 里对游戏执行「修复」或重新安装。",
                    weight=2,
                )
            )
        third = _check_third_party(game)
        if third is not None:
            checks.append(third)

    if settings.prefer_steam and installed_games:
        steam_games = [g for g in installed_games if g.platform == "steam" and g.steam_appid]
        if steam_games:
            checks.append(
                Check(
                    id="steam-launch",
                    title="启动方式",
                    status="info",
                    detail=f"{len(steam_games)} 个游戏由 Steam 管理，优先通过 Steam 启动（这是 Steam 版 EA 游戏的正确启动方式）。",
                    weight=1,
                )
            )

    checks.append(
        Check(
            id="support",
            title="官方求助入口",
            status="info",
            detail="如果确认账号已拥有该游戏但仍然提示无法激活，请按 EA 官方步骤核对 Steam 与 EA 账号绑定。",
            hint=EA_SUPPORT_LINK,
            action="link_help",
            weight=1,
        )
    )

    return Diagnosis(checks=checks)


def summary_text(diagnosis: Diagnosis) -> str:
    errors = len(diagnosis.errors)
    warns = len(diagnosis.warnings)
    if errors:
        return f"{errors} 个严重问题、{warns} 个提醒"
    if warns:
        return f"{warns} 个提醒"
    return "全部检查通过"


def _chain_check(discovered) -> Check | None:
    """分析最近一次 Steam → EA 启动链路，把「启动方式问题」和「账号授权问题」分开。"""
    steam_games = [game for game in discovered.games if game.installed and game.steam_appid]
    if not steam_games:
        return None
    try:
        steam_text = chain.read_steam_log(discovered.steam_root)
        core_text = chain.read_core_log()
        analyses = [chain.analyze_game_text(game, steam_text, core_text) for game in steam_games[:8]]
    except Exception:
        return None
    analyses.sort(key=lambda item: (item.last_start.when.timestamp() if item.last_start and item.last_start.when else 0), reverse=True)
    analysis = analyses[0]
    status = "warn" if analysis.cause in ("ea_portal_timeout_no_license", "activation_no_entitlement", "steam_not_launched") else "info"
    if analysis.cause == "no_activation":
        status = "ok"
    detail = f"最近一次链路（{analysis.game_name}）：{analysis.cause_label}"
    hint = "；".join(analysis.notes[:2])
    return Check(id="launch-chain", title="最近一次启动链路", status=status, detail=detail, hint=hint, weight=4)
