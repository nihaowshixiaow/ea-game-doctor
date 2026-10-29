"""主窗口：布局、监视循环、修复调度、托盘与页面联动。"""

from __future__ import annotations

import os
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizeGrip,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import actions, catalog, detect, diagnostics, discovery, eaapp
from ..actions import BackupStore, RepairContext, RepairRunner, RunnerCallbacks, list_backups, restore_backup
from ..config import (
    APP_NAME_CN,
    APP_VERSION,
    is_restricted_environment,
    BACKUPS_DIR,
    LOGS_DIR,
    REPORTS_DIR,
    EventLog,
    Settings,
    human_size,
)
from ..win32 import is_admin, open_folder, open_url, relaunch_as_admin
from . import theme
from .pages import (
    BackupsDialog,
    DiagnosticsDialog,
    FixPage,
    GamesPage,
    LogsPage,
    OverviewPage,
    SettingsPage,
)
from .widgets import IconWidget, Pill, PulseDot, label


def make_app_icon(size: int = 64) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(0, 0, size, size)
    path = QPainterPath()
    path.addRoundedRect(rect.adjusted(1, 1, -1, -1), size * 0.28, size * 0.28)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor(theme.ACCENT))
    gradient.setColorAt(1, QColor(theme.ACCENT_2))
    painter.fillPath(path, gradient)
    painter.setClipping(True)
    painter.setClipPath(path)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 36))
    painter.drawEllipse(QRectF(size * 0.55, -size * 0.25, size * 0.75, size * 0.75))
    from .widgets import _paint_icon

    _paint_icon(painter, "shield", QRectF(size * 0.18, size * 0.14, size * 0.64, size * 0.7), QColor("#0A1020"), size * 0.06)
    painter.end()
    return pixmap


