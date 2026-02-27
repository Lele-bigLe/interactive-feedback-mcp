# Interactive Feedback MCP UI
# Developed by Fábio Ferreira (https://x.com/fabiomlferreira)
# Inspired by/related to dotcursorrules.com (https://dotcursorrules.com/)
import os
import sys
import json
import argparse
import hashlib
import tempfile
import time
import re
from typing import Optional, TypedDict, List, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QSizePolicy, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSettings
from PySide6.QtGui import (
    QIcon, QKeyEvent, QPalette, QColor,
    QPixmap, QImage, QDragEnterEvent, QDropEvent
)


class FeedbackResult(TypedDict):
    logs: str
    interactive_feedback: str
    image_paths: List[str]  # 图片路径列表
    selected_options: List[str]  # 用户选择的选项列表
    timeout_triggered: bool  # 是否因超时触发重新调用


def parse_file_references(text: str, project_directory: str) -> List[Tuple[str, Optional[int], Optional[int]]]:
    """解析文本中的文件引用

    支持的格式：
    - @相对路径 - 引用整个文件
    - @相对路径#行号 - 引用特定行
    - @相对路径#起始行-结束行 - 引用行范围

    示例：
    - @src/views/dataAdmin/uploadHead/index.vue
    - @src/views/dataAdmin/uploadHead/index.vue#61
    - @src/views/dataAdmin/uploadHead/index.vue#61-70

    返回: [(文件路径, 起始行, 结束行), ...]
    """
    # 匹配 @路径 或 @路径#行号 或 @路径#起始行-结束行
    # 支持完整相对路径，包含 / 和 \ 分隔符
    pattern = r'@([\w./\\][\w./\\-]*(?:\.\w+))(?:#(\d+)(?:-(\d+))?)?'
    matches = re.finditer(pattern, text)

    references = []
    for match in matches:
        filename = match.group(1)
        start_line = int(match.group(2)) if match.group(2) else None
        end_line = int(match.group(3)) if match.group(3) else start_line

        # 统一路径分隔符
        filename = filename.replace('\\', '/')

        # 构建完整路径
        if os.path.isabs(filename):
            file_path = filename
        else:
            file_path = os.path.join(project_directory, filename)

        # 标准化路径
        file_path = os.path.normpath(file_path)

        if os.path.exists(file_path):
            references.append((file_path, start_line, end_line))

    return references


def expand_file_references(text: str, project_directory: str) -> str:
    """展开文本中的文件引用，返回包含引用信息的文本"""
    references = parse_file_references(text, project_directory)
    if not references:
        return text

    expanded_text = text

    for file_path, start_line, end_line in references:
        # 计算相对路径用于显示
        try:
            rel_path = os.path.relpath(file_path, project_directory).replace('\\', '/')
        except ValueError:
            rel_path = file_path

        if start_line is None:
            ref_info = f"\n\n[引用文件: {rel_path}]"
        elif end_line == start_line:
            ref_info = f"\n\n[引用: {rel_path}#{start_line}]"
        else:
            ref_info = f"\n\n[引用: {rel_path}#{start_line}-{end_line}]"

        # 在文本末尾追加引用信息（不替换原始文本）
        expanded_text += ref_info

    return expanded_text


def set_dark_title_bar(widget: QWidget, dark_title_bar: bool) -> None:
    if sys.platform != "win32":
        return

    from ctypes import windll, c_uint32, byref

    build_number = sys.getwindowsversion().build
    if build_number < 17763:
        return

    dark_prop = widget.property("DarkTitleBar")
    if dark_prop is not None and dark_prop == dark_title_bar:
        return

    widget.setProperty("DarkTitleBar", dark_title_bar)

    dwmapi = windll.dwmapi
    hwnd = widget.winId()
    attribute = 20 if build_number >= 18985 else 19
    c_dark_title_bar = c_uint32(dark_title_bar)
    dwmapi.DwmSetWindowAttribute(hwnd, attribute, byref(c_dark_title_bar), 4)

    temp_widget = QWidget(None, Qt.FramelessWindowHint)
    temp_widget.resize(1, 1)
    temp_widget.move(widget.pos())
    temp_widget.show()
    temp_widget.deleteLater()


