"""开发用：离屏渲染各页面截图，便于检查视觉与排版。"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .. import actions, detect
from dataclasses import asdict

from ..config import APP_NAME_CN, CONFIG_FILE, REPORTS_DIR, EventLog, Settings
from . import theme
from .main_window import MainWindow


def _demo_detection(games) -> detect.Detection:
    game = next((item for item in games if item.key == "bf3"), None)
    game_name = game.name if game else "Battlefield 3"
    install_dir = game.install_dir if game else r"F:\2\SteamLibrary\steamapps\common\Battlefield 3"
    issue = detect.Issue(
        kind=detect.KIND_ACTIVATION,
        game_key=game.key if game else "bf3",
        game_name=game_name,
        confidence=0.98,
        evidence=[
            "EA 激活程序 activation.exe 正在运行",
            f"程序路径: {install_dir}\\Core\\activation.exe",
            f"归属游戏目录: {install_dir}",
            "窗口标题: Battlefield 3™",
            "窗口类: Qt5152QWindowIcon · 尺寸: 852×554",
        ],
        hwnd=0x000A11F2,
        pid=18824,
        proc_name="activation.exe",
        title="Battlefield 3™",
        cls="Qt5152QWindowIcon",
    )
    blocked = detect.Issue(
        kind=detect.KIND_BLOCKED,
        game_key=issue.game_key,
        game_name=game_name,
        confidence=0.88,
        evidence=["游戏进程 bf3.exe 已启动，但没有出现游戏窗口", "同时检测到激活 / 授权提示界面"],
        pid=17742,
        proc_name="bf3.exe",
    )
    return detect.Detection(
        issues=[issue, blocked],
        game_windows=[],
        ea_windows=[],
        game_processes=[],
        screen=detect.screen_size(),
    )


def _demo_conclusion(window: MainWindow, game) -> None:
    ctx = actions.RepairContext(
        settings=window.settings,
        log=window.log,
        game=game,
        issue=window.current_issue,
        profile="quick",
    )
    ctx.results = {
        "snapshot": actions.StepResult("ok", "已记录现场（20261029-001500-snapshot.json）"),
        "close_dialog": actions.StepResult("ok", "已关闭 1 个提示窗口，结束 1 个激活进程"),
        "repair_protocol": actions.StepResult("ok", "EA 启动协议注册正常，无需修复"),
        "launch": actions.StepResult("ok", "已通过 Steam 请求启动 Battlefield 3（AppID 1238820）"),
        "verify": actions.StepResult("ok", "游戏窗口已出现，用时约 14.2 秒"),
        "conclude": actions.StepResult("ok", "修复完成：游戏已正常启动"),
    }
    ctx.evidence = [
        "EA 激活程序 activation.exe 正在运行",
        "已通过 Steam 请求启动 Battlefield 3（AppID 1238820）",
        "游戏窗口已出现，用时约 14.2 秒",
    ]
    ctx.concluded = {
        "success": True,
        "analysis": [
            "弹窗已关闭，游戏窗口已正常出现。",
            "本次通过 Steam 启动 —— Steam 版 EA 游戏必须由 Steam 拉起，才能把 Steam 票据交给 EA App 完成授权。",
        ],
        "chain_lines": [
            "Steam 启动记录：10-29 00:39:58（PID 24080）",
            "启动后新增授权缓存：1 个（EA 重新生成了 71067.dlf）",
            "游戏窗口：10-29 01:20:05 出现（bf3.exe）",
        ],
        "report": r"…\\EAGameDoctor\\reports\\20261029-001500-repair-success.json",
    }
    ctx.verify_data = {"result": "window", "elapsed": 14.2}
    window.fix_page.show_conclusion(ctx, report=ctx.concluded["report"])
    for step in actions.build_plan("quick"):
        result = ctx.results.get(step.id)
        if result is not None:
            window.fix_page.on_step_done(step, result)
    window.fix_page.progress.setValue(100)


def render_previews(app: QApplication, out_dir: Path) -> list[Path]:
    from .. import config as app_config
    from .. import eaapp as eaapp_module

    app_config.BASE_DIR_KIND = "user"  # 预览不显示受限环境横幅
    # 预览/文档截图里不出现真实账号信息
    eaapp_module.account_summary = lambda: "EA 账号 DemoPlayer（DemoNick）· 绑定 Steam DemoUser（7656119xxxxxxxxxx）"
    out_dir.mkdir(parents=True, exist_ok=True)
    config_existed = CONFIG_FILE.is_file()
    original_settings = Settings.load()
    window = MainWindow()
    window.resize(1240, 836)
    window._restricted = False
    window.overview_page.set_environment_note("")
    window._timer.stop()
    window.show()
    app.processEvents()

    detection = _demo_detection(window.games)
    window.detection = detection
    window.stats["issues"] = 2
    window.stats["fixes"] = 3
    window.current_issue = detection.issues[0]
    window.current_game = next((game for game in window.games if game.key == detection.issues[0].game_key), None)
    window.overview_page.update_view(
        detection,
        window.diagnosis,
        window.games,
        window.stats,
        window.settings,
        window.ea_info,
        True,
    )
    for level, title, message in (
        ("info", "启动完成", "EA 启动医生 v1.0.0 · 监视已开启"),
        ("warn", "检测到激活异常", "Battlefield 3 · 激活弹窗；证据：EA 激活程序 activation.exe 正在运行"),
        ("action", "自动修复", "检测到 Battlefield 3 的激活弹窗，自动执行快速修复"),
        ("info", "关闭激活弹窗 · 已关闭 1 个提示窗口", "（0.4s）"),
        ("info", "按平台正确启动 · 已通过 Steam 请求启动", "（1.2s）"),
        ("success", "修复成功", "Battlefield 3 已正常启动"),
    ):
        window.log.add(level, title, message)
        app.processEvents()
    window.games_page.populate(window.games, detection)
    window.fix_page.set_issue(window.current_game, detection.issues[0], detection)
    _demo_conclusion(window, window.current_game)

    paths: list[Path] = []
    pages = [
        ("01-overview", window.overview_page),
        ("02-games", window.games_page),
        ("03-fix", window.fix_page),
        ("04-logs", window.logs_page),
        ("05-settings", window.settings_page),
    ]
    for index, (name, page) in enumerate(pages):
        window._switch_page(index)
        app.processEvents()
        time.sleep(0.05)
        app.processEvents()
        target = out_dir / f"{name}.png"
        page.grab().save(str(target))
        paths.append(target)
        full = out_dir / f"{name}-full.png"
        window.grab().save(str(full))
        paths.append(full)

    # 失败状态：展示链路分析与「运行深度修复」入口
    failed_ctx = actions.RepairContext(
        settings=window.settings,
        log=window.log,
        game=window.current_game,
        issue=window.current_issue,
        profile="quick",
    )
    failed_ctx.results = {
        "snapshot": actions.StepResult("ok", "已记录现场（20261029-003146-snapshot.json）"),
        "close_dialog": actions.StepResult("ok", "关闭 1 个窗口，结束 1 个进程"),
        "repair_protocol": actions.StepResult("ok", "EA 启动协议注册正常，无需修复"),
        "launch": actions.StepResult("ok", "已通过 Steam 请求启动 Battlefield 3（AppID 1238820）"),
        "verify": actions.StepResult("fail", "激活弹窗再次出现：说明 EA 仍然认为当前启动没有有效授权"),
        "conclude": actions.StepResult("warn", "未能让游戏正常出现窗口，已生成诊断建议"),
    }
    failed_ctx.chain_analysis = None
    failed_ctx.concluded = {
        "success": False,
        "analysis": [
            "定位到原因：BF3 的老式授权缓存文件（71067.dlf）已经过期/损坏，EA 加载它时卡了 20 秒，随后退回激活界面。",
            "这不是账号授权缺失，也不是启动方式问题：深度修复会备份并删除这些缓存，EA App 重启后会重新生成一份新的授权缓存。",
            "这台机器上正是用这个方法恢复的：删除旧 71067.dlf → EA 重新生成 → 从 Steam 启动，BF3 窗口正常出现。",
            "如果之后再遇到，直接点「运行深度修复」即可（所有删除都会先移到备份目录，可还原）。",
        ],
        "chain_lines": [
            "Steam 启动记录：10-29 00:39:58（PID 24080）",
            "EA 拉起激活界面：10-29 00:40:57（activation.exe）",
            "EA 授权握手超时：1 次（每次 20 秒，cmd_portal_command 无响应）",
            "启动后新增授权缓存：0 个",
            "BF3 老授权缓存年龄：470 天（>60 天视为过期，是本次修复的关键）",
        ],
        "report": r"…\\EAGameDoctor\\reports\\20261029-003255-repair.json",
        "account": "EA 账号 DemoPlayer（DemoNick）· 绑定 Steam DemoUser（7656119xxxxxxxxxx）",
    }
    window.fix_page.show_conclusion(failed_ctx, report=failed_ctx.concluded["report"])
    for step in actions.build_plan("quick"):
        result = failed_ctx.results.get(step.id)
        if result is not None:
            window.fix_page.on_step_done(step, result)

    # 对话框截图（诊断 / 备份）
    from .. import diagnostics as diag_module
    from .pages import BackupsDialog, DiagnosticsDialog

    diag_dialog = DiagnosticsDialog(window)
    diag_dialog.show_diagnosis(diag_module.run_checks(window.discovery, window.settings), execute=False)
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()
    target = out_dir / "06-diagnostics.png"
    diag_dialog.grab().save(str(target))
    paths.append(target)
    diag_dialog.close()

    backups_dialog = BackupsDialog(window)
    backups_dialog.show_backups(
        [
            ("20261029-001120-bf3", "1.2 MB", 11),
            ("20261028-231501-bf3", "1.2 MB", 11),
            ("20261027-220312-general", "0 B", 0),
        ],
        execute=False,
    )
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()
    target = out_dir / "07-backups.png"
    backups_dialog.grab().save(str(target))
    paths.append(target)
    backups_dialog.close()

    window._switch_page(2)
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()
    target = out_dir / "08-fix-manual.png"
    window.grab().save(str(target))
    paths.append(target)

    window._quitting = True
    window.close()
    # 预览不应改动用户配置
    try:
        if config_existed:
            CONFIG_FILE.write_text(__import__("json").dumps(asdict(original_settings), ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            CONFIG_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return paths
