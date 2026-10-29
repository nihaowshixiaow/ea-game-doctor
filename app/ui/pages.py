"""五个页面：概览 / 游戏库 / 修复中心 / 事件日志 / 设置。"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import catalog, detect, diagnostics
from ..actions import PROFILE_LABELS, RISK_LABELS, RepairContext
from ..config import APP_NAME_CN, APP_VERSION, EA_SUPPORT_LINK, EventLog, Settings, human_size
from . import theme
from .widgets import (
    Card,
    ConfirmDialog,
    EmptyState,
    GameCard,
    HeroCard,
    IconWidget,
    InfoRow,
    LogList,
    Pill,
    PulseDot,
    SearchBox,
    SectionHeader,
    SegmentedControl,
    StatTile,
    StepRow,
    ToggleSwitch,
    elide,
    hline,
    label,
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def game_state(game, detection: detect.Detection | None) -> tuple[str, str]:
    if detection is not None:
        for issue in detection.issues:
            if issue.game_key and issue.game_key == game.key:
                return "warn", "激活异常"
        if game.key in detection.running_keys:
            return "ok", "运行中"
    if not game.installed:
        return "muted", "未安装"
    if not game.exe and not game.steam_appid:
        return "error", "需修复"
    if game.extras:
        return "warn", "第三方组件"
    return "ok", "就绪"


def _bullets(lines: list[str], color: str = theme.TEXT_DIM) -> str:
    items = "".join(
        f'<div style="margin: 3px 0;"><span style="color:{theme.ACCENT_SOFT};">•</span> '
        f'<span style="color:{color};">{line}</span></div>'
        for line in lines
    )
    return f'<div style="font-size:12px; line-height:150%;">{items}</div>'


def _short_path(path: str | None) -> str:
    if not path:
        return "未定位"
    try:
        parts = Path(path).parts
    except Exception:
        return path
    if len(parts) <= 2:
        return str(Path(path))
    return "…\\" + "\\".join(parts[-2:])


def _stat_block(title: str) -> tuple[QWidget, QLabel]:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    value = label("—", "h2")
    caption = label(title, "small")
    layout.addWidget(value)
    layout.addWidget(caption)
    return wrapper, value


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------
class OverviewPage(QWidget):
    scan_requested = Signal()
    fix_requested = Signal()
    open_logs_requested = Signal()
    open_diagnostics_requested = Signal()
    monitor_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(SectionHeader("概览", "检测激活弹窗 → 识别游戏 → 修复启动链 → 验证游戏窗口"))
        header.addStretch(1)
        header.addWidget(label("自动监视", "small"))
        self.monitor_toggle = ToggleSwitch()
        self.monitor_toggle.toggled.connect(self.monitor_toggled.emit)
        header.addWidget(self.monitor_toggle)
        self.scan_button = QPushButton("立即扫描")
        self.scan_button.setProperty("btn", "ghost")
        self.scan_button.setCursor(Qt.PointingHandCursor)
        self.scan_button.clicked.connect(self.scan_requested.emit)
        header.addWidget(self.scan_button)
        root.addLayout(header)
        self.env_note = ""

        # Hero
        self.hero = HeroCard()
        left = QVBoxLayout()
        left.setSpacing(10)
        status_row = QHBoxLayout()
        status_row.setSpacing(14)
        self.pulse = PulseDot(theme.SUCCESS, 13)
        status_row.addWidget(self.pulse, 0, Qt.AlignVCenter)
        status_text = QVBoxLayout()
        status_text.setSpacing(4)
        self.status_title = label("守护已就绪", "h2")
        self.status_sub = label("正在监视 EA 相关窗口，一旦出现激活弹窗会立刻提示。", "body")
        self.status_sub.setWordWrap(True)
        status_text.addWidget(self.status_title)
        status_text.addWidget(self.status_sub)
        status_row.addLayout(status_text, 1)
        left.addLayout(status_row)
        self.evidence_label = label("", "small")
        self.evidence_label.setWordWrap(True)
        left.addWidget(self.evidence_label)
        left.addStretch(1)
        self.hero.body.addLayout(left, 1)

        right = QHBoxLayout()
        right.setSpacing(22)
        self.ea_block, self.ea_value = _stat_block("EA App")
        self.license_block, self.license_value = _stat_block("授权缓存")
        self.library_block, self.library_value = _stat_block("游戏库")
        for block in (self.ea_block, self.license_block, self.library_block):
            right.addWidget(block)
        self.fix_button = QPushButton("立即修复")
        self.fix_button.setProperty("btn", "primary")
        self.fix_button.setCursor(Qt.PointingHandCursor)
        self.fix_button.clicked.connect(self.fix_requested.emit)
        right.addWidget(self.fix_button, 0, Qt.AlignVCenter)
        self.hero.body.addLayout(right)
        root.addWidget(self.hero)

        # 统计
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.tile_games = StatTile("已安装游戏", "0", theme.ACCENT)
        self.tile_scans = StatTile("本次扫描", "0", theme.SUCCESS)
        self.tile_issues = StatTile("发现异常", "0", theme.WARN)
        self.tile_fixes = StatTile("累计修复", "0", theme.INFO)
        for tile in (self.tile_games, self.tile_scans, self.tile_issues, self.tile_fixes):
            stats.addWidget(tile, 1)
        root.addLayout(stats)

        # 主体
        body = QHBoxLayout()
        body.setSpacing(14)
        events_card = Card(margins=18, spacing=10)
        events_header = QHBoxLayout()
        events_header.addWidget(label("实时事件", "h3"))
        events_header.addStretch(1)
        logs_button = QPushButton("查看全部")
        logs_button.setProperty("btn", "mini")
        logs_button.setCursor(Qt.PointingHandCursor)
        logs_button.clicked.connect(self.open_logs_requested.emit)
        events_header.addWidget(logs_button)
        events_card.body.addLayout(events_header)
        self.log_list = LogList()
        self.log_list.setMinimumHeight(228)
        events_card.body.addWidget(self.log_list, 1)
        body.addWidget(events_card, 3)

        side = QVBoxLayout()
        side.setSpacing(14)
        self.issue_card = Card(margins=18, spacing=10)
        issue_header = QHBoxLayout()
        issue_header.addWidget(label("当前问题", "h3"))
        issue_header.addStretch(1)
        self.issue_pill = Pill("正常", "ok")
        issue_header.addWidget(self.issue_pill)
        self.issue_card.body.addLayout(issue_header)
        self.issue_box = QVBoxLayout()
        self.issue_box.setSpacing(8)
        self.issue_card.body.addLayout(self.issue_box)
        side.addWidget(self.issue_card)

        quick_card = Card(margins=18, spacing=10)
        quick_card.body.addWidget(label("快速操作", "h3"))
        grid = QGridLayout()
        grid.setSpacing(8)
        for index, (text, signal) in enumerate(
            (
                ("系统诊断", self.open_diagnostics_requested.emit),
                ("打开日志", self.open_logs_requested.emit),
                ("修复中心", self.fix_requested.emit),
                ("重新扫描", self.scan_requested.emit),
            )
        ):
            button = QPushButton(text)
            button.setProperty("btn", "ghost")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(signal)
            grid.addWidget(button, index // 2, index % 2)
        quick_card.body.addLayout(grid)
        side.addWidget(quick_card)
        side.addStretch(1)
        body.addLayout(side, 2)
        root.addLayout(body, 1)

    # -- 更新 ---------------------------------------------------------------
    def set_environment_note(self, text: str) -> None:
        self.env_note = text

    def set_monitor(self, enabled: bool) -> None:
        self.monitor_toggle.blockSignals(True)
        self.monitor_toggle.setChecked(enabled)
        self.monitor_toggle.blockSignals(False)

    def append_log(self, event) -> None:
        self.log_list.add_event(event)

    def update_view(
        self,
        detection: detect.Detection,
        diagnosis: diagnostics.Diagnosis | None,
        games,
        stats: dict,
        settings: Settings,
        ea_info,
        steam_running: bool,
    ) -> None:
        installed = [g for g in games if g.installed]
        issues = [issue for issue in detection.issues if issue.requires_action]
        self.set_monitor(settings.monitor_enabled)

        if issues:
            primary = issues[0]
            self.pulse.set_color(theme.WARN)
            self.hero.set_accent(theme.WARN)
            self.status_title.setText("发现激活异常")
            self.status_sub.setText(f"{primary.game_name} · {primary.kind_label}，已准备修复方案")
            evidence = "；".join(primary.evidence[:2])
            self.evidence_label.setText(evidence)
            self.fix_button.setEnabled(True)
            self.issue_pill.set_kind("warn", f"{len(issues)} 个问题")
        elif detection.game_windows:
            self.pulse.set_color(theme.SUCCESS)
            self.hero.set_accent(theme.SUCCESS)
            titles = "、".join({w.title for w in detection.game_windows if w.title})[:60]
            self.status_title.setText("游戏正在运行")
            self.status_sub.setText(f"检测到游戏窗口：{titles}" + (f"　{self.env_note}" if self.env_note else ""))
            self.evidence_label.setText("")
            self.fix_button.setEnabled(True)
            self.issue_pill.set_kind("ok", "正常")
        else:
            self.pulse.set_color(theme.SUCCESS if settings.monitor_enabled else theme.TEXT_MUTED)
            self.hero.set_accent(theme.SUCCESS if settings.monitor_enabled else theme.TEXT_MUTED)
            self.status_title.setText("守护已就绪" if settings.monitor_enabled else "监视已暂停")
            self.status_sub.setText(
                (
                    "正在监视 EA 相关窗口，一旦出现激活弹窗会立刻提示。"
                    if settings.monitor_enabled
                    else "监视已关闭，仍可以手动扫描或直接启动游戏。"
                )
                + (f"　{self.env_note}" if self.env_note else "")
            )
            self.evidence_label.setText("")
            self.fix_button.setEnabled(True)
            self.issue_pill.set_kind("ok", "正常")

        self.ea_value.setText("运行中" if ea_info.running else "未运行")
        self.ea_value.setStyleSheet(f"color: {theme.SUCCESS if ea_info.running else theme.WARN};")
        self.license_value.setText(f"{stats.get('license_count', 0)} 条")
        self.library_value.setText(f"{len(installed)} 款")
        self.tile_games.set_value(str(len(installed)))
        self.tile_scans.set_value(str(stats.get("scans", 0)))
        self.tile_issues.set_value(str(stats.get("issues", 0)))
        self.tile_fixes.set_value(str(stats.get("fixes", 0)))

        # 当前问题卡
        while self.issue_box.count():
            item = self.issue_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if issues:
            primary = issues[0]
            row = QHBoxLayout()
            row.setSpacing(10)
            from .widgets import GameCover

            game = next((g for g in games if primary.game_key and g.key == primary.game_key), None)
            if game is not None:
                row.addWidget(GameCover(game.initials, game.accent, 42))
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(label(primary.game_name, "h3"))
            hint = label(primary.kind_label + " · 置信度 " + str(int(primary.confidence * 100)) + "%", "small")
            text.addWidget(hint)
            row.addLayout(text, 1)
            self.issue_box.addLayout(row)
            if primary.evidence:
                line = label("· " + elide(primary.evidence[0], 34), "small")
                line.setToolTip("\n".join(primary.evidence))
                self.issue_box.addWidget(line)
            open_button = QPushButton("查看修复方案")
            open_button.setProperty("btn", "ghost")
            open_button.setCursor(Qt.PointingHandCursor)
            open_button.clicked.connect(self.fix_requested.emit)
            self.issue_box.addWidget(open_button)
        else:
            self.issue_box.addWidget(
                EmptyState("shield", "没有检测到激活弹窗", "出现弹窗后会立刻显示在这里")
            )
        if diagnosis is not None:
            self.tile_scans.setToolTip(diagnostics.summary_text(diagnosis))


# ---------------------------------------------------------------------------
# 游戏库
# ---------------------------------------------------------------------------
class GamesPage(QWidget):
    launch_requested = Signal(str)
    fix_requested = Signal(str)
    diagnose_requested = Signal(str)
    refresh_requested = Signal()

    FILTERS = (
        ("all", "全部"),
        ("installed", "已安装"),
        ("steam", "Steam"),
        ("ea", "EA App"),
        ("issue", "异常"),
        ("notinstalled", "未安装"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._games: list = []
        self._detection: detect.Detection | None = None
        self._filter = "all"
        self._search = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(SectionHeader("游戏库", "自动识别注册表与 Steam 清单里的 EA 游戏"))
        header.addStretch(1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setProperty("btn", "ghost")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = SearchBox("搜索游戏名称 / 目录")
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self._on_search)
        toolbar.addWidget(self.search)
        self.chips: dict[str, QPushButton] = {}
        for value, text in self.FILTERS:
            chip = QPushButton(text)
            chip.setProperty("chip", "true")
            chip.setCheckable(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setChecked(value == "all")
            chip.clicked.connect(lambda _=False, v=value: self._set_filter(v))
            self.chips[value] = chip
            toolbar.addWidget(chip)
        toolbar.addStretch(1)
        self.count_label = label("", "small")
        toolbar.addWidget(self.count_label)
        root.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.grid = QGridLayout(container)
        self.grid.setContentsMargins(0, 0, 6, 4)
        self.grid.setSpacing(12)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.scroll.setWidget(container)
        root.addWidget(self.scroll, 1)
        self._empty = EmptyState("games", "没有匹配的游戏", "试试切换筛选条件，或点击右上角刷新。")
        root.addWidget(self._empty)
        self._empty.setVisible(False)

    # -- 过滤 ---------------------------------------------------------------
    def _on_search(self, text: str) -> None:
        self._search = text.strip().lower()
        self._rebuild()

    def _set_filter(self, value: str) -> None:
        self._filter = value
        for key, chip in self.chips.items():
            chip.setChecked(key == value)
        self._rebuild()

    def _matches(self, game) -> bool:
        issue_keys = {issue.game_key for issue in (self._detection.issues if self._detection else []) if issue.game_key}
        if self._filter == "all" and not (game.installed or game.install_dir):
            return False
        if self._filter == "notinstalled" and game.installed:
            return False
        if self._filter == "installed" and not game.installed:
            return False
        if self._filter == "steam" and game.platform != "steam":
            return False
        if self._filter == "ea" and game.platform != "ea":
            return False
        if self._filter == "issue" and game.key not in issue_keys:
            return False
        if self._search:
            haystack = f"{game.name} {game.name_cn} {game.install_dir or ''}".lower()
            return self._search in haystack
        return True

    # -- 数据 ---------------------------------------------------------------
    def populate(self, games, detection: detect.Detection | None) -> None:
        self._games = games
        self._detection = detection
        self._rebuild()

    def _rebuild(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        visible = [game for game in self._games if self._matches(game)]
        installed = [game for game in self._games if game.installed]
        self.count_label.setText(f"显示 {len(visible)} 款 · 已安装 {len(installed)} 款")
        for index, game in enumerate(visible):
            card = GameCard(game, game_state(game, self._detection))
            card.launch_clicked.connect(self.launch_requested.emit)
            card.fix_clicked.connect(self.fix_requested.emit)
            card.diagnose_clicked.connect(self.diagnose_requested.emit)
            self.grid.addWidget(card, index // 2, index % 2)
        # 底部留白，避免卡片贴边
        self.grid.setRowStretch(len(visible) // 2 + 1, 1)
        self._empty.setVisible(not visible)
        self.scroll.setVisible(bool(visible))


# ---------------------------------------------------------------------------
# 修复中心
# ---------------------------------------------------------------------------
class FixPage(QWidget):
    run_requested = Signal(str)
    cancel_requested = Signal()
    rescan_requested = Signal()
    open_report_requested = Signal()
    restore_requested = Signal()
    open_help_requested = Signal()
    deep_fix_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._step_rows: dict[str, StepRow] = {}
        self._result = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(SectionHeader("修复中心", "每一步都可回退；不会做任何授权绕过"))
        header.addStretch(1)
        self.profile = SegmentedControl([("quick", "快速修复"), ("deep", "深度修复")])
        self.profile.changed.connect(lambda _value: self.show_plan())
        header.addWidget(self.profile)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setProperty("btn", "ghost")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        header.addWidget(self.cancel_button)
        self.run_button = QPushButton("开始修复")
        self.run_button.setProperty("btn", "primary")
        self.run_button.setCursor(Qt.PointingHandCursor)
        self.run_button.clicked.connect(lambda: self.run_requested.emit(self.profile.value()))
        header.addWidget(self.run_button)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)

        # 左：当前问题
        self.issue_card = Card(margins=18, spacing=10)
        self.issue_card.setMinimumWidth(370)
        self.issue_card.setMaximumWidth(410)
        self.issue_card.body.addWidget(label("当前问题", "h3"))
        self.issue_scroll = QScrollArea()
        self.issue_scroll.setWidgetResizable(True)
        self.issue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        issue_content = QWidget()
        self.issue_host = QVBoxLayout(issue_content)
        self.issue_host.setContentsMargins(0, 0, 4, 2)
        self.issue_host.setSpacing(8)
        self.issue_scroll.setWidget(issue_content)
        self.issue_card.body.addWidget(self.issue_scroll, 1)
        rescan = QPushButton("重新扫描")
        rescan.setProperty("btn", "ghost")
        rescan.setCursor(Qt.PointingHandCursor)
        rescan.clicked.connect(self.rescan_requested.emit)
        self.issue_card.body.addWidget(rescan)
        body.addWidget(self.issue_card, 0)

        # 右：修复方案
        plan_card = Card(margins=18, spacing=12)
        plan_header = QHBoxLayout()
        plan_header.addWidget(label("修复方案", "h3"))
        plan_header.addStretch(1)
        self.plan_pill = Pill("等待开始", "muted")
        plan_header.addWidget(self.plan_pill)
        plan_card.body.addLayout(plan_header)
        self.steps_host = QVBoxLayout()
        self.steps_host.setSpacing(7)
        self.steps_host.setContentsMargins(0, 0, 0, 0)
        steps_wrapper = QWidget()
        steps_wrapper.setLayout(self.steps_host)
        self.steps_scroll = QScrollArea()
        self.steps_scroll.setWidgetResizable(True)
        self.steps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.steps_scroll.setWidget(steps_wrapper)
        plan_card.body.addWidget(self.steps_scroll, 1)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        progress_row.addWidget(self.progress, 1)
        self.status_label = label("准备就绪", "small")
        self.status_label.setMinimumWidth(180)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_row.addWidget(self.status_label)
        plan_card.body.addLayout(progress_row)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.report_button = QPushButton("打开报告")
        self.report_button.setProperty("btn", "ghost")
        self.report_button.setEnabled(False)
        self.report_button.setCursor(Qt.PointingHandCursor)
        self.report_button.clicked.connect(self.open_report_requested.emit)
        footer.addWidget(self.report_button)
        self.restore_button = QPushButton("还原备份")
        self.restore_button.setProperty("btn", "ghost")
        self.restore_button.setEnabled(False)
        self.restore_button.setCursor(Qt.PointingHandCursor)
        self.restore_button.clicked.connect(self.restore_requested.emit)
        footer.addWidget(self.restore_button)
        footer.addStretch(1)
        body.addWidget(plan_card, 1)
        root.addLayout(body, 1)

        # 结论
        self.conclusion_card = Card(margins=18, spacing=8)
        conclusion_header = QHBoxLayout()
        self.conclusion_title = label("修复结论", "h3")
        conclusion_header.addWidget(self.conclusion_title)
        conclusion_header.addStretch(1)
        self.conclusion_pill = Pill("", "muted")
        self.conclusion_pill.setVisible(False)
        conclusion_header.addWidget(self.conclusion_pill)
        self.conclusion_card.body.addLayout(conclusion_header)
        self.conclusion_text = label("", "body")
        self.conclusion_text.setTextFormat(Qt.RichText)
        self.conclusion_text.setWordWrap(True)
        self.conclusion_card.body.addWidget(self.conclusion_text)
        self.chain_title = label("链路分析（Steam → EA）", "body")
        self.chain_title.setVisible(False)
        self.conclusion_card.body.addWidget(self.chain_title)
        self.chain_text = label("", "small")
        self.chain_text.setWordWrap(True)
        self.chain_text.setVisible(False)
        self.conclusion_card.body.addWidget(self.chain_text)
        links = QHBoxLayout()
        links.setSpacing(8)
        self.report_path_label = label("", "small")
        self.report_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        links.addWidget(self.report_path_label, 1)
        self.deep_button = QPushButton("运行深度修复")
        self.deep_button.setProperty("btn", "mini")
        self.deep_button.setCursor(Qt.PointingHandCursor)
        self.deep_button.setVisible(False)
        self.deep_button.clicked.connect(self.deep_fix_requested.emit)
        links.addWidget(self.deep_button)
        help_button = QPushButton("EA 账号绑定帮助")
        help_button.setProperty("btn", "mini")
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(self.open_help_requested.emit)
        links.addWidget(help_button)
        self.conclusion_card.body.addLayout(links)
        self.conclusion_card.setVisible(False)
        root.addWidget(self.conclusion_card)

        self.show_plan()

    # -- 问题卡 -------------------------------------------------------------
    def set_issue(self, game, issue, detection: detect.Detection | None) -> None:
        self._clear_layout(self.issue_host)
        if issue is None:
            self.issue_host.addWidget(
                EmptyState("shield", "暂未检测到激活弹窗", "启动游戏后出现弹窗会自动识别")
            )
            self.run_button.setEnabled(False)
            self.plan_pill.set_kind("muted", "等待开始")
            return
        self.run_button.setEnabled(True)
        top = QHBoxLayout()
        top.setSpacing(12)
        if game is not None:
            from .widgets import GameCover

            top.addWidget(GameCover(game.initials, game.accent, 46))
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label(issue.game_name, "h3"))
        text.addWidget(label(issue.kind_label, "small"))
        top.addLayout(text, 1)
        confidence = Pill(f"{int(issue.confidence * 100)}%", "warn" if issue.confidence >= 0.8 else "info")
        confidence.setToolTip("检测置信度")
        top.addWidget(confidence, 0, Qt.AlignTop)
        self.issue_host.addLayout(top)

        info = QWidget()
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        rows = [
            ("窗口标题", issue.title or "（无窗口，进程级检测）"),
            ("进程", issue.proc_name or "未知"),
            ("窗口句柄", f"0x{issue.hwnd:08X}" if issue.hwnd else "—"),
            ("游戏目录", _short_path(game.install_dir) if game else "未定位"),
        ]
        for title, value in rows:
            row = QHBoxLayout()
            row.setSpacing(8)
            key_label = label(title, "small")
            key_label.setFixedWidth(64)
            row.addWidget(key_label)
            value_label = label(elide(str(value), 42), "small")
            value_label.setStyleSheet(f"color: {theme.TEXT};")
            value_label.setToolTip(str(value))
            row.addWidget(value_label, 1)
            info_layout.addLayout(row)
        self.issue_host.addWidget(info)
        self.issue_host.addWidget(hline())
        self.issue_host.addWidget(label("证据链", "body"))
        for line in issue.evidence[:3]:
            item = label("· " + elide(line, 42), "small")
            item.setToolTip(line)
            self.issue_host.addWidget(item)
        self.issue_host.addStretch(1)
        self.issue_host.addWidget(hline())
        tip_title = label("小贴士", "body")
        self.issue_host.addWidget(tip_title)
        for tip in self._tips_for(game, issue):
            tip_label = label("· " + tip, "small")
            tip_label.setWordWrap(True)
            self.issue_host.addWidget(tip_label)
        self.issue_host.addStretch(1)

    @staticmethod
    def _tips_for(game, issue) -> list[str]:
        tips: list[str] = []
        if game is not None and game.platform == "steam" and game.steam_appid:
            tips.append(f"Steam 版必须由 Steam 启动（AppID {game.steam_appid}），直接双击 exe 会拿不到平台票据。")
        tips.append("EA App 需要在后台运行并完成登录，且登录账号必须拥有该游戏。")
        return tips

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child is not None:
                FixPage._clear_layout(child)

    # -- 方案 ---------------------------------------------------------------
    def show_plan(self) -> None:
        from ..actions import plan_payload

        self._clear_layout(self.steps_host)
        self._step_rows.clear()
        for index, step in enumerate(plan_payload(self.profile.value()), start=1):
            row = StepRow(index, step["title"], step["detail"], step["risk_label"])
            self._step_rows[step["id"]] = row
            self.steps_host.addWidget(row)
        self.steps_host.addStretch(1)
        self.progress.setValue(0)
        self.status_label.setText("准备就绪" if self.run_button.isEnabled() else "等待检测到问题")
        self.plan_pill.set_kind("muted", "等待开始")

    def set_busy(self, busy: bool) -> None:
        self.run_button.setEnabled(not busy and self._step_rows != {})
        self.run_button.setText("修复中…" if busy else "开始修复")
        self.cancel_button.setEnabled(busy)
        self.profile.setEnabled(not busy)
        if busy:
            self.report_button.setEnabled(False)
            self.restore_button.setEnabled(False)
            self.conclusion_card.setVisible(False)
            for row in self._step_rows.values():
                row.set_status("pending")
            self.progress.setValue(0)
            self.plan_pill.set_kind("accent", "执行中")
            self.status_label.setText("开始执行…")

    def on_step_started(self, step) -> None:
        row = self._step_rows.get(step.id)
        if row is not None:
            row.set_status("running")
        total = max(1, len(self._step_rows))
        done = sum(1 for item in self._step_rows.values() if item.icon._status in ("ok", "warn", "fail", "skip", "simulated"))
        self.progress.setValue(int(done / total * 100))
        self.status_label.setText(f"正在执行：{step.title}")

    def on_step_done(self, step, result) -> None:
        row = self._step_rows.get(step.id)
        if row is not None:
            row.set_status(result.status)
            row.set_message(result.message)
        total = max(1, len(self._step_rows))
        done = sum(1 for item in self._step_rows.values() if item.icon._status in ("ok", "warn", "fail", "skip", "simulated"))
        self.progress.setValue(int(done / total * 100))
        self.status_label.setText(f"{step.title}：{result.message[:40]}")

    def show_conclusion(self, ctx: RepairContext, report: str = "") -> None:
        self.set_busy(False)
        success = bool(ctx.concluded.get("success"))
        lines = list(ctx.concluded.get("analysis") or [])
        self.conclusion_title.setText("修复结论")
        self.conclusion_pill.set_kind("ok" if success else "warn", "已修复" if success else "需要人工处理")
        self.conclusion_pill.setVisible(True)
        self.conclusion_text.setText(_bullets(lines))
        chain_lines = list(ctx.concluded.get("chain_lines") or [])
        if chain_lines:
            self.chain_title.setVisible(True)
            self.chain_text.setVisible(True)
            self.chain_text.setText("\n".join("· " + line for line in chain_lines))
        else:
            self.chain_title.setVisible(False)
            self.chain_text.setVisible(False)
        self.deep_button.setVisible(not success)
        self.report_path_label.setText(f"报告：{report}" if report else "")
        self.conclusion_card.setVisible(True)
        self.report_button.setEnabled(bool(report))
        self.report_button.setProperty("report", report)
        self.progress.setValue(100 if success else self.progress.value())
        self.plan_pill.set_kind("ok" if success else "warn", "完成" if success else "部分完成")
        self.status_label.setText("修复完成" if success else "已停止，等待人工处理")
        root = ctx.backup
        self.restore_button.setEnabled(bool(root and root.exists))

    def reset(self) -> None:
        self._result = None
        self.set_busy(False)
        self.conclusion_card.setVisible(False)
        self.chain_title.setVisible(False)
        self.chain_text.setVisible(False)
        self.deep_button.setVisible(False)
        self.report_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        self.progress.setValue(0)
        self.plan_pill.set_kind("muted", "等待开始")
        self.status_label.setText("准备就绪")
        self.show_plan()


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
class LogsPage(QWidget):
    export_requested = Signal()
    clear_requested = Signal()

    FILTERS = (("", "全部"), ("success", "成功"), ("info", "信息"), ("warn", "警告"), ("error", "错误"), ("action", "操作"))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(SectionHeader("事件日志", "检测、修复、启动的完整时间线，可导出排查"))
        header.addStretch(1)
        self.export_button = QPushButton("导出日志")
        self.export_button.setProperty("btn", "ghost")
        self.export_button.setCursor(Qt.PointingHandCursor)
        self.export_button.clicked.connect(self.export_requested.emit)
        header.addWidget(self.export_button)
        clear_button = QPushButton("清空")
        clear_button.setProperty("btn", "ghost")
        clear_button.setCursor(Qt.PointingHandCursor)
        clear_button.clicked.connect(self.clear_requested.emit)
        header.addWidget(clear_button)
        root.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._chips: dict[str, QPushButton] = {}
        for value, text in self.FILTERS:
            chip = QPushButton(text)
            chip.setProperty("chip", "true")
            chip.setCheckable(True)
            chip.setChecked(value == "")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, v=value: self._set_filter(v))
            self._chips[value] = chip
            toolbar.addWidget(chip)
        toolbar.addStretch(1)
        self.search = SearchBox("搜索日志内容")
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search)
        root.addLayout(toolbar)

        card = Card(margins=10, spacing=0)
        self.log_list = LogList()
        card.body.addWidget(self.log_list)
        root.addWidget(card, 1)
        self._filter = ""

    def _set_filter(self, value: str) -> None:
        self._filter = value
        for key, chip in self._chips.items():
            chip.setChecked(key == value)
        self._apply_filter()

    def _apply_filter(self) -> None:
        self.log_list.set_filter(self._filter, self.search.text())

    def append_log(self, event) -> None:
        self.log_list.add_event(event)

    def export_text(self) -> str:
        return "\n".join(
            f"[{event.time_text}] {event.level.upper():8} {event.title} {event.message}"
            for event in self.log_list._events
        )


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------
class SettingsPage(QWidget):
    settings_changed = Signal()
    elevate_requested = Signal()
    open_backups_requested = Signal()
    restore_latest_requested = Signal()
    open_logs_requested = Signal()
    open_data_requested = Signal()
    open_help_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(SectionHeader("设置", "监视节奏、自动修复策略与数据目录"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 8)
        layout.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # 监视与自动修复
        monitor_card = Card(margins=18, spacing=12)
        monitor_card.body.addWidget(label("监视与自动修复", "h3"))
        self.monitor_toggle = ToggleSwitch()
        self.monitor_toggle.toggled.connect(self._on_monitor)
        monitor_card.body.addWidget(
            InfoRow("自动监视", "每 1~5 秒扫描一次 EA 窗口，发现激活弹窗立即提示", self.monitor_toggle)
        )
        interval_row = QWidget()
        interval_layout = QHBoxLayout(interval_row)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.setSpacing(10)
        self.interval_slider = QSlider(Qt.Horizontal)
        self.interval_slider.setRange(1000, 5000)
        self.interval_slider.setSingleStep(200)
        self.interval_slider.setFixedWidth(180)
        self.interval_label = label("1.8 秒", "small")
        self.interval_slider.valueChanged.connect(self._on_interval)
        interval_layout.addWidget(self.interval_slider)
        interval_layout.addWidget(self.interval_label)
        monitor_card.body.addWidget(InfoRow("扫描间隔", "更短的间隔更灵敏，但会多一点 CPU 占用", interval_row))

        self.autofix_toggle = ToggleSwitch()
        self.autofix_toggle.toggled.connect(self._on_autofix)
        monitor_card.body.addWidget(
            InfoRow("自动修复", "检测到弹窗后自动执行「快速修复」：关弹窗 + 按平台重新启动", self.autofix_toggle)
        )
        self.profile_combo = QComboBox()
        for value, text in PROFILE_LABELS.items():
            self.profile_combo.addItem(text, value)
        self.profile_combo.currentIndexChanged.connect(self._on_profile)
        monitor_card.body.addWidget(InfoRow("自动修复方案", "深度修复会重启 EA App 并刷新授权缓存", self.profile_combo))

        timeout_row = QWidget()
        timeout_layout = QHBoxLayout(timeout_row)
        timeout_layout.setContentsMargins(0, 0, 0, 0)
        timeout_layout.setSpacing(10)
        self.timeout_slider = QSlider(Qt.Horizontal)
        self.timeout_slider.setRange(20, 180)
        self.timeout_slider.setFixedWidth(180)
        self.timeout_label = label("75 秒", "small")
        self.timeout_slider.valueChanged.connect(self._on_timeout)
        timeout_layout.addWidget(self.timeout_slider)
        timeout_layout.addWidget(self.timeout_label)
        monitor_card.body.addWidget(InfoRow("启动验证时长", "启动游戏后等待窗口出现的最长时间", timeout_row))

        self.confirm_toggle = ToggleSwitch()
        self.confirm_toggle.toggled.connect(self._on_confirm)
        monitor_card.body.addWidget(
            InfoRow("深度修复前确认", "清理授权缓存、结束进程前弹出确认框", self.confirm_toggle)
        )
        layout.addWidget(monitor_card)

        # 启动与通知
        launch_card = Card(margins=18, spacing=12)
        launch_card.body.addWidget(label("启动与通知", "h3"))
        self.steam_toggle = ToggleSwitch()
        self.steam_toggle.toggled.connect(self._on_steam)
        launch_card.body.addWidget(
            InfoRow("Steam 版优先走 Steam", "Steam 版 EA 游戏必须由 Steam 拉起才能带上平台票据", self.steam_toggle)
        )
        self.notify_toggle = ToggleSwitch()
        self.notify_toggle.toggled.connect(self._on_notify)
        launch_card.body.addWidget(InfoRow("系统通知", "检测到问题 / 修复完成时弹出通知", self.notify_toggle))
        self.tray_toggle = ToggleSwitch()
        self.tray_toggle.toggled.connect(self._on_tray)
        launch_card.body.addWidget(InfoRow("关闭时最小化到托盘", "监视继续在后台运行", self.tray_toggle))
        layout.addWidget(launch_card)

        # 备份与数据
        data_card = Card(margins=18, spacing=12)
        data_card.body.addWidget(label("备份与数据", "h3"))
        self.backup_label = label("暂无备份", "small")
        data_card.body.addWidget(InfoRow("授权缓存备份", "深度修复会先把 .dlf 文件备份到这里，可一键还原", self.backup_label))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        open_backups = QPushButton("打开备份目录")
        open_backups.setProperty("btn", "ghost")
        open_backups.setCursor(Qt.PointingHandCursor)
        open_backups.clicked.connect(self.open_backups_requested.emit)
        buttons.addWidget(open_backups)
        restore = QPushButton("还原最近一次备份")
        restore.setProperty("btn", "ghost")
        restore.setCursor(Qt.PointingHandCursor)
        restore.clicked.connect(self.restore_latest_requested.emit)
        buttons.addWidget(restore)
        open_logs = QPushButton("打开日志文件")
        open_logs.setProperty("btn", "ghost")
        open_logs.setCursor(Qt.PointingHandCursor)
        open_logs.clicked.connect(self.open_logs_requested.emit)
        buttons.addWidget(open_logs)
        open_data = QPushButton("打开数据目录")
        open_data.setProperty("btn", "ghost")
        open_data.setCursor(Qt.PointingHandCursor)
        open_data.clicked.connect(self.open_data_requested.emit)
        buttons.addWidget(open_data)
        buttons.addStretch(1)
        data_card.body.addLayout(buttons)
        layout.addWidget(data_card)

        # 权限与关于
        about_card = Card(margins=18, spacing=12)
        about_card.body.addWidget(label("权限与关于", "h3"))
        self.admin_label = label("", "small")
        self.elevate_button = QPushButton("以管理员身份重启")
        self.elevate_button.setProperty("btn", "ghost")
        self.elevate_button.setCursor(Qt.PointingHandCursor)
        self.elevate_button.clicked.connect(self.elevate_requested.emit)
        about_card.body.addWidget(InfoRow("当前权限", "管理员权限可修复 URL 协议注册、重启 EA 后台服务", self.admin_label))
        admin_row = QWidget()
        admin_layout = QHBoxLayout(admin_row)
        admin_layout.setContentsMargins(0, 0, 0, 0)
        admin_layout.addWidget(self.elevate_button)
        admin_layout.addStretch(1)
        about_card.body.addWidget(admin_row)
        about_card.body.addWidget(hline())
        about_card.body.addWidget(
            InfoRow(
                f"{APP_NAME_CN} v{APP_VERSION}",
                "只做启动链修复：关闭弹窗、修复协议、刷新授权缓存、按正确平台启动、验证窗口。不会绕过游戏授权，也不会伪造产品密钥。",
            )
        )
        link_row = QHBoxLayout()
        help_button = QPushButton("EA 账号绑定帮助")
        help_button.setProperty("btn", "ghost")
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(self.open_help_requested.emit)
        link_row.addWidget(help_button)
        link_row.addStretch(1)
        about_card.body.addLayout(link_row)
        layout.addWidget(about_card)
        layout.addStretch(1)
        self.bind(settings)

    # -- 绑定 ---------------------------------------------------------------
    def bind(self, settings: Settings) -> None:
        self.settings = settings
        widgets = (
            (self.monitor_toggle, settings.monitor_enabled),
            (self.autofix_toggle, settings.auto_fix),
            (self.confirm_toggle, settings.confirm_deep),
            (self.steam_toggle, settings.prefer_steam),
            (self.notify_toggle, settings.notify),
            (self.tray_toggle, settings.minimize_to_tray),
        )
        for widget, value in widgets:
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)
        self.interval_slider.blockSignals(True)
        self.interval_slider.setValue(int(settings.interval_ms))
        self.interval_slider.blockSignals(False)
        self.interval_label.setText(f"{settings.interval_ms / 1000:.1f} 秒")
        self.timeout_slider.blockSignals(True)
        self.timeout_slider.setValue(int(settings.verify_timeout))
        self.timeout_slider.blockSignals(False)
        self.timeout_label.setText(f"{int(settings.verify_timeout)} 秒")
        index = self.profile_combo.findData(settings.auto_fix_profile)
        if index >= 0:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(index)
            self.profile_combo.blockSignals(False)
        self.set_admin_state(False)
        self.set_backup_info(None)

    def set_admin_state(self, is_admin: bool, can_elevate: bool = True) -> None:
        self.admin_label.setText("管理员" if is_admin else "普通用户")
        self.admin_label.setStyleSheet(f"color: {theme.SUCCESS if is_admin else theme.WARN};")
        self.elevate_button.setVisible(not is_admin and can_elevate)

    def set_backup_info(self, info: tuple[str, str] | None) -> None:
        if info is None:
            self.backup_label.setText("暂无备份")
        else:
            name, size_text = info
            self.backup_label.setText(f"{name} · {size_text}")

    # -- 回调 ---------------------------------------------------------------
    def _emit_changed(self) -> None:
        self.settings.save()
        self.settings_changed.emit()

    def _on_monitor(self, value: bool) -> None:
        self.settings.monitor_enabled = bool(value)
        self._emit_changed()

    def _on_autofix(self, value: bool) -> None:
        self.settings.auto_fix = bool(value)
        self._emit_changed()

    def _on_confirm(self, value: bool) -> None:
        self.settings.confirm_deep = bool(value)
        self._emit_changed()

    def _on_steam(self, value: bool) -> None:
        self.settings.prefer_steam = bool(value)
        self._emit_changed()

    def _on_notify(self, value: bool) -> None:
        self.settings.notify = bool(value)
        self._emit_changed()

    def _on_tray(self, value: bool) -> None:
        self.settings.minimize_to_tray = bool(value)
        self._emit_changed()

    def _on_interval(self, value: int) -> None:
        self.settings.interval_ms = int(value)
        self.interval_label.setText(f"{value / 1000:.1f} 秒")
        self._emit_changed()

    def _on_timeout(self, value: int) -> None:
        self.settings.verify_timeout = float(value)
        self.timeout_label.setText(f"{value} 秒")
        self._emit_changed()

    def _on_profile(self, _index: int) -> None:
        self.settings.auto_fix_profile = self.profile_combo.currentData()
        self._emit_changed()


# ---------------------------------------------------------------------------
# 诊断弹窗
# ---------------------------------------------------------------------------
class DiagnosticsDialog(QDialog):
    STATUS_LABELS = {"ok": "正常", "info": "提示", "warn": "提醒", "error": "问题"}
    STATUS_KINDS = {"ok": "ok", "info": "info", "warn": "warn", "error": "error"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(720, 560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card(margins=22, spacing=14)
        outer.addWidget(card)
        header = QHBoxLayout()
        header.addWidget(label("系统诊断", "h2"))
        header.addStretch(1)
        self.score_label = label("健康度 100", "small")
        header.addWidget(self.score_label)
        close_button = QPushButton("关闭")
        close_button.setProperty("btn", "ghost")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.reject)
        header.addWidget(close_button)
        card.body.addLayout(header)
        self.summary_label = label("", "small")
        card.body.addWidget(self.summary_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.items_host = QVBoxLayout()
        self.items_host.setContentsMargins(0, 0, 6, 4)
        self.items_host.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self.items_host)
        scroll.setWidget(holder)
        card.body.addWidget(scroll, 1)

    def show_diagnosis(self, diagnosis: diagnostics.Diagnosis, execute: bool = True) -> None:
        while self.items_host.count():
            item = self.items_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.score_label.setText(f"健康度 {diagnosis.health_score}")
        self.summary_label.setText(diagnostics.summary_text(diagnosis))
        for check in diagnosis.sorted():
            row = QFrame()
            row.setObjectName("Inner")
            row.setAttribute(Qt.WA_StyledBackground, True)
            layout = QVBoxLayout(row)
            layout.setContentsMargins(14, 11, 14, 11)
            layout.setSpacing(4)
            top = QHBoxLayout()
            top.addWidget(Pill(self.STATUS_LABELS.get(check.status, check.status), self.STATUS_KINDS.get(check.status, "info")))
            title = label(check.title, "h3")
            top.addWidget(title)
            top.addStretch(1)
            layout.addLayout(top)
            detail = label(check.detail, "small")
            detail.setWordWrap(True)
            layout.addWidget(detail)
            if check.hint:
                hint = label(("提示：" if check.status != "info" else "") + check.hint, "small")
                hint.setWordWrap(True)
                hint.setStyleSheet(f"color: {theme.TEXT_MUTED};")
                layout.addWidget(hint)
            self.items_host.addWidget(row)
        self.items_host.addStretch(1)
        if execute:
            self.exec()
        else:
            self.show()


class BackupsDialog(QDialog):
    restore_requested = Signal(str)
    open_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(560, 420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card(margins=22, spacing=12)
        outer.addWidget(card)
        header = QHBoxLayout()
        header.addWidget(label("修复备份", "h2"))
        header.addStretch(1)
        open_button = QPushButton("打开目录")
        open_button.setProperty("btn", "ghost")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(self.open_requested.emit)
        header.addWidget(open_button)
        close_button = QPushButton("关闭")
        close_button.setProperty("btn", "ghost")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.reject)
        header.addWidget(close_button)
        card.body.addLayout(header)
        card.body.addWidget(label("深度修复会先把授权缓存移动到备份目录；失败时可以一键还原。", "small"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.items_host = QVBoxLayout()
        self.items_host.setContentsMargins(0, 0, 6, 4)
        self.items_host.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self.items_host)
        scroll.setWidget(holder)
        card.body.addWidget(scroll, 1)

    def show_backups(self, backups: list[tuple[str, str, int]], execute: bool = True) -> None:
        """backups: [(name, size_text, item_count)]"""
        while self.items_host.count():
            item = self.items_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not backups:
            self.items_host.addWidget(EmptyState("shield", "还没有备份", "执行一次深度修复后会在这里生成备份。"))
        for name, size_text, count in backups:
            row = QFrame()
            row.setObjectName("Inner")
            row.setAttribute(Qt.WA_StyledBackground, True)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(14, 10, 12, 10)
            layout.setSpacing(10)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(label(name, "h3"))
            text.addWidget(label(f"{count} 个文件 · {size_text}", "small"))
            layout.addLayout(text, 1)
            restore = QPushButton("还原")
            restore.setProperty("btn", "mini")
            restore.setCursor(Qt.PointingHandCursor)
            restore.clicked.connect(lambda _=False, n=name: self.restore_requested.emit(n))
            layout.addWidget(restore)
            self.items_host.addWidget(row)
        self.items_host.addStretch(1)
        if execute:
            self.exec()
        else:
            self.show()