def get_dark_mode_palette(app: QApplication):
    darkPalette = app.palette()
    darkPalette.setColor(QPalette.Window, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.WindowText, Qt.white)
    darkPalette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.Base, QColor(42, 42, 42))
    darkPalette.setColor(QPalette.AlternateBase, QColor(66, 66, 66))
    darkPalette.setColor(QPalette.ToolTipBase, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ToolTipText, Qt.white)
    darkPalette.setColor(QPalette.Text, Qt.white)
    darkPalette.setColor(QPalette.Disabled, QPalette.Text, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.Dark, QColor(35, 35, 35))
    darkPalette.setColor(QPalette.Shadow, QColor(20, 20, 20))
    darkPalette.setColor(QPalette.Button, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ButtonText, Qt.white)
    darkPalette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.BrightText, Qt.red)
    darkPalette.setColor(QPalette.Link, QColor(42, 130, 218))
    darkPalette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    darkPalette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(80, 80, 80))
    darkPalette.setColor(QPalette.HighlightedText, Qt.white)
    darkPalette.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.PlaceholderText, QColor(127, 127, 127))
    return darkPalette


class FeedbackTextEdit(QTextEdit):
    """自定义文本编辑器，支持纯文本粘贴和图片粘贴"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setAcceptDrops(True)

    def _get_feedback_ui(self):
        """查找父级 FeedbackUI 实例"""
        parent = self.parent()
        while parent and not isinstance(parent, FeedbackUI):
            parent = parent.parent()
        return parent

    def insertFromMimeData(self, source):
        """重写粘贴方法：支持图片粘贴和纯文本"""
        # 优先处理图片数据（剪贴板截图）
        if source.hasImage():
            ui = self._get_feedback_ui()
            if ui:
                image_data = source.imageData()
                if isinstance(image_data, QImage):
                    pixmap = QPixmap.fromImage(image_data)
                elif isinstance(image_data, QPixmap):
                    pixmap = image_data
                else:
                    pixmap = QPixmap()
                if not pixmap.isNull():
                    ui._add_image_from_pixmap(pixmap, "剪贴板截图")
                    return
        # 处理文件URL（拖放图片文件）
        if source.hasUrls():
            ui = self._get_feedback_ui()
            if ui:
                for url in source.urls():
                    file_path = url.toLocalFile()
                    if file_path:
                        ext = os.path.splitext(file_path)[1].lower()
                        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                            pixmap = QPixmap(file_path)
                            if not pixmap.isNull():
                                ui._add_image_from_pixmap(pixmap, file_path)
                return
        # 纯文本粘贴
        if source.hasText():
            self.insertPlainText(source.text())
        else:
            super().insertFromMimeData(source)

    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入：接受图片文件"""
        if event.mimeData().hasImage() or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        """拖放事件：处理图片文件拖放"""
        mime = event.mimeData()
        ui = self._get_feedback_ui()
        if ui:
            if mime.hasImage():
                image_data = mime.imageData()
                if isinstance(image_data, QImage):
                    pixmap = QPixmap.fromImage(image_data)
                elif isinstance(image_data, QPixmap):
                    pixmap = image_data
                else:
                    pixmap = QPixmap()
                if not pixmap.isNull():
                    ui._add_image_from_pixmap(pixmap, "拖放的图片")
                    event.acceptProposedAction()
                    return
            if mime.hasUrls():
                handled = False
                for url in mime.urls():
                    file_path = url.toLocalFile()
                    if file_path:
                        ext = os.path.splitext(file_path)[1].lower()
                        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                            pixmap = QPixmap(file_path)
                            if not pixmap.isNull():
                                ui._add_image_from_pixmap(pixmap, file_path)
                                handled = True
                if handled:
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
            ui = self._get_feedback_ui()
            if ui:
                ui._submit_feedback()
        else:
            super().keyPressEvent(event)


