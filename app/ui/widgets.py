"""自绘控件库：卡片、徽章、脉冲点、步骤行、游戏卡、开关、导航等。"""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def label(text: str = "", role: str = "body", parent: QWidget | None = None) -> QLabel:
    item = QLabel(text, parent)
    item.setProperty("role", role)
    return item


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    return line


def elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


# ---------------------------------------------------------------------------
# 基础容器
# ---------------------------------------------------------------------------
class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, soft: bool = False, margins: int = 18, spacing: int = 12):
        super().__init__(parent)
        self.setObjectName("CardSoft" if soft else "Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(spacing)


class HeroCard(QFrame):
    """带渐变光晕的主状态卡。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(156)
        self._accent = QColor(theme.ACCENT)
        self.body = QHBoxLayout(self)
        self.body.setContentsMargins(24, 22, 24, 22)
        self.body.setSpacing(22)

    def set_accent(self, color: str | QColor) -> None:
        self._accent = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        glow = QRadialGradient(rect.left() + rect.width() * 0.18, rect.top() + rect.height() * 0.2, rect.width() * 0.7)
        color = QColor(self._accent)
        color.setAlpha(46)
        glow.setColorAt(0.0, color)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)
        painter.setClipPath(path)
        painter.fillRect(rect, glow)
        painter.end()


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.title = label(title, "h1")
        layout.addWidget(self.title)
        self.subtitle = label(subtitle, "body")
        self.subtitle.setVisible(bool(subtitle))
        layout.addWidget(self.subtitle)


class Pill(QLabel):
    def __init__(self, text: str = "", kind: str = "muted", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("pill", kind)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_kind(self, kind: str, text: str | None = None) -> None:
        if text is not None:
            self.setText(text)
        self.setProperty("pill", kind)
        repolish(self)


# ---------------------------------------------------------------------------
# 自绘：脉冲状态点 / 图标 / 封面 / 开关 / 步骤
# ---------------------------------------------------------------------------
class PulseDot(QWidget):
    def __init__(self, color: str = theme.SUCCESS, diameter: int = 14, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._color = QColor(color)
        self._phase = 0.0
        self.setFixedSize(diameter * 3, diameter * 3)
        self._animation = QPropertyAnimation(self, b"phase", self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(2200)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.InOutSine)
        self._animation.start()

    def get_phase(self) -> float:
        return self._phase

    def set_phase(self, value: float) -> None:
        self._phase = float(value)
        self.update()

    phase = Property(float, get_phase, set_phase)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def stop(self) -> None:
        self._animation.stop()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QRectF(self.rect()).center()
        radius = self._diameter / 2
        pulse = 0.5 + 0.5 * math.sin(self._phase * 2 * math.pi)
        glow = QRadialGradient(center, radius * (1.7 + pulse * 1.5))
        color = QColor(self._color)
        color.setAlpha(int(70 - 40 * pulse))
        glow.setColorAt(0.0, color)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), glow)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(center, radius, radius)
        painter.end()


def _paint_icon(painter: QPainter, name: str, rect: QRectF, color: QColor, stroke: float = 1.6) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, stroke, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    if name == "overview":
        for dx, dy in ((0, 0), (0.55, 0), (0, 0.55), (0.55, 0.55)):
            painter.drawRoundedRect(QRectF(x + w * dx, y + h * dy, w * 0.42, h * 0.42), 2.5, 2.5)
    elif name == "games":
        for index in range(3):
            painter.drawRoundedRect(QRectF(x, y + h * (0.1 + index * 0.3), w * 0.72, h * 0.18), 2.5, 2.5)
            painter.drawEllipse(QPoint(int(x + w * 0.88), int(y + h * (0.19 + index * 0.3))), 1.6, 1.6)
    elif name == "fix":
        painter.drawLine(int(x + w * 0.22), int(y + h * 0.82), int(x + w * 0.8), int(y + h * 0.22))
        painter.drawArc(QRectF(x + w * 0.55, y + h * 0.02, w * 0.42, h * 0.42), 30 * 16, 240 * 16)
        painter.drawArc(QRectF(x + w * 0.03, y + h * 0.56, w * 0.42, h * 0.42), 30 * 16, 240 * 16)
    elif name == "logs":
        painter.drawRoundedRect(QRectF(x + w * 0.16, y + h * 0.1, w * 0.68, h * 0.8), 3, 3)
        for index in range(3):
            painter.drawLine(
                int(x + w * 0.3),
                int(y + h * (0.34 + index * 0.17)),
                int(x + w * (0.7 if index != 2 else 0.56)),
                int(y + h * (0.34 + index * 0.17)),
            )
    elif name == "settings":
        painter.drawEllipse(QRectF(x + w * 0.3, y + h * 0.3, w * 0.4, h * 0.4))
        for index in range(8):
            angle = math.radians(index * 45)
            inner = w * 0.3
            outer = w * 0.46
            cx = x + w * 0.5
            cy = y + h * 0.5
            painter.drawLine(
                int(cx + math.cos(angle) * inner),
                int(cy + math.sin(angle) * inner),
                int(cx + math.cos(angle) * outer),
                int(cy + math.sin(angle) * outer),
            )
    elif name == "shield":
        path = QPainterPath()
        path.moveTo(x + w * 0.5, y + h * 0.06)
        path.lineTo(x + w * 0.92, y + h * 0.24)
        path.lineTo(x + w * 0.86, y + h * 0.66)
        path.quadTo(x + w * 0.5, y + h * 0.95, x + w * 0.14, y + h * 0.66)
        path.lineTo(x + w * 0.08, y + h * 0.24)
        path.closeSubpath()
        painter.drawPath(path)
        play = QPainterPath()
        play.moveTo(x + w * 0.42, y + h * 0.36)
        play.lineTo(x + w * 0.66, y + h * 0.5)
        play.lineTo(x + w * 0.42, y + h * 0.64)
        play.closeSubpath()
        painter.fillPath(play, QBrush(color))
    elif name == "spark":
        cx, cy = x + w * 0.5, y + h * 0.5
        for angle in (0, 90, 180, 270):
            rad = math.radians(angle)
            painter.drawLine(
                int(cx + math.cos(rad) * w * 0.12),
                int(cy + math.sin(rad) * h * 0.12),
                int(cx + math.cos(rad) * w * 0.36),
                int(cy + math.sin(rad) * h * 0.36),
            )
        painter.drawEllipse(QRectF(x + w * 0.32, y + h * 0.32, w * 0.36, h * 0.36))
    painter.restore()


class IconWidget(QWidget):
    def __init__(self, name: str, size: int = 18, color: str = theme.TEXT_DIM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        _paint_icon(painter, self._name, QRectF(self.rect()), self._color)
        painter.end()


class NavButton(QAbstractButton):
    def __init__(self, icon_name: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(91, 140, 255, 36))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 9, 3, rect.height() - 18), 1.5, 1.5)
        elif self._hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(147, 165, 196, 18))
            painter.drawRoundedRect(rect, 10, 10)
        color = QColor(theme.ACCENT_SOFT if self.isChecked() else theme.TEXT_DIM)
        if self._hover and not self.isChecked():
            color = QColor(theme.TEXT)
        _paint_icon(painter, self._icon_name, QRectF(rect.left() + 14, rect.center().y() - 9, 18, 18), color)
        font = theme.font(10, 600)
        painter.setFont(font)
        painter.setPen(QPen(color))
        painter.drawText(
            QRectF(rect.left() + 42, rect.top(), rect.width() - 48, rect.height()),
            int(Qt.AlignVCenter | Qt.AlignLeft),
            self.text(),
        )
        painter.end()


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 23)
        self._offset = 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    offset = Property(float, get_offset, set_offset)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        if self.isChecked():
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#6FA0FF"))
            gradient.setColorAt(1, QColor("#A97BFF"))
            painter.setBrush(gradient)
        else:
            painter.setBrush(QColor(theme.SURFACE_3))
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(rect, radius, radius)
        thumb_radius = radius - 2.5
        center_x = rect.left() + 2.5 + thumb_radius + self._offset * (rect.width() - 5 - thumb_radius * 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F4F8FF"))
        painter.drawEllipse(QRectF(center_x - thumb_radius, rect.center().y() - thumb_radius, thumb_radius * 2, thumb_radius * 2))
        painter.end()


class StepIcon(QWidget):
    STATUS_STYLE = {
        "pending": (theme.TEXT_MUTED, "dot"),
        "running": (theme.ACCENT_SOFT, "spinner"),
        "ok": (theme.SUCCESS, "check"),
        "warn": (theme.WARN, "warn"),
        "fail": (theme.DANGER, "cross"),
        "skip": (theme.TEXT_MUTED, "dash"),
        "simulated": (theme.INFO, "dots"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = "pending"
        self._angle = 0
        self.setFixedSize(26, 26)
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)

    def set_status(self, status: str) -> None:
        self._status = status
        if status == "running":
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color_name, shape = self.STATUS_STYLE.get(self._status, (theme.TEXT_MUTED, "dot"))
        color = QColor(color_name)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if shape == "spinner":
            painter.setPen(QPen(QColor(theme.SURFACE_3), 2.2))
            painter.drawEllipse(rect)
            pen = QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, int(self._angle * 16), int(110 * 16))
            painter.end()
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 34))
        painter.drawEllipse(rect)
        pen = QPen(color, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        center = rect.center()
        if shape == "check":
            painter.drawLine(
                QPoint(int(rect.left() + 4), int(center.y())),
                QPoint(int(center.x() - 0.5), int(rect.bottom() - 5)),
            )
            painter.drawLine(
                QPoint(int(center.x() - 0.5), int(rect.bottom() - 5)),
                QPoint(int(rect.right() - 4), int(rect.top() + 5)),
            )
        elif shape == "cross":
            painter.drawLine(QPoint(int(rect.left() + 5), int(rect.top() + 5)), QPoint(int(rect.right() - 5), int(rect.bottom() - 5)))
            painter.drawLine(QPoint(int(rect.right() - 5), int(rect.top() + 5)), QPoint(int(rect.left() + 5), int(rect.bottom() - 5)))
        elif shape == "warn":
            painter.drawLine(QPoint(int(center.x()), int(rect.top() + 5)), QPoint(int(center.x()), int(center.y() + 2)))
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPoint(int(center.x()), int(rect.bottom() - 5)), 1.4, 1.4)
        elif shape == "dash":
            painter.drawLine(QPoint(int(rect.left() + 6), int(center.y())), QPoint(int(rect.right() - 6), int(center.y())))
        else:
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(center, 2.6, 2.6)
        painter.end()


class StepRow(QFrame):
    def __init__(self, index: int, title: str, detail: str, risk_label: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Inner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 8)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(9)
        self.icon = StepIcon()
        top.addWidget(self.icon, 0, Qt.AlignVCenter)
        self.title_label = label(f"{index:02d}  {title}", "h3")
        top.addWidget(self.title_label, 0, Qt.AlignVCenter)
        top.addStretch(1)
        self.risk_label = label(risk_label, "small")
        top.addWidget(self.risk_label, 0, Qt.AlignVCenter)
        self.status_label = label("等待", "small")
        self.status_label.setFixedWidth(52)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.status_label, 0, Qt.AlignVCenter)
        layout.addLayout(top)

        self.detail_label = label(detail, "small")
        self.detail_label.setWordWrap(True)
        self.detail_label.setContentsMargins(35, 0, 0, 0)
        self.detail_label.setMinimumWidth(120)
        self.detail_label.setStyleSheet(f"font-size: 11px; color: {theme.TEXT_MUTED};")
        layout.addWidget(self.detail_label)

    def set_status(self, status: str) -> None:
        self.icon.set_status(status)
        self.status_label.setText(
            {
                "pending": "等待",
                "running": "执行中",
                "ok": "完成",
                "warn": "注意",
                "fail": "失败",
                "skip": "跳过",
                "simulated": "模拟",
            }.get(status, status)
        )
        color = {
            "ok": theme.SUCCESS,
            "warn": theme.WARN,
            "fail": theme.DANGER,
            "running": theme.ACCENT_SOFT,
        }.get(status, theme.TEXT_MUTED)
        self.status_label.setStyleSheet(f"color: {color};")

    def set_message(self, message: str) -> None:
        self.detail_label.setText(message)


class GameCover(QWidget):
    def __init__(self, initials: str, colors: tuple[str, str], size: int = 58, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._initials = initials
        self._colors = colors
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        painter.setClipPath(path)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(self._colors[0]))
        gradient.setColorAt(1, QColor(self._colors[1]))
        painter.fillRect(rect, gradient)
        painter.setBrush(QColor(255, 255, 255, 26))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(rect.right() - 30, rect.top() - 16, 48, 48))
        painter.setPen(QPen(QColor(12, 18, 32, 210)))
        painter.setFont(theme.font(15, 800))
        painter.drawText(rect, int(Qt.AlignCenter), self._initials)
        painter.end()


class StatTile(Card):
    def __init__(self, title: str, value: str = "—", accent: str = theme.ACCENT, parent: QWidget | None = None) -> None:
        super().__init__(parent, soft=True, margins=14, spacing=2)
        self.setMinimumHeight(78)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        bar = QFrame()
        bar.setObjectName("AccentBar")
        bar.setFixedSize(3, 14)
        bar.setStyleSheet(f"background: {accent}; border-radius: 1.5px;")
        top.addWidget(bar)
        self.title_label = label(title, "small")
        top.addWidget(self.title_label)
        top.addStretch(1)
        self.body.addLayout(top)
        self.value_label = label(value, "value")
        self.body.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class GameCard(Card):
    launch_clicked = Signal(str)
    fix_clicked = Signal(str)
    diagnose_clicked = Signal(str)

    def __init__(self, game, state: tuple[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent, margins=16, spacing=11)
        self.game = game
        self.setMinimumWidth(330)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        header.addWidget(GameCover(game.initials, game.accent))
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        self.name_label = label(game.display, "h3")
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.addWidget(self.name_label)
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        meta.addWidget(Pill(game.platform_label, "accent" if game.platform == "steam" else "muted"))
        status_kind, status_text = state
        self.state_pill = Pill(status_text, status_kind)
        meta.addWidget(self.state_pill)
        meta.addStretch(1)
        text.addLayout(meta)
        header.addLayout(text, 1)
        self.body.addLayout(header)

        path_text = elide(game.install_dir or "未找到安装目录", 46)
        self.path_label = label(path_text, "small")
        self.path_label.setToolTip(game.install_dir or "")
        self.body.addWidget(self.path_label)

        if game.extras:
            warn = label("检测到第三方启动器：" + "、".join(game.extras[:2]), "small")
            warn.setStyleSheet(f"color: {theme.WARN};")
            self.body.addWidget(warn)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)
        self.launch_button = QPushButton("启动")
        self.launch_button.setProperty("btn", "primary")
        self.launch_button.setCursor(Qt.PointingHandCursor)
        self.launch_button.clicked.connect(lambda: self.launch_clicked.emit(self.game.key))
        actions.addWidget(self.launch_button)
        self.diagnose_button = QPushButton("诊断")
        self.diagnose_button.setProperty("btn", "ghost")
        self.diagnose_button.setCursor(Qt.PointingHandCursor)
        self.diagnose_button.clicked.connect(lambda: self.diagnose_clicked.emit(self.game.key))
        actions.addWidget(self.diagnose_button)
        actions.addStretch(1)
        self.body.addLayout(actions)
        if not game.installed:
            self.launch_button.setEnabled(False)
            self.diagnose_button.setEnabled(False)


class SegmentedControl(QWidget):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Inner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._buttons: dict[str, QPushButton] = {}
        for value, text in options:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("btn", "seg")
            button.setStyleSheet(
                f"""
                QPushButton {{ border: none; border-radius: 8px; padding: 5px 13px;
                    background: transparent; color: {theme.TEXT_DIM}; font-size: 12px; font-weight: 600; }}
                QPushButton:hover {{ color: {theme.TEXT}; }}
                QPushButton:checked {{ background: rgba(91,140,255,0.2); color: {theme.ACCENT_SOFT}; }}
                """
            )
            button.clicked.connect(lambda _=False, v=value: self._select(v))
            layout.addWidget(button)
            self._buttons[value] = button
        if self._buttons:
            next(iter(self._buttons.values())).setChecked(True)

    def _select(self, value: str) -> None:
        for key, button in self._buttons.items():
            button.setChecked(key == value)
        self.changed.emit(value)

    def value(self) -> str:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return next(iter(self._buttons), "")

    def set_value(self, value: str) -> None:
        if value in self._buttons:
            self._select(value)


class LogRow(QFrame):
    def __init__(self, event, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(10)
        color = theme.LEVEL_COLORS.get(event.level, theme.TEXT_MUTED)
        dot = QFrame()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: {color}; border-radius: 3.5px;")
        layout.addWidget(dot, 0, Qt.AlignTop)
        time_label = label(event.time_text, "small")
        time_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-family: '{theme.MONO_FAMILY}'; font-size: 11px;")
        time_label.setFixedWidth(56)
        layout.addWidget(time_label, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        title = label(event.title, "body")
        title.setStyleSheet(f"color: {theme.TEXT if event.level != 'warn' else theme.WARN}; font-size: 12px; font-weight: 600;")
        title.setWordWrap(True)
        text.addWidget(title)
        if event.message:
            message = label(event.message, "small")
            message.setWordWrap(True)
            text.addWidget(message)
        layout.addLayout(text, 1)


class LogList(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSpacing(1)
        self._max_rows = 500
        self._auto_scroll = True
        self._level_filter = ""
        self._search = ""
        self._events: list = []

    def set_filter(self, level: str = "", search: str = "") -> None:
        self._level_filter = level
        self._search = (search or "").lower()
        self.refresh()

    def add_event(self, event) -> None:
        self._events.append(event)
        if len(self._events) > 800:
            del self._events[: len(self._events) - 800]
        if self._matches(event) and self.count() < self._max_rows:
            self._append(event)

    def refresh(self) -> None:
        scrollbar = self.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        self.clear()
        for event in self._events:
            if self._matches(event) and self.count() < self._max_rows:
                self._append(event)
        if at_bottom:
            self.scrollToBottom()

    def _matches(self, event) -> bool:
        if self._level_filter and event.level != self._level_filter:
            return False
        if self._search:
            haystack = f"{event.title} {event.message}".lower()
            return self._search in haystack
        return True

    def _append(self, event) -> None:
        item = QListWidgetItem()
        widget = LogRow(event)
        item.setSizeHint(widget.sizeHint() + QSize(0, 2))
        self.addItem(item)
        self.setItemWidget(item, widget)
        if self._auto_scroll:
            self.scrollToBottom()


class EmptyState(QWidget):
    def __init__(self, icon: str, title: str, detail: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 28, 20, 28)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)
        icon_widget = IconWidget(icon, 34, theme.TEXT_MUTED)
        layout.addWidget(icon_widget, 0, Qt.AlignHCenter)
        title_label = label(title, "h3")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        if detail:
            detail_label = label(detail, "small")
            detail_label.setAlignment(Qt.AlignCenter)
            detail_label.setWordWrap(True)
            detail_label.setMinimumHeight(detail_label.fontMetrics().lineSpacing() * 2 + 2)
            layout.addWidget(detail_label)


class InfoRow(QWidget):
    """左标题右值的设置行。"""

    def __init__(self, title: str, subtitle: str = "", trailing: QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(label(title, "body"))
        if subtitle:
            hint = label(subtitle, "small")
            hint.setWordWrap(True)
            text.addWidget(hint)
        layout.addLayout(text, 1)
        if trailing is not None:
            layout.addWidget(trailing, 0, Qt.AlignVCenter)


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "搜索…", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setFixedHeight(34)


class ConfirmDialog(QDialog):
    """无边框确认框（用于危险操作）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("Card")
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        self.card.setFixedWidth(440)
        outer.addWidget(self.card)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        self.title_label = label("确认操作", "h2")
        layout.addWidget(self.title_label)
        self.message_label = label("", "body")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        self.extra_label = label("", "small")
        self.extra_label.setWordWrap(True)
        self.extra_label.setVisible(False)
        layout.addWidget(self.extra_label)
        layout.addWidget(hline())
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setProperty("btn", "ghost")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        confirm = QPushButton("继续")
        confirm.setProperty("btn", "primary")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    def ask(self, title: str, message: str, extra: str = "") -> bool:
        self.title_label.setText(title)
        self.message_label.setText(message)
        self.extra_label.setText(extra)
        self.extra_label.setVisible(bool(extra))
        self.adjustSize()
        screen = self.parent().screen() if self.parent() is not None else self.screen()
        center = screen.availableGeometry().center()
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        return self.exec() == QDialog.Accepted

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