class WorkerBridge(QObject):
    step_started = Signal(object)
    step_done = Signal(object, object)
    log_line = Signal(str, str)
    finished = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.log = EventLog(file_path=LOGS_DIR / "app.log")
        self.discovery: discovery.Discovery | None = None
        self.games: list = []
        self.detection = detect.Detection(issues=[], game_windows=[], ea_windows=[], game_processes=[], screen=detect.screen_size())
        self.diagnosis = diagnostics.Diagnosis()
        self.ea_info = eaapp.info()
        self.stats = {
            "scans": 0,
            "issues": int(getattr(self.settings, "total_detections", 0) or 0),
            "fixes": int(getattr(self.settings, "total_fixes", 0) or 0),
            "license_count": 0,
            "steam_running": False,
        }
        self.current_issue: detect.Issue | None = None
        self.current_game = None
        self.fixing = False
        self.last_report: str = ""
        self._runner: RepairRunner | None = None
        self._ctx: RepairContext | None = None
        self._last_issue_sig = ""
        self._auto_cooldown_until = 0.0
        self._escalated = False
        self._restricted = is_restricted_environment()
        self._drag_offset: QPoint | None = None
        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._quitting = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(APP_NAME_CN)
        self.setWindowIcon(QIcon(make_app_icon(64)))
        self.resize(1240, 836)
        self.setMinimumSize(1080, 720)

        self._build_ui()
        self._build_tray()
        self._wire_signals()
        self._refresh_slow(initial=True)
        self._scan_fast(manual=False)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(self.settings.interval_ms)
        self._apply_settings_to_ui()
        if self._restricted:
            self.overview_page.set_environment_note("受限环境：进程识别可能不完整，建议从桌面双击启动")
            self.log.warn(
                "受限运行环境",
                "当前实例无法写入 %LOCALAPPDATA%\\EAGameDoctor（数据回退到程序目录），进程/窗口识别可能不完整；请从桌面双击「启动 EA 启动医生.bat」重新启动。",
            )
        self.log.info("启动完成", f"{APP_NAME_CN} v{APP_VERSION} · 监视已开启")

    # ------------------------------------------------------------------
    # 构建 UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        container = QWidget()
        self.setCentralWidget(container)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)

        self.root = QFrame()
        self.root.setObjectName("Root")
        self.root.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(self.root)
        try:
            from PySide6.QtWidgets import QGraphicsDropShadowEffect

            shadow = QGraphicsDropShadowEffect(self.root)
            shadow.setBlurRadius(42)
            shadow.setColor(QColor(0, 0, 0, 165))
            shadow.setOffset(0, 10)
            self.root.setGraphicsEffect(shadow)
        except Exception:
            pass

        root_layout = QVBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 标题栏
        self.titlebar = QFrame()
        self.titlebar.setObjectName("TitleBar")
        self.titlebar.setAttribute(Qt.WA_StyledBackground, True)
        self.titlebar.setFixedHeight(56)
        title_layout = QHBoxLayout(self.titlebar)
        title_layout.setContentsMargins(20, 0, 12, 0)
        title_layout.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(make_app_icon(26))
        title_layout.addWidget(logo)
        title_layout.addWidget(label(APP_NAME_CN, "h3"))
        title_layout.addWidget(label(f"v{APP_VERSION}", "small"))
        title_layout.addStretch(1)
        self.title_status = Pill("监视中", "ok")
        title_layout.addWidget(self.title_status)
        self.min_button = _WindowButton("min")
        self.min_button.clicked.connect(self.showMinimized)
        title_layout.addWidget(self.min_button)
        self.close_button = _WindowButton("close")
        self.close_button.clicked.connect(self.close)
        title_layout.addWidget(self.close_button)
        root_layout.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # 侧边栏
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(206)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 10, 14, 16)
        side_layout.setSpacing(6)
        self.nav_buttons: list = []
        for index, (icon_name, text) in enumerate(
            (
                ("overview", "概览"),
                ("games", "游戏库"),
                ("fix", "修复中心"),
                ("logs", "事件日志"),
                ("settings", "设置"),
            )
        ):
            from .widgets import NavButton

            button = NavButton(icon_name, text)
            button.clicked.connect(lambda _=False, i=index: self._switch_page(i))
            side_layout.addWidget(button)
            self.nav_buttons.append(button)
        side_layout.addStretch(1)

        guard_card = QFrame()
        guard_card.setObjectName("CardSoft")
        guard_card.setAttribute(Qt.WA_StyledBackground, True)
        guard_layout = QVBoxLayout(guard_card)
        guard_layout.setContentsMargins(12, 12, 12, 12)
        guard_layout.setSpacing(6)
        guard_header = QHBoxLayout()
        self.side_pulse = PulseDot(theme.SUCCESS, 9)
        guard_header.addWidget(self.side_pulse, 0, Qt.AlignVCenter)
        self.side_status = label("监视中", "body")
        guard_header.addWidget(self.side_status)
        guard_header.addStretch(1)
        guard_layout.addLayout(guard_header)
        self.side_hint = label("", "small")
        self.side_hint.setWordWrap(True)
        guard_layout.addWidget(self.side_hint)
        side_layout.addWidget(guard_card)
        side_layout.addSpacing(4)
        side_layout.addWidget(label(f"仅修复启动链 · 不绕过授权", "small"))
        body.addWidget(sidebar)

        # 内容区
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 16, 22, 10)
        content_layout.setSpacing(12)
        self.stack = QStackedWidget()
        self.overview_page = OverviewPage()
        self.games_page = GamesPage()
        self.fix_page = FixPage()
        self.logs_page = LogsPage()
        self.settings_page = SettingsPage(self.settings)
        for page in (self.overview_page, self.games_page, self.fix_page, self.logs_page, self.settings_page):
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        body.addWidget(content, 1)
        root_layout.addLayout(body, 1)

        # 底部状态栏
        footer = QFrame()
        footer.setFixedHeight(38)
        foot_layout = QHBoxLayout(footer)
        foot_layout.setContentsMargins(20, 0, 16, 0)
        foot_layout.setSpacing(10)
        self.footer_pulse = PulseDot(theme.SUCCESS, 7)
        foot_layout.addWidget(self.footer_pulse, 0, Qt.AlignVCenter)
        self.footer_status = label("监视中", "small")
        foot_layout.addWidget(self.footer_status)
        foot_layout.addWidget(_Separator())
        self.footer_last = label("", "small")
        foot_layout.addWidget(self.footer_last, 1)
        self.admin_pill = Pill("普通用户", "muted")
        foot_layout.addWidget(self.admin_pill)
        self.data_button = QPushButton("数据目录")
        self.data_button.setProperty("btn", "mini")
        self.data_button.setCursor(Qt.PointingHandCursor)
        self.data_button.clicked.connect(lambda: open_folder(str(BACKUPS_DIR.parent)))
        foot_layout.addWidget(self.data_button)
        grip = QSizeGrip(footer)
        foot_layout.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        root_layout.addWidget(footer)

        self._switch_page(0)
        self.titlebar.mousePressEvent = self._title_press  # type: ignore[method-assign]
        self.titlebar.mouseMoveEvent = self._title_move  # type: ignore[method-assign]
        self.titlebar.mouseReleaseEvent = self._title_release  # type: ignore[method-assign]
        self.titlebar.mouseDoubleClickEvent = self._title_double  # type: ignore[method-assign]

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(QIcon(make_app_icon(64)), self)
        menu = QMenu()
        show_action = QAction("显示主界面", self)
        show_action.triggered.connect(self._show_from_tray)
        menu.addAction(show_action)
        self.monitor_action = QAction("暂停监视", self, checkable=True)
        self.monitor_action.toggled.connect(self._toggle_monitor_from_tray)
        menu.addAction(self.monitor_action)
        scan_action = QAction("立即扫描", self)
        scan_action.triggered.connect(lambda: self._scan_fast(manual=True))
        menu.addAction(scan_action)
        menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)
        self._tray_menu = menu
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(lambda reason: self._show_from_tray() if reason == QSystemTrayIcon.DoubleClick else None)
        self._tray.show()

    def _wire_signals(self) -> None:
        self.log.subscribe(self._on_log_event)
        self.overview_page.scan_requested.connect(lambda: self._scan_fast(manual=True))
        self.overview_page.fix_requested.connect(self._open_fix_page)
        self.overview_page.open_logs_requested.connect(lambda: self._switch_page(3))
        self.overview_page.open_diagnostics_requested.connect(self._show_diagnostics)
        self.overview_page.monitor_toggled.connect(self._set_monitor)
        self.games_page.launch_requested.connect(self._launch_game)
        self.games_page.fix_requested.connect(self._fix_game)
        self.games_page.diagnose_requested.connect(self._show_diagnostics)
        self.games_page.refresh_requested.connect(lambda: self._refresh_slow(force=True))
        self.fix_page.run_requested.connect(self._run_fix)
        self.fix_page.cancel_requested.connect(self._cancel_fix)
        self.fix_page.rescan_requested.connect(self._open_fix_page)
        self.fix_page.open_report_requested.connect(self._open_report)
        self.fix_page.restore_requested.connect(self._restore_latest)
        self.fix_page.deep_fix_requested.connect(self._run_deep_fix)
        self.fix_page.open_help_requested.connect(self._open_help)
        self.logs_page.export_requested.connect(self._export_logs)
        self.logs_page.clear_requested.connect(self._clear_logs)
        self.settings_page.settings_changed.connect(self._on_settings_changed)
        self.settings_page.elevate_requested.connect(self._elevate)
        self.settings_page.open_backups_requested.connect(self._show_backups)
        self.settings_page.restore_latest_requested.connect(self._restore_latest)
        self.settings_page.open_logs_requested.connect(lambda: open_folder(str(LOGS_DIR)))
        self.settings_page.open_data_requested.connect(lambda: open_folder(str(BACKUPS_DIR.parent)))
        self.settings_page.open_help_requested.connect(self._open_help)

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------
    def _refresh_slow(self, initial: bool = False, force: bool = False) -> None:
        try:
            self.discovery = discovery.discover_games()
            self.games = self.discovery.games
            self.diagnosis = diagnostics.run_checks(self.discovery, self.settings)
            self.ea_info = eaapp.info()
            self.stats["license_count"] = eaapp.license_summary().count
            self.stats["steam_running"] = self.discovery.steam_running
        except Exception as exc:  # 任何环境异常都不应让 UI 崩溃
            self.log.error("扫描游戏失败", str(exc))
        self.games_page.populate(self.games, self.detection)
        self.overview_page.update_view(
            self.detection,
            self.diagnosis,
            self.games,
            self.stats,
            self.settings,
            self.ea_info,
            self.discovery.steam_running if self.discovery else False,
        )
        self._update_backup_info()
        if initial:
            self._log_startup_summary()

    def _scan_fast(self, manual: bool = False) -> None:
        if self.fixing:
            return
        try:
            self.detection = detect.scan(self.games)
        except Exception as exc:
            self.log.warn("扫描窗口失败", str(exc))
            return
        self.ea_info = eaapp.info() if (manual or self.detection.issues) else self.ea_info
        self.stats["scans"] += 1
        self.overview_page.update_view(
            self.detection,
            self.diagnosis,
            self.games,
            self.stats,
            self.settings,
            self.ea_info,
            self.discovery.steam_running if self.discovery else False,
        )
        self._refresh_issue_view(manual=manual)
        self._update_footer()
        if manual:
            if self.detection.issues:
                primary = self.detection.primary
                self.log.warn(
                    "扫描发现异常",
                    f"{primary.kind_label} · {primary.game_name}（置信度 {int(primary.confidence * 100)}%）",
                )
            elif self.detection.game_windows:
                self.log.success("扫描完成", "检测到游戏窗口正在运行")
            else:
                self.log.info("扫描完成", "没有发现激活弹窗，EA 相关窗口状态正常")
        self._maybe_auto_fix()

    def _refresh_issue_view(self, manual: bool = False) -> None:
        issue = self.detection.primary
        signature = "|".join(sorted(item.signature for item in self.detection.issues))
        if issue is None:
            if self.current_issue is not None or manual:
                self.current_issue = None
                self.current_game = None
                self.fix_page.set_issue(None, None, self.detection)
            return
        changed = signature != self._last_issue_sig
        if changed or manual or self.current_game is None:
            self._last_issue_sig = signature
            self.current_issue = issue
            self.current_game = self._game_for_issue(issue)
            self.fix_page.set_issue(self.current_game, issue, self.detection)
            self.fix_page.show_plan(self.fix_page.profile.value())
            self.fix_page.run_button.setEnabled(True)
            if changed:
                self.stats["issues"] += 1
                self.log.warn(
                    "检测到激活异常",
                    f"{issue.game_name} · {issue.kind_label}；证据：{'；'.join(issue.evidence[:2])}",
                )
                self._notify("检测到激活异常", f"{issue.game_name}：{issue.kind_label}")

    def _game_for_issue(self, issue: detect.Issue):
        if issue.game_key:
            for game in self.games:
                if game.key == issue.game_key:
                    return game
        return None

    def _update_footer(self) -> None:
        prefix = "受限环境 · " if self._restricted else ""
        if self.settings.monitor_enabled:
            self.footer_status.setText(f"{prefix}监视中 · 每 {self.settings.interval_ms / 1000:.1f} 秒扫描")
            self.footer_pulse.set_color(theme.WARN if self._restricted else theme.SUCCESS)
        else:
            self.footer_status.setText(f"{prefix}监视已暂停")
            self.footer_pulse.set_color(theme.TEXT_MUTED)
        events = self.log.items()
        if events:
            last = events[-1]
            self.footer_last.setText(f"{last.time_text} · {last.title}")
        else:
            self.footer_last.setText("")
        self.admin_pill.set_kind("accent" if is_admin() else "muted", "管理员" if is_admin() else "普通用户")
        if self._restricted:
            self.title_status.set_kind("warn", "受限模式")
        else:
            self.title_status.set_kind("ok" if self.settings.monitor_enabled else "muted", "监视中" if self.settings.monitor_enabled else "已暂停")
        self.side_status.setText("监视中" if self.settings.monitor_enabled else "已暂停")
        self.side_pulse.set_color(theme.SUCCESS if self.settings.monitor_enabled else theme.TEXT_MUTED)
        installed = [game for game in self.games if game.installed]
        hints = [f"{len(installed)} 款游戏", "EA App 运行中" if self.ea_info.running else "EA App 未运行"]
        if self.detection.issues:
            hints.insert(0, f"{len(self.detection.issues)} 个异常")
        self.side_hint.setText(" · ".join(hints))
        if self._tray is not None:
            self._tray.setToolTip(f"{APP_NAME_CN} · {'监视中' if self.settings.monitor_enabled else '已暂停'}")

    def _log_startup_summary(self) -> None:
        installed = [game for game in self.games if game.installed]
        parts = [f"识别到 {len(installed)} 款已安装 EA 游戏"]
        if self.discovery and self.discovery.steam_root:
            parts.append(f"Steam 库 {len(self.discovery.libraries)} 个")
        parts.append(f"授权缓存 {self.stats['license_count']} 条")
        self.log.info("环境就绪", "；".join(parts))
        for check in self.diagnosis.sorted():
            if check.status == "error":
                self.log.error(check.title, check.detail)
            elif check.status == "warn":
                self.log.warn(check.title, check.detail)

    # ------------------------------------------------------------------
    # 页面切换
    # ------------------------------------------------------------------
    def _switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)

    def _open_fix_page(self) -> None:
        self._switch_page(2)
        if self.current_issue is None:
            self.log.info("修复中心", "当前没有检测到问题；可以先启动游戏，出现弹窗后会自动跳转")
        else:
            self.fix_page.set_issue(self.current_game, self.current_issue, self.detection)
            self.fix_page.run_button.setEnabled(True)
        self._refresh_issue_view(manual=True)

    def _fix_game(self, game_key: str) -> None:
        game = next((item for item in self.games if item.key == game_key), None)
        if game is None:
            return
        self._switch_page(2)
        if self.current_issue is not None and self.current_issue.game_key == game_key:
            self.fix_page.set_issue(game, self.current_issue, self.detection)
        else:
            self.fix_page.set_issue(game, detect.Issue(
                kind=detect.KIND_ACTIVATION,
                game_key=game.key,
                game_name=game.name,
                confidence=0.5,
                evidence=["手动选择该游戏进行修复", f"启动方式：{'Steam' if game.steam_appid else '主程序'}"],
            ), self.detection)
            self.current_game = game
        self.fix_page.run_button.setEnabled(True)

    # ------------------------------------------------------------------
    # 修复流程
    # ------------------------------------------------------------------
    def _run_fix(self, profile: str) -> None:
        if self.fixing:
            return
        if self.current_issue is None and self.current_game is None:
            self.log.warn("无法开始修复", "没有识别到游戏；请先启动一次游戏，出现激活弹窗后再试")
            return
        if profile == "deep" and self.settings.confirm_deep:
            from .widgets import ConfirmDialog

            dialog = ConfirmDialog(self)
            confirmed = dialog.ask(
                "执行深度修复？",
                "深度修复会关闭 EA App、结束残留游戏进程，并把授权缓存移动到备份目录（可还原）。",
                "适合场景：快速修复后仍然反复提示无法激活。不会修改游戏文件，也不会绕过授权。",
            )
            if not confirmed:
                return
        game = self.current_game or self._game_for_issue(self.current_issue) if self.current_issue else self.current_game
        ctx = RepairContext(
            settings=self.settings,
            log=self.log,
            game=game,
            issue=self.current_issue,
            detection=self.detection,
            games=self.games,
            profile=profile,
            verify_timeout=self.settings.verify_timeout,
        )
        ctx.backup = BackupStore(label=game.key if game else "general")
        self._ctx = ctx
        self.fixing = True
        self.fix_page.set_busy(True)
        self.fix_page.set_issue(game, self.current_issue, self.detection)
        self.log.action("开始修复", f"{actions.PROFILE_LABELS.get(profile, profile)} · {ctx.game_name}")
        bridge = WorkerBridge()
        bridge.step_started.connect(self.fix_page.on_step_started)
        bridge.step_done.connect(self.fix_page.on_step_done)
        bridge.log_line.connect(lambda level, message: getattr(self.log, level if level in ("info", "warn", "error", "success") else "info")(message))
        bridge.finished.connect(self._on_fix_finished)
        self._bridge = bridge  # 保持引用，避免被回收
        callbacks = RunnerCallbacks(
            on_start=lambda step: bridge.step_started.emit(step),
            on_done=lambda step, result: bridge.step_done.emit(step, result),
            on_log=lambda level, message: bridge.log_line.emit(level, message),
            on_finished=lambda finished_ctx: bridge.finished.emit(finished_ctx),
        )
        runner = RepairRunner(ctx, profile, callbacks)
        self._runner = runner
        runner.start()

    def _on_fix_finished(self, ctx: RepairContext) -> None:
        self.fixing = False
        self._ctx = ctx
        self._runner = None
        report = (ctx.concluded or {}).get("report", "")
        self.last_report = report
        self.fix_page.show_conclusion(ctx, report=report)
        success = bool((ctx.concluded or {}).get("success"))
        if success:
            self.stats["fixes"] += 1
            self.settings.total_fixes = int(getattr(self.settings, "total_fixes", 0) or 0) + 1
            self.settings.save()
            self.log.success("修复成功", f"{ctx.game_name} 已正常启动（报告：{Path(report).name if report else '无'}）")
            self._notify("修复成功", f"{ctx.game_name} 的游戏窗口已正常出现")
            self.current_issue = None
            self.current_game = None
            self._last_issue_sig = ""
        else:
            self.log.warn("修复未完成", "已生成诊断建议，请按结论里的步骤继续排查")
            self._notify("修复未完成", f"{ctx.game_name}：需要人工确认账号授权 / 启动方式")
            self._auto_cooldown_until = time.time() + 120
        self._update_backup_info()
        cause = (ctx.concluded or {}).get("chain_cause", "")
        if not success and ctx.profile == "quick" and cause in ("bf3_license_stale", "ea_portal_timeout_no_license") and not self._escalated:
            self._escalated = True
            from .widgets import ConfirmDialog

            dialog = ConfirmDialog(self)
            if dialog.ask(
                "要不要直接执行深度修复？",
                "已定位到 BF3 授权缓存问题。深度修复会：关闭 EA App → 备份并删除过期的 BF3 授权缓存（71067.dlf 等）→ 清理老下载缓存 → 重启 EA App → 从 Steam 重新启动。",
                "这是社区验证过的修法，所有删除都是移动到备份目录，可还原。",
            ):
                QTimer.singleShot(400, lambda: self._run_fix("deep"))
        self._refresh_slow()
        self._scan_fast(manual=False)

    def _run_deep_fix(self) -> None:
        if self.fixing:
            return
        self.fix_page.profile.set_value("deep")
        self._run_fix("deep")

    def _cancel_fix(self) -> None:
        if self._ctx is not None:
            self._ctx.cancel_event.set()
            self.log.warn("已请求取消", "当前步骤结束后停止")
        self.fix_page.cancel_button.setEnabled(False)

    def _maybe_auto_fix(self) -> None:
        if not self.settings.monitor_enabled or not self.settings.auto_fix:
            return
        issue = self.detection.primary
        if issue is None or not issue.requires_action or self.fixing:
            return
        if time.time() < self._auto_cooldown_until:
            return
        if self.current_issue is None:
            return
        # 置信度不足的疑似窗口不自动动手，避免误关正常窗口
        if issue.confidence < 0.85:
            self.log.info("自动修复已跳过", f"检测置信度不足（{int(issue.confidence * 100)}%），等待手动确认")
            return
        # 游戏自己的窗口已经在跑时不要自动重启它
        running_keys = {
            definition.key
            for window in self.detection.game_windows
            if window.title and (definition := catalog.match_game_text(window.title)) is not None
        }
        if issue.game_key and issue.game_key in running_keys:
            return
        profile = self.settings.auto_fix_profile or "quick"
        self._auto_cooldown_until = time.time() + 90
        self.log.action("自动修复", f"检测到 {issue.game_name} 的{issue.kind_label}，自动执行{actions.PROFILE_LABELS.get(profile, profile)}")
        self._switch_page(2)
        self._run_fix(profile)

    # ------------------------------------------------------------------
    # 启动游戏 / 诊断 / 备份
    # ------------------------------------------------------------------
    def _launch_game(self, game_key: str) -> None:
        game = next((item for item in self.games if item.key == game_key), None)
        if game is None:
            return
        if not game.installed:
            self.log.warn("无法启动", f"{game.name} 的安装目录不完整，请先在平台里修复游戏")
            return
        ok, message = actions.launch_game_now(game, prefer_steam=self.settings.prefer_steam)
        (self.log.success if ok else self.log.error)("启动游戏" if ok else "启动失败", message)
        self._notify("正在启动游戏" if ok else "启动失败", message if not ok else f"{game.name} 已交给{'Steam' if game.steam_appid and self.settings.prefer_steam else '系统'}启动")
        QTimer.singleShot(8000, lambda: self._post_launch_check(game))

    def _post_launch_check(self, game) -> None:
        self._scan_fast(manual=False)
        issues = [issue for issue in self.detection.issues if issue.game_key == game.key]
        windows = [window for window in self.detection.game_windows if window.pid in {proc.pid for proc in self.detection.game_processes}]
        if issues:
            self.log.warn("启动被拦截", f"{game.name} 又出现了{issues[0].kind_label}，可以试试修复中心")
        elif self.detection.game_windows:
            self.log.success("游戏窗口已出现", f"{game.name} 启动正常")
        elif windows:
            self.log.info("游戏正在加载", f"{game.name} 进程已启动，尚未创建窗口")

    def _show_diagnostics(self) -> None:
        try:
            self.diagnosis = diagnostics.run_checks(self.discovery, self.settings)
        except Exception as exc:
            self.log.error("诊断失败", str(exc))
            return
        dialog = DiagnosticsDialog(self)
        dialog.show_diagnosis(self.diagnosis)

    def _update_backup_info(self) -> None:
        backups = list_backups()
        if not backups:
            self.settings_page.set_backup_info(None)
            return
        latest = backups[0]
        try:
            size = sum(f.stat().st_size for f in latest.rglob("*") if f.is_file())
        except OSError:
            size = 0
        self.settings_page.set_backup_info((latest.name, human_size(size)))

    def _show_backups(self) -> None:
        dialog = BackupsDialog(self)
        rows: list[tuple[str, str, int]] = []
        for directory in list_backups()[:20]:
            count = 0
            size = 0
            manifest = directory / "manifest.json"
            if manifest.is_file():
                try:
                    import json

                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    items = payload.get("items") or []
                    count = len(items)
                    size = int(sum(int(item.get("size") or 0) for item in items))
                except Exception:
                    count = 0
            rows.append((directory.name, human_size(size), count))
        dialog.restore_requested.connect(lambda name: self._restore_backup_dir(BACKUPS_DIR / name))
        dialog.open_requested.connect(lambda: open_folder(str(BACKUPS_DIR)))
        dialog.show_backups(rows)

    def _restore_latest(self) -> None:
        backups = list_backups()
        if not backups:
            self.log.warn("没有可还原的备份", "深度修复后会自动生成备份")
            return
        self._restore_backup_dir(backups[0])

    def _restore_backup_dir(self, directory: Path) -> None:
        from .widgets import ConfirmDialog

        dialog = ConfirmDialog(self)
        if not dialog.ask("还原备份？", f"将把备份 {directory.name} 里的授权缓存文件放回原位置。", "还原前会关闭 EA App 以确保文件不被占用。"):
            return
        eaapp.stop_client()
        restored, errors = restore_backup(directory)
        if restored:
            self.log.success("备份已还原", f"恢复了 {restored} 个文件")
        if errors:
            self.log.warn("还原时出现问题", "；".join(errors[:3]))
        self._update_backup_info()
        self._refresh_slow()

    def _open_report(self) -> None:
        report = self.last_report
        if not report:
            report = getattr(self.fix_page.report_button, "property", lambda _: "")("report") or ""
        if report and Path(report).is_file():
            open_folder(str(Path(report).parent))
        else:
            open_folder(str(REPORTS_DIR))

    def _open_help(self) -> None:
        from ..config import EA_SUPPORT_LINK

        if not open_url(EA_SUPPORT_LINK):
            webbrowser.open(EA_SUPPORT_LINK)

    def _export_logs(self) -> None:
        from ..config import write_report

        content = self.logs_page.export_text()
        path = write_report("event-log.txt", {"lines": content})
        text_path = path.with_suffix(".txt")
        try:
            text_path.write_text(content, encoding="utf-8")
        except OSError:
            pass
        self.log.success("日志已导出", str(text_path))
        open_folder(str(text_path.parent))

    def _clear_logs(self) -> None:
        self.log.clear()
        self.logs_page.log_list._events.clear()
        self.logs_page.log_list.clear()
        self.overview_page.log_list._events.clear()
        self.overview_page.log_list.clear()
        self.log.info("日志已清空", "只清空界面显示，磁盘日志文件仍保留")

    # ------------------------------------------------------------------
    # 设置 / 监视
    # ------------------------------------------------------------------
    def _apply_settings_to_ui(self) -> None:
        self.overview_page.set_monitor(self.settings.monitor_enabled)
        self._timer.setInterval(max(600, int(self.settings.interval_ms)))
        self.settings_page.set_admin_state(is_admin())
        self._update_footer()

    def _on_settings_changed(self) -> None:
        self._timer.setInterval(max(600, int(self.settings.interval_ms)))
        self.overview_page.set_monitor(self.settings.monitor_enabled)
        self._update_footer()
        self.log.info("设置已更新", f"监视 {'开' if self.settings.monitor_enabled else '关'} · 间隔 {self.settings.interval_ms} ms")

    def _set_monitor(self, enabled: bool) -> None:
        self.settings.monitor_enabled = bool(enabled)
        self.settings.save()
        self._apply_settings_to_ui()
        self.log.info("监视状态", "已开启" if enabled else "已暂停")
        self._update_footer()

    def _toggle_monitor_from_tray(self, enabled: bool) -> None:
        self._set_monitor(enabled)
        self.monitor_action.setChecked(self.settings.monitor_enabled)

    def _on_tick(self) -> None:
        if self.fixing or not self.settings.monitor_enabled:
            return
        self._scan_fast(manual=False)

    def _elevate(self) -> None:
        from .widgets import ConfirmDialog

        dialog = ConfirmDialog(self)
        if not dialog.ask("以管理员身份重启？", "会以管理员权限启动一个新实例，用于修复 URL 协议注册、重启 EA 后台服务。", "当前窗口会被关闭。"):
            return
        if relaunch_as_admin():
            self.log.info("正在重启", "已请求管理员权限")
            QTimer.singleShot(400, self._quit_app)
        else:
            self.log.warn("提权取消", "用户取消了 UAC 授权")

    # ------------------------------------------------------------------
    # 日志与通知
    # ------------------------------------------------------------------
    def _on_log_event(self, event) -> None:
        self.logs_page.append_log(event)
        self.overview_page.append_log(event)
        self.footer_last.setText(f"{event.time_text} · {event.title}")

    def _notify(self, title: str, message: str) -> None:
        if not self.settings.notify or self._tray is None:
            return
        self._tray.showMessage(title, message, QSystemTrayIcon.Information, 4200)

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self) -> None:
        self._quitting = True
        self.close()

    # ------------------------------------------------------------------
    # 窗口行为
    # ------------------------------------------------------------------
    def _title_press(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _title_move(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if self.isMaximized():
                self.showNormal()
                self._drag_offset = QPoint(self.width() // 2, 20)
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def _title_release(self, event) -> None:
        self._drag_offset = None
        event.accept()

    def _title_double(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.showNormal() if self.isMaximized() else self.showMaximized()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._quitting and self.settings.minimize_to_tray and self._tray is not None:
            event.ignore()
            self.hide()
            self._notify("仍在后台监视", "关闭窗口不会退出，右键托盘图标可以退出")
            return
        self.settings.save()
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)


class _WindowButton(QPushButton):
    """标题栏最小化 / 关闭按钮。"""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(32, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(
            f"""
            QPushButton {{ border: none; border-radius: 8px; background: transparent; }}
            QPushButton:hover {{ background: {'rgba(255,95,110,0.18)' if kind == 'close' else 'rgba(147,165,196,0.14)'}; }}
            """
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(theme.DANGER if self.kind == "close" else theme.TEXT_DIM)
        painter.setPen(QColor(color))
        rect = self.rect()
        cx, cy = rect.center().x() + 0.5, rect.center().y() + 0.5
        if self.kind == "close":
            painter.drawLine(QPoint(int(cx - 5), int(cy - 5)), QPoint(int(cx + 5), int(cy + 5)))
            painter.drawLine(QPoint(int(cx + 5), int(cy - 5)), QPoint(int(cx - 5), int(cy + 5)))
        else:
            painter.drawLine(QPoint(int(cx - 5), int(cy + 4)), QPoint(int(cx + 5), int(cy + 4)))
        painter.end()


class _Separator(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(1, 14)
        self.setStyleSheet(f"background: {theme.BORDER};")