class FeedbackUI(QMainWindow):
    # 预定义超时样式，避免重复创建
    _TIMEOUT_STYLE_NORMAL = """
        font-size: 12px;
        color: #aaa;
        padding: 4px 8px;
        background-color: #333;
        border-radius: 4px;
    """
    _TIMEOUT_STYLE_WARNING = """
        font-size: 12px;
        color: #ffaa66;
        padding: 4px 8px;
        background-color: #4a3a2a;
        border-radius: 4px;
    """
    _TIMEOUT_STYLE_DANGER = """
        font-size: 12px;
        color: #ff6666;
        padding: 4px 8px;
        background-color: #4a2a2a;
        border-radius: 4px;
        font-weight: bold;
    """
    _TIMEOUT_STYLE_PAUSED = """
        font-size: 12px;
        color: #ffc;
        padding: 4px 8px;
        background-color: #5a4a3a;
        border-radius: 4px;
    """

    def __init__(self, project_directory: str, prompt: str, current_file: Optional[str] = None, timeout_seconds: int = 600, options: Optional[List[str]] = None):
        super().__init__()
        self.project_directory = project_directory
        self.prompt = prompt
        self.current_file = current_file
        self.timeout_seconds = timeout_seconds
        self.start_time = time.time()
        self.timeout_triggered = False
        self.options = options or []
        self.selected_options: List[str] = []  # 已选中的选项
        self.image_paths: List[str] = []  # 图片路径列表
        self.temp_image_counter = 0  # 临时图片计数器

        self.feedback_result = None

        # 超时样式状态缓存，避免重复设置样式
        self._current_timeout_style = None

        # 获取项目名称
        self.project_name = os.path.basename(os.path.normpath(project_directory))
        self.setWindowTitle(f"交互式反馈 - [{self.project_name}]")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "images", "feedback.png")
        self.setWindowIcon(QIcon(icon_path))
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self.settings = QSettings("InteractiveFeedbackMCP", "InteractiveFeedbackMCP")

        # 加载窗口几何信息
        self.settings.beginGroup("MainWindow_General")
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(800, 600)
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - 800) // 2
            y = (screen.height() - 600) // 2
            self.move(x, y)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        self.settings.endGroup()

        self._create_ui()
        set_dark_title_bar(self, True)
        self._setup_timeout_timer()

    def _apply_styles(self):
        """应用全局样式表"""
        style = """
            /* 主按钮样式 */
            QPushButton {
                background-color: #3d3d3d;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 8px 16px;
                color: #fff;
                font-size: 13px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #666;
            }
            QPushButton:pressed {
                background-color: #2d2d2d;
            }

            /* 主要操作按钮 */
            QPushButton#primaryButton {
                background-color: #2a82da;
                border: 1px solid #3a92ea;
            }
            QPushButton#primaryButton:hover {
                background-color: #3a92ea;
            }

            /* 分组框样式 */
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #323232;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                color: #aaa;
            }

            /* 文本编辑器样式 */
            QTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 8px;
                color: #fff;
                font-size: 13px;
            }
            QTextEdit:focus {
                border-color: #2a82da;
            }

            /* 标签样式 */
            QLabel {
                color: #ddd;
                font-size: 13px;
            }
            QLabel#descriptionLabel {
                font-size: 14px;
                color: #fff;
                padding: 8px;
                background-color: #3a4a5a;
                border-radius: 6px;
                border-left: 4px solid #2a82da;
            }
        """
        self.setStyleSheet(style)

    def _create_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self._apply_styles()

        # 项目标识和超时计时器区域
        project_info_layout = QHBoxLayout()
        project_info_layout.setSpacing(12)

        self.project_label = QLabel(f"📁 {self.project_name}")
        self.project_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #4a9eff;
            padding: 4px 10px;
            background-color: #2a3a4a;
            border-radius: 4px;
        """)
        self.project_label.setToolTip(f"项目路径: {self.project_directory}")
        project_info_layout.addWidget(self.project_label)

        project_info_layout.addStretch()

        # 超时倒计时标签
        self.timeout_label = QLabel()
        self.timeout_label.setStyleSheet(self._TIMEOUT_STYLE_NORMAL)
        project_info_layout.addWidget(self.timeout_label)

        # 重新计时按钮
        self.reset_timer_button = QPushButton("🔄 重新计时")
        self.reset_timer_button.setFixedWidth(90)
        self.reset_timer_button.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                padding: 4px 8px;
                background-color: #3a5a3a;
                border: 1px solid #4a6a4a;
                border-radius: 4px;
                color: #cfc;
            }
            QPushButton:hover {
                background-color: #4a6a4a;
            }
        """)
        self.reset_timer_button.clicked.connect(self._reset_timeout)
        project_info_layout.addWidget(self.reset_timer_button)

        # 停止计时按钮
        self.stop_timer_button = QPushButton("⏹️ 停止")
        self.stop_timer_button.setFixedWidth(70)
        self.stop_timer_button.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                padding: 4px 8px;
                background-color: #5a4a3a;
                border: 1px solid #6a5a4a;
                border-radius: 4px;
                color: #ffc;
            }
            QPushButton:hover {
                background-color: #6a5a4a;
            }
        """)
        self.stop_timer_button.clicked.connect(self._stop_timeout)
        project_info_layout.addWidget(self.stop_timer_button)

        layout.addLayout(project_info_layout)

        # 反馈区域
        self.feedback_group = QGroupBox("💬 反馈")
        feedback_layout = QVBoxLayout(self.feedback_group)
        feedback_layout.setSpacing(10)

        # 说明标签
        self.description_label = QLabel(self.prompt)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("descriptionLabel")
        feedback_layout.addWidget(self.description_label)

        # 解决方案选项区域（垂直布局，每个选项单独一行）
        if self.options:
            self.options_group = QGroupBox("💡 快速选择（点击追加到输入框，再次点击取消选择）")
            options_layout = QVBoxLayout(self.options_group)
            options_layout.setSpacing(6)

            # 选项按钮样式（未选中）
            self._option_style_normal = """
                QPushButton {
                    text-align: left;
                    padding: 8px 14px;
                    background-color: #2a4a3a;
                    border: 1px solid #3a6a4a;
                    border-radius: 8px;
                    color: #9fc;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #3a5a4a;
                    border-color: #4a7a5a;
                    color: #bfe;
                }
                QPushButton:pressed {
                    background-color: #1a3a2a;
                }
            """
            # 选项按钮样式（已选中）
            self._option_style_selected = """
                QPushButton {
                    text-align: left;
                    padding: 8px 14px;
                    background-color: #1a5a3a;
                    border: 2px solid #4aaa6a;
                    border-radius: 8px;
                    color: #bfe;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2a6a4a;
                    border-color: #5aba7a;
                }
                QPushButton:pressed {
                    background-color: #0a4a2a;
                }
            """

            self.option_buttons = []
            for i, option in enumerate(self.options):
                btn = QPushButton(f"  {option}")
                btn.setToolTip(f"点击选择: {option}")
                btn.setStyleSheet(self._option_style_normal)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn.clicked.connect(lambda checked, opt=option, b=btn: self._toggle_option(opt, b))
                options_layout.addWidget(btn)
                self.option_buttons.append(btn)

            feedback_layout.addWidget(self.options_group)

        # 反馈文本输入区
        self.feedback_text = FeedbackTextEdit()
        font_metrics = self.feedback_text.fontMetrics()
        row_height = font_metrics.height()
        padding = self.feedback_text.contentsMargins().top() + self.feedback_text.contentsMargins().bottom() + 5
        self.feedback_text.setMinimumHeight(5 * row_height + padding)
        self.feedback_text.setPlaceholderText(
            "✏️ 在此输入反馈内容...\n\n"
            "支持文件引用语法：\n"
            "  @src/views/example/index.vue - 引用整个文件\n"
            "  @src/views/example/index.vue#61 - 引用特定行\n"
            "  @src/views/example/index.vue#61-70 - 引用行范围\n\n"
            "快捷键: Ctrl+Enter 发送"
        )
        self.feedback_text.textChanged.connect(self._on_feedback_text_changed)
        feedback_layout.addWidget(self.feedback_text)

        # 引用预览区域
        self.reference_preview = QLabel()
        self.reference_preview.setWordWrap(True)
        self.reference_preview.setStyleSheet("""
            font-size: 11px;
            color: #888;
            padding: 4px 8px;
            background-color: #2a2a2a;
            border-radius: 4px;
            border-left: 3px solid #4a9eff;
        """)
        self.reference_preview.setVisible(False)
        feedback_layout.addWidget(self.reference_preview)

        # 图片区域（精简版：直接显示在反馈区内）
        image_bar_layout = QHBoxLayout()
        image_bar_layout.setSpacing(8)

        self.image_info_label = QLabel("")
        self.image_info_label.setStyleSheet("font-size: 12px; color: #888;")
        image_bar_layout.addWidget(self.image_info_label)

        image_bar_layout.addStretch()

        select_image_btn = QPushButton("📂 选择图片")
        select_image_btn.setFixedHeight(28)
        select_image_btn.setStyleSheet("""
            QPushButton { font-size: 11px; padding: 2px 10px; }
        """)
        select_image_btn.clicked.connect(self._select_image_file)
        image_bar_layout.addWidget(select_image_btn)

        clear_image_btn = QPushButton("🗑️")
        clear_image_btn.setFixedSize(28, 28)
        clear_image_btn.setToolTip("清除所有图片")
        clear_image_btn.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                padding: 2px;
                background-color: #5a3a3a;
                border: 1px solid #6a4a4a;
            }
            QPushButton:hover { background-color: #6a4a4a; }
        """)
        clear_image_btn.clicked.connect(self._clear_images)
        image_bar_layout.addWidget(clear_image_btn)

        feedback_layout.addLayout(image_bar_layout)

        # 图片提示
        self.image_hint_label = QLabel("💡 在输入框中 Ctrl+V 可直接粘贴截图，也可拖放图片文件")
        self.image_hint_label.setStyleSheet("font-size: 11px; color: #666; padding: 2px 0;")
        feedback_layout.addWidget(self.image_hint_label)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        submit_button = QPushButton("✉️ 发送反馈 (Ctrl+Enter)")
        submit_button.setObjectName("primaryButton")
        submit_button.clicked.connect(self._submit_feedback)

        end_button = QPushButton("✓ 结束")
        end_button.clicked.connect(self._end_feedback)

        button_layout.addStretch()
        button_layout.addWidget(end_button)
        button_layout.addWidget(submit_button)

        feedback_layout.addLayout(button_layout)

        layout.addWidget(self.feedback_group)

        # 底部信息
        contact_label = QLabel('💡 需要改进？联系 Fábio Ferreira <a href="https://x.com/fabiomlferreira">X.com</a> 或访问 <a href="https://dotcursorrules.com/">dotcursorrules.com</a>')
        contact_label.setOpenExternalLinks(True)
        contact_label.setAlignment(Qt.AlignCenter)
        contact_label.setStyleSheet("font-size: 10px; color: #666; padding: 8px;")
        layout.addWidget(contact_label)

    def _setup_timeout_timer(self):
        """设置超时计时器"""
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self._update_timeout_display)
        self.timeout_timer.start(1000)
        self._update_timeout_display()

    def _update_timeout_display(self):
        """更新超时倒计时显示（仅在样式状态变化时更新样式）"""
        elapsed = time.time() - self.start_time
        remaining = max(0, self.timeout_seconds - elapsed)

        minutes = int(remaining // 60)
        seconds = int(remaining % 60)

        if remaining <= 0:
            self.timeout_timer.stop()
            self._trigger_timeout()
            return

        # 只更新文本，样式仅在阈值变化时设置
        self.timeout_label.setText(f"⏱️ {minutes:02d}:{seconds:02d}")

        if remaining <= 60:
            target_style = "danger"
        elif remaining <= 120:
            target_style = "warning"
        else:
            target_style = "normal"

        if self._current_timeout_style != target_style:
            self._current_timeout_style = target_style
            style_map = {
                "normal": self._TIMEOUT_STYLE_NORMAL,
                "warning": self._TIMEOUT_STYLE_WARNING,
                "danger": self._TIMEOUT_STYLE_DANGER,
            }
            self.timeout_label.setStyleSheet(style_map[target_style])

    def _reset_timeout(self):
        """重新计时"""
        self.start_time = time.time()
        self._current_timeout_style = None  # 重置样式缓存
        if not self.timeout_timer.isActive():
            self.timeout_timer.start(1000)
            self.stop_timer_button.setText("⏹️ 停止")
            self.stop_timer_button.setStyleSheet("""
                QPushButton {
                    font-size: 11px;
                    padding: 4px 8px;
                    background-color: #5a4a3a;
                    border: 1px solid #6a5a4a;
                    border-radius: 4px;
                    color: #ffc;
                }
                QPushButton:hover {
                    background-color: #6a5a4a;
                }
            """)
        self._update_timeout_display()

    def _stop_timeout(self):
        """停止/恢复计时"""
        if self.timeout_timer.isActive():
            self.timeout_timer.stop()
            self.timeout_label.setText("⏸️ 已暂停")
            self._current_timeout_style = "paused"
            self.timeout_label.setStyleSheet(self._TIMEOUT_STYLE_PAUSED)
            self.stop_timer_button.setText("▶️ 恢复")
            self.stop_timer_button.setStyleSheet("""
                QPushButton {
                    font-size: 11px;
                    padding: 4px 8px;
                    background-color: #3a5a3a;
                    border: 1px solid #4a6a4a;
                    border-radius: 4px;
                    color: #cfc;
                }
                QPushButton:hover {
                    background-color: #4a6a4a;
                }
            """)
        else:
            self.start_time = time.time()
            self._current_timeout_style = None
            self.timeout_timer.start(1000)
            self.stop_timer_button.setText("⏹️ 停止")
            self.stop_timer_button.setStyleSheet("""
                QPushButton {
                    font-size: 11px;
                    padding: 4px 8px;
                    background-color: #5a4a3a;
                    border: 1px solid #6a5a4a;
                    border-radius: 4px;
                    color: #ffc;
                }
                QPushButton:hover {
                    background-color: #6a5a4a;
                }
            """)
            self._update_timeout_display()

    def _trigger_timeout(self):
        """超时触发，自动提交以保持会话活跃"""
        self.timeout_triggered = True
        self.feedback_result = FeedbackResult(
            logs="",
            interactive_feedback="[会话保持] 等待用户输入中...",
            image_paths=[],
            selected_options=[],
            timeout_triggered=True,
        )
        self.close()

    def _add_image_from_pixmap(self, pixmap: QPixmap, source: str):
        """从 QPixmap 添加图片（保存临时文件并记录路径）"""
        if pixmap.isNull():
            return

        # 确定图片路径
        if source and os.path.exists(source):
            image_path = source
        else:
            # 粘贴/拖放的图片数据，保存为临时文件
            temp_dir = tempfile.gettempdir()
            self.temp_image_counter += 1
            image_path = os.path.join(
                temp_dir,
                f"mcp_feedback_{os.getpid()}_{self.temp_image_counter}.png"
            )
            pixmap.save(image_path, "PNG")

        # 避免重复
        if image_path not in self.image_paths:
            self.image_paths.append(image_path)
            self._update_image_display()

    def _select_image_file(self):
        """通过文件对话框选择图片"""
        initial_dir = self.project_directory
        if self.current_file and os.path.exists(self.current_file):
            if os.path.isfile(self.current_file):
                initial_dir = os.path.dirname(self.current_file)
            else:
                initial_dir = self.current_file

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片（可多选）",
            initial_dir,
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)"
        )
        for file_path in files:
            if file_path and file_path not in self.image_paths:
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    self.image_paths.append(file_path)
        if files:
            self._update_image_display()

    def _clear_images(self):
        """清除所有图片"""
        self.image_paths.clear()
        self.temp_image_counter = 0
        self._update_image_display()

    def _update_image_display(self):
        """更新图片状态显示"""
        count = len(self.image_paths)
        if count > 0:
            names = [os.path.basename(p) for p in self.image_paths]
            self.image_info_label.setText(f"🖼️ 已添加 {count} 张图片: {', '.join(names)}")
            self.image_info_label.setStyleSheet("font-size: 12px; color: #4a9eff;")
            self.image_hint_label.setVisible(False)
        else:
            self.image_info_label.setText("")
            self.image_info_label.setStyleSheet("font-size: 12px; color: #888;")
            self.image_hint_label.setVisible(True)

    def _toggle_option(self, option: str, btn: QPushButton):
        """切换选项的选中状态（追加/移除，不覆盖输入框内容）"""
        if option in self.selected_options:
            # 取消选中
            self.selected_options.remove(option)
            btn.setStyleSheet(self._option_style_normal)
            btn.setText(f"  {option}")
        else:
            # 选中
            self.selected_options.append(option)
            btn.setStyleSheet(self._option_style_selected)
            btn.setText(f"✔ {option}")

    def _on_feedback_text_changed(self):
        """反馈文本变化时，更新引用预览"""
        feedback_text = self.feedback_text.toPlainText()
        references = parse_file_references(feedback_text, self.project_directory)

        if references:
            preview_lines = []
            for file_path, start_line, end_line in references:
                try:
                    rel_path = os.path.relpath(file_path, self.project_directory).replace('\\', '/')
                except ValueError:
                    rel_path = os.path.basename(file_path)

                if start_line is None:
                    preview_lines.append(f"📄 {rel_path}")
                elif end_line == start_line:
                    preview_lines.append(f"📄 {rel_path}#{start_line}")
                else:
                    preview_lines.append(f"📄 {rel_path}#{start_line}-{end_line}")

            preview_text = "检测到引用: " + ", ".join(preview_lines)
            self.reference_preview.setText(preview_text)
            self.reference_preview.setVisible(True)
        else:
            self.reference_preview.setVisible(False)

    def _submit_feedback(self):
        """提交反馈"""
        feedback_text = self.feedback_text.toPlainText().strip()

        # 展开文件引用
        expanded_text = expand_file_references(feedback_text, self.project_directory)

        # 如果有选中的选项，追加到反馈中
        if self.selected_options:
            options_info = "\n".join([f"  - {opt}" for opt in self.selected_options])
            if expanded_text:
                expanded_text = f"[选择的方案:]\n{options_info}\n\n{expanded_text}"
            else:
                expanded_text = f"[选择的方案:]\n{options_info}"

        # 如果有图片，追加图片路径信息
        if self.image_paths:
            images_info = "\n".join([f"  - {p}" for p in self.image_paths])
            if expanded_text:
                expanded_text += f"\n\n[附加图片 ({len(self.image_paths)}张):]\n{images_info}"
            else:
                expanded_text = f"[附加图片 ({len(self.image_paths)}张):]\n{images_info}"

        self.feedback_result = FeedbackResult(
            logs="",
            interactive_feedback=expanded_text,
            image_paths=self.image_paths.copy(),
            selected_options=self.selected_options.copy(),
            timeout_triggered=False,
        )
        self.close()

    def _end_feedback(self):
        """结束反馈，清理所有临时图片"""
        self._cleanup_temp_images(keep_none=True)
        self.feedback_text.setPlainText("结束")
        self._submit_feedback()

    def closeEvent(self, event):
        self.settings.beginGroup("MainWindow_General")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.endGroup()
        super().closeEvent(event)

    def _cleanup_temp_images(self, keep_none: bool = False):
        """清理临时图片文件

        参数:
            keep_none: 为 True 时清除所有临时图片，为 False 时保留提交中引用的
        """
        temp_dir = tempfile.gettempdir()

        # 确定需要保留的路径
        keep_paths = set()
        if not keep_none and self.feedback_result and self.feedback_result.get("image_paths"):
            keep_paths = set(self.feedback_result["image_paths"])

        # 清除所有 mcp_feedback_ 临时图片（包括历史会话的）
        try:
            for filename in os.listdir(temp_dir):
                if filename.startswith("mcp_feedback_") and filename.endswith(".png"):
                    full_path = os.path.join(temp_dir, filename)
                    if full_path not in keep_paths:
                        try:
                            os.remove(full_path)
                        except OSError:
                            pass
        except OSError:
            pass

    def run(self) -> FeedbackResult:
        self.show()
        QApplication.instance().exec()

        if not self.feedback_result:
            return FeedbackResult(
                logs="",
                interactive_feedback="",
                image_paths=[],
                selected_options=[],
                timeout_triggered=False,
            )

        return self.feedback_result


