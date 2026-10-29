"""统一视觉：配色、字体、QSS。"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

# ---------------------------------------------------------------------------
# 色板
# ---------------------------------------------------------------------------
BG = "#080C14"
BG_SOFT = "#0C1220"
SURFACE = "#101828"
SURFACE_2 = "#152136"
SURFACE_3 = "#1A2840"
BORDER = "#1D2B44"
BORDER_SOFT = "#17223A"
TEXT = "#E9EFFA"
TEXT_DIM = "#93A5C4"
TEXT_MUTED = "#5F7192"
ACCENT = "#5B8CFF"
ACCENT_2 = "#9B6BFF"
ACCENT_SOFT = "#7AA0FF"
SUCCESS = "#3DDC97"
WARN = "#FFB65C"
DANGER = "#FF5F6E"
INFO = "#4FC3F7"

LEVEL_COLORS = {
    "info": INFO,
    "success": SUCCESS,
    "warn": WARN,
    "error": DANGER,
    "action": ACCENT,
    "dim": TEXT_MUTED,
}

STATUS_COLORS = {
    "ok": SUCCESS,
    "info": INFO,
    "warn": WARN,
    "error": DANGER,
}

# 字体候选（Windows 上优先中文 UI 字体）
_FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Segoe UI",
    "Noto Sans SC",
    "PingFang SC",
)
_MONO_CANDIDATES = ("Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New")


def _pick_font(candidates: tuple[str, ...], fallback: str) -> str:
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"


_WINDOWS_FONTS = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
)


def _ensure_system_fonts() -> None:
    """某些离屏 / 精简环境没有字体库，手动加载系统字体，避免界面全是方块。"""
    if QFontDatabase.families():
        return
    for path in _WINDOWS_FONTS:
        try:
            QFontDatabase.addApplicationFont(path)
        except Exception:
            continue


def init_theme(app) -> None:
    global FONT_FAMILY, MONO_FAMILY
    _ensure_system_fonts()
    FONT_FAMILY = _pick_font(_FONT_CANDIDATES, "Microsoft YaHei UI")
    MONO_FAMILY = _pick_font(_MONO_CANDIDATES, "Consolas")

    font = QFont(FONT_FAMILY, 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(SURFACE_2))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(SURFACE_2))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#0A0E17"))
    palette.setColor(QPalette.ToolTipBase, QColor(SURFACE_2))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    app.setPalette(palette)


def font(size: int = 10, weight: int = 400, mono: bool = False) -> QFont:
    family = MONO_FAMILY if mono else FONT_FAMILY
    result = QFont(family, size)
    result.setWeight(QFont.Weight(weight))
    return result


# ---------------------------------------------------------------------------
# QSS
# ---------------------------------------------------------------------------
def build_qss() -> str:
    return f"""
    * {{
        font-family: "{FONT_FAMILY}";
        outline: none;
    }}
    QWidget {{
        color: {TEXT};
        background: transparent;
    }}
    QToolTip {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 6px 9px;
        font-size: 12px;
    }}

    /* ---------------- 容器 ---------------- */
    QFrame#Root {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: 18px;
    }}
    QFrame#TitleBar {{
        background: transparent;
        border: none;
    }}
    QFrame#Sidebar {{
        background: {BG_SOFT};
        border-top-left-radius: 18px;
        border-bottom-left-radius: 18px;
        border: 1px solid {BORDER_SOFT};
        border-top: none;
        border-left: none;
        border-bottom: none;
    }}
    QFrame#Card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 16px;
    }}
    QFrame#CardSoft {{
        background: {SURFACE_2};
        border: 1px solid {BORDER_SOFT};
        border-radius: 14px;
    }}
    QFrame#Inner {{
        background: {BG_SOFT};
        border: 1px solid {BORDER_SOFT};
        border-radius: 12px;
    }}
    QFrame#Divider {{
        background: {BORDER_SOFT};
        border: none;
        max-height: 1px;
        min-height: 1px;
    }}
    QFrame#AccentBar {{
        border: none;
        border-radius: 2px;
    }}

    /* ---------------- 文本 ---------------- */
    QLabel {{
        background: transparent;
        border: none;
    }}
    QLabel[role="h1"] {{ font-size: 24px; font-weight: 700; color: {TEXT}; }}
    QLabel[role="h2"] {{ font-size: 17px; font-weight: 700; color: {TEXT}; }}
    QLabel[role="h3"] {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
    QLabel[role="body"] {{ font-size: 13px; color: {TEXT_DIM}; }}
    QLabel[role="small"] {{ font-size: 12px; color: {TEXT_MUTED}; }}
    QLabel[role="mono"] {{ font-size: 12px; color: {TEXT_DIM}; font-family: "{MONO_FAMILY}"; }}
    QLabel[role="value"] {{ font-size: 26px; font-weight: 700; color: {TEXT}; }}
    QLabel[role="accent"] {{ color: {ACCENT_SOFT}; }}
    QLabel[role="dim"] {{ color: {TEXT_MUTED}; }}

    /* ---------------- 徽章 ---------------- */
    QLabel[pill="ok"] {{
        color: {SUCCESS}; background: rgba(61, 220, 151, 0.12);
        border: 1px solid rgba(61, 220, 151, 0.32);
        border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
    }}
    QLabel[pill="warn"] {{
        color: {WARN}; background: rgba(255, 182, 92, 0.12);
        border: 1px solid rgba(255, 182, 92, 0.34);
        border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
    }}
    QLabel[pill="error"] {{
        color: {DANGER}; background: rgba(255, 95, 110, 0.12);
        border: 1px solid rgba(255, 95, 110, 0.34);
        border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
    }}
    QLabel[pill="info"] {{
        color: {INFO}; background: rgba(79, 195, 247, 0.12);
        border: 1px solid rgba(79, 195, 247, 0.3);
        border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
    }}
    QLabel[pill="accent"] {{
        color: {ACCENT_SOFT}; background: rgba(91, 140, 255, 0.14);
        border: 1px solid rgba(91, 140, 255, 0.34);
        border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
    }}
    QLabel[pill="muted"] {{
        color: {TEXT_DIM}; background: rgba(147, 165, 196, 0.08);
        border: 1px solid {BORDER};
        border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
    }}

    /* ---------------- 按钮 ---------------- */
    QPushButton {{
        border: none;
        border-radius: 10px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
        background: {SURFACE_3};
    }}
    QPushButton:hover {{ background: #20304C; }}
    QPushButton:pressed {{ background: #1A2740; }}
    QPushButton:disabled {{ color: {TEXT_MUTED}; background: {SURFACE_2}; }}

    QPushButton[btn="primary"] {{
        color: #0A1020;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #6FA0FF, stop:1 #A97BFF);
        padding: 9px 20px;
    }}
    QPushButton[btn="primary"]:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #85B0FF, stop:1 #B98FFF);
    }}
    QPushButton[btn="primary"]:pressed {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #5C8DEF, stop:1 #8F63EF);
    }}
    QPushButton[btn="primary"]:disabled {{ color: #64718A; background: {SURFACE_3}; }}

    QPushButton[btn="ghost"] {{
        color: {TEXT_DIM};
        background: rgba(147, 165, 196, 0.07);
        border: 1px solid {BORDER};
    }}
    QPushButton[btn="ghost"]:hover {{ color: {TEXT}; border-color: #2A3C5C; background: rgba(147, 165, 196, 0.12); }}

    QPushButton[btn="danger"] {{
        color: {DANGER};
        background: rgba(255, 95, 110, 0.1);
        border: 1px solid rgba(255, 95, 110, 0.32);
    }}
    QPushButton[btn="danger"]:hover {{ background: rgba(255, 95, 110, 0.18); }}

    QPushButton[btn="mini"] {{
        padding: 4px 11px;
        font-size: 12px;
        border-radius: 8px;
        color: {TEXT_DIM};
        background: rgba(147, 165, 196, 0.08);
        border: 1px solid {BORDER};
    }}
    QPushButton[btn="mini"]:hover {{ color: {TEXT}; background: rgba(147, 165, 196, 0.15); }}

    QPushButton[chip="true"] {{
        padding: 5px 13px;
        font-size: 12px;
        font-weight: 500;
        color: {TEXT_DIM};
        background: rgba(147, 165, 196, 0.06);
        border: 1px solid {BORDER_SOFT};
        border-radius: 14px;
    }}
    QPushButton[chip="true"]:hover {{ color: {TEXT}; border-color: #2A3C5C; }}
    QPushButton[chip="true"]:checked {{
        color: {ACCENT_SOFT};
        background: rgba(91, 140, 255, 0.16);
        border: 1px solid rgba(91, 140, 255, 0.45);
    }}

    /* ---------------- 输入 ---------------- */
    QLineEdit {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 8px 12px;
        color: {TEXT};
        font-size: 13px;
        selection-background-color: rgba(91, 140, 255, 0.4);
    }}
    QLineEdit:focus {{ border: 1px solid rgba(91, 140, 255, 0.6); }}
    QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}

    QComboBox {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 7px 12px;
        color: {TEXT};
        font-size: 12px;
        min-width: 108px;
    }}
    QComboBox:hover {{ border-color: #2A3C5C; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 4px;
        selection-background-color: rgba(91, 140, 255, 0.22);
        color: {TEXT};
    }}

    QSlider::groove:horizontal {{
        height: 4px;
        background: {SURFACE_3};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6FA0FF, stop:1 #A97BFF);
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -6px 0;
        border-radius: 7px;
        background: #EAF1FF;
    }}

    /* ---------------- 滚动条 ---------------- */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px 0;
    }}
    QScrollBar::handlevisibility:vertical {{ background: transparent; }}
    QScrollBar::handle:vertical {{
        background: #26354E;
        min-height: 32px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #324560; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
    }}
    QScrollBar::handle:horizontal {{
        background: #26354E;
        min-width: 32px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ---------------- 列表 ---------------- */
    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
        padding: 0;
    }}
    QListWidget::item {{ border: none; padding: 0; margin: 0; }}
    QListWidget::item:selected {{ background: transparent; }}

    QProgressBar {{
        background: {SURFACE_3};
        border: none;
        border-radius: 3px;
        height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        border-radius: 3px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #6FA0FF, stop:1 #A97BFF);
    }}

    QDialog {{ background: transparent; }}
    """