def get_project_settings_group(project_dir: str) -> str:
    basename = os.path.basename(os.path.normpath(project_dir))
    full_hash = hashlib.md5(project_dir.encode('utf-8')).hexdigest()[:8]
    return f"{basename}_{full_hash}"


def feedback_ui(project_directory: str, prompt: str, output_file: Optional[str] = None, current_file: Optional[str] = None, timeout_seconds: int = 600, options: Optional[List[str]] = None) -> Optional[FeedbackResult]:
    """启动反馈UI界面

    参数:
        project_directory: 项目目录路径
        prompt: 提示信息
        output_file: 输出文件路径
        current_file: 当前编辑的文件路径
        timeout_seconds: 超时时间（秒）
        options: 可选的解决方案列表
    """
    app = QApplication.instance() or QApplication()
    app.setPalette(get_dark_mode_palette(app))
    app.setStyle("Fusion")
    ui = FeedbackUI(project_directory, prompt, current_file, timeout_seconds, options)
    result = ui.run()

    if output_file and result:
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
        with open(output_file, "w") as f:
            json.dump(result, f)
        return None

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行反馈界面")
    parser.add_argument("--project-directory", default=os.getcwd(), help="项目目录路径")
    parser.add_argument("--prompt", default="我已经实现了您请求的更改。", help="显示给用户的提示")
    parser.add_argument("--output-file", help="保存反馈结果为 JSON 的路径")
    parser.add_argument("--current-file", help="当前编辑的文件路径")
    parser.add_argument("--timeout", type=int, default=600, help="超时时间（秒），默认600秒")
    parser.add_argument("--options", help="解决方案选项列表（JSON格式）")
    args = parser.parse_args()

    options = None
    if args.options:
        try:
            options = json.loads(args.options)
        except json.JSONDecodeError:
            pass

    result = feedback_ui(args.project_directory, args.prompt, args.output_file, args.current_file, args.timeout, options)
    if result:
        print(f"\n收到的反馈:\n{result['interactive_feedback']}")
    sys.exit(0)
