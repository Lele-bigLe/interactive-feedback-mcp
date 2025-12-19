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
from typing import Optional, TypedDict, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSettings
from PySide6.QtGui import (
    QIcon, QKeyEvent, QPalette, QColor, 
    QPixmap
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent

class FeedbackResult(TypedDict):
    logs: str  # 保留字段，但不再使用命令日志
    interactive_feedback: str
    image_path: str  # 保持兼容，存储第一张图片路径
    image_paths: List[str]  # 多图片路径列表
    context_files: List[str]  # 上下文文件路径列表
    timeout_triggered: bool  # 是否因超时触发重新调用

def set_dark_title_bar(widget: QWidget, dark_title_bar: bool) -> None:
    # Ensure we're on Windows
    if sys.platform != "win32":
        return

    from ctypes import windll, c_uint32, byref

    # Get Windows build number
    build_number = sys.getwindowsversion().build
    if build_number < 17763:  # Windows 10 1809 minimum
        return

    # Check if the widget's property already matches the setting
    dark_prop = widget.property("DarkTitleBar")
    if dark_prop is not None and dark_prop == dark_title_bar:
        return

    # Set the property (True if dark_title_bar != 0, False otherwise)
    widget.setProperty("DarkTitleBar", dark_title_bar)

    # Load dwmapi.dll and call DwmSetWindowAttribute
    dwmapi = windll.dwmapi
    hwnd = widget.winId()  # Get the window handle
    attribute = 20 if build_number >= 18985 else 19  # Use newer attribute for newer builds
    c_dark_title_bar = c_uint32(dark_title_bar)  # Convert to C-compatible uint32
    dwmapi.DwmSetWindowAttribute(hwnd, attribute, byref(c_dark_title_bar), 4)

    # HACK: Create a 1x1 pixel frameless window to force redraw
    temp_widget = QWidget(None, Qt.FramelessWindowHint)
    temp_widget.resize(1, 1)
    temp_widget.move(widget.pos())
    temp_widget.show()
    temp_widget.deleteLater()  # Safe deletion in Qt event loop

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
    """自定义文本编辑器，只接受纯文本粘贴"""
    def __init__(self, parent=None):
        super().__init__(parent)
        # 设置为纯文本模式
        self.setAcceptRichText(False)

    def insertFromMimeData(self, source):
        """重写粘贴方法，只接受纯文本"""
        if source.hasText():
            # 只插入纯文本，忽略任何格式
            self.insertPlainText(source.text())
        else:
            # 如果没有文本，调用父类方法
            super().insertFromMimeData(source)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
            # Find the parent FeedbackUI instance and call submit
            parent = self.parent()
            while parent and not isinstance(parent, FeedbackUI):
                parent = parent.parent()
            if parent:
                parent._submit_feedback()
        else:
            super().keyPressEvent(event)

class ImageLabel(QLabel):
    """支持粘贴和拖放的图片标签"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.image_loaded_callback = None  # 回调函数，用于通知父组件图片已加载

    def set_image_loaded_callback(self, callback):
        """设置图片加载后的回调函数"""
        self.image_loaded_callback = callback

    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入事件"""
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        """拖放事件"""
        if event.mimeData().hasImage():
            # 从拖拽中获取图片
            image_data = event.mimeData().imageData()
            if image_data:
                # 转换为QPixmap
                from PySide6.QtGui import QImage
                if isinstance(image_data, QImage):
                    pixmap = QPixmap.fromImage(image_data)
                elif isinstance(image_data, QPixmap):
                    pixmap = image_data
                else:
                    pixmap = QPixmap()
                if not pixmap.isNull():
                    self._load_pixmap(pixmap, "拖放的图片")
        elif event.mimeData().hasUrls():
            # 拖放文件
            urls = event.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()
                if file_path:
                    self._load_from_file(file_path)
        event.acceptProposedAction()

    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件：支持 Ctrl+V 粘贴"""
        if event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
            self._paste_from_clipboard()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """鼠标点击事件：点击后获得焦点，支持粘贴"""
        self.setFocus()
        super().mousePressEvent(event)

    def _paste_from_clipboard(self):
        """从剪贴板粘贴图片"""
        clipboard = QApplication.clipboard()
        if clipboard.mimeData().hasImage():
            pixmap = clipboard.pixmap()
            if not pixmap.isNull():
                self._load_pixmap(pixmap, "粘贴的图片")
        elif clipboard.mimeData().hasUrls():
            # 剪贴板中有文件路径
            urls = clipboard.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()
                if file_path and os.path.exists(file_path):
                    self._load_from_file(file_path)

    def _load_pixmap(self, pixmap: QPixmap, source: str):
        """加载QPixmap图片"""
        if not pixmap.isNull():
            if self.image_loaded_callback:
                self.image_loaded_callback(pixmap, source)
            else:
                # 如果没有回调，直接显示
                self._update_display(pixmap)

    def _load_from_file(self, file_path: str):
        """从文件加载图片"""
        if os.path.exists(file_path):
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                if self.image_loaded_callback:
                    self.image_loaded_callback(pixmap, file_path)
                else:
                    self._update_display(pixmap)

    def _update_display(self, pixmap: QPixmap):
        """更新显示"""
        label_width = self.width() if self.width() > 0 else 400
        label_height = self.height() if self.height() > 0 else 300
        scaled_pixmap = pixmap.scaled(
            label_width,
            label_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.setPixmap(scaled_pixmap)
        self.setText("")

class ImageDropArea(QTextEdit):
    """支持拖放和粘贴的多图片区域"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.image_paths: List[str] = []
        self.image_added_callback = None  # 图片添加回调
        self.setPlaceholderText("🖼️ 拖放图片到这里，或按 Ctrl+V 粘贴")
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入事件"""
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        """拖放事件"""
        if event.mimeData().hasImage():
            # 拖放的是图片数据
            image_data = event.mimeData().imageData()
            if image_data:
                from PySide6.QtGui import QImage
                if isinstance(image_data, QImage):
                    pixmap = QPixmap.fromImage(image_data)
                elif isinstance(image_data, QPixmap):
                    pixmap = image_data
                else:
                    pixmap = QPixmap()
                if not pixmap.isNull() and self.image_added_callback:
                    self.image_added_callback(pixmap, "拖放的图片")
        elif event.mimeData().hasUrls():
            # 拖放的是文件
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path and os.path.exists(file_path):
                    # 检查是否是图片文件
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                        pixmap = QPixmap(file_path)
                        if not pixmap.isNull() and self.image_added_callback:
                            self.image_added_callback(pixmap, file_path)
        event.acceptProposedAction()
    
    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件：支持 Ctrl+V 粘贴"""
        if event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
            self._paste_from_clipboard()
        else:
            super().keyPressEvent(event)
    
    def mousePressEvent(self, event):
        """鼠标点击事件：点击后获得焦点"""
        self.setFocus()
        super().mousePressEvent(event)
    
    def _paste_from_clipboard(self):
        """从剪贴板粘贴图片"""
        clipboard = QApplication.clipboard()
        if clipboard.mimeData().hasImage():
            pixmap = clipboard.pixmap()
            if not pixmap.isNull() and self.image_added_callback:
                self.image_added_callback(pixmap, "粘贴的图片")
        elif clipboard.mimeData().hasUrls():
            for url in clipboard.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path and os.path.exists(file_path):
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                        pixmap = QPixmap(file_path)
                        if not pixmap.isNull() and self.image_added_callback:
                            self.image_added_callback(pixmap, file_path)
    
    def update_display(self, image_paths: List[str]):
        """更新显示的图片列表"""
        self.image_paths = image_paths
        if image_paths:
            display_text = "\n".join([f"🖼️ {os.path.basename(p) if os.path.exists(p) else p}" for p in image_paths])
            self.setPlainText(display_text)
            self.setStyleSheet("""
                border: 2px solid #42a2da; 
                border-radius: 8px;
                background-color: #2a2a2a; 
                color: #fff;
                font-size: 13px;
                padding: 8px;
            """)
        else:
            self.clear()
            self.setPlaceholderText("🖼️ 拖放图片到这里，或按 Ctrl+V 粘贴\n支持多张图片")
            self.setStyleSheet("""
                border: 2px dashed #555; 
                border-radius: 8px;
                background-color: #2a2a2a; 
                color: #888;
                font-size: 13px;
                padding: 8px;
            """)

class ContextFileList(QTextEdit):
    """支持拖放的上下文文件列表"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setReadOnly(True)
        self.files: List[str] = []
        self.files_added_callback = None  # 文件添加回调
        self.setPlaceholderText("拖放文件/文件夹到这里")
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        """拖放事件"""
        if event.mimeData().hasUrls():
            new_files = []
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path and os.path.exists(file_path):
                    # 如果是文件夹，获取其中所有文件
                    if os.path.isdir(file_path):
                        new_files.append(file_path)
                    else:
                        new_files.append(file_path)
            
            if new_files and self.files_added_callback:
                self.files_added_callback(new_files)
            
            event.acceptProposedAction()
    
    def update_display(self, files: List[str]):
        """更新显示的文件列表"""
        self.files = files
        if files:
            display_text = "\n".join([f"📄 {f}" if os.path.isfile(f) else f"📁 {f}" for f in files])
            self.setPlainText(display_text)
        else:
            self.clear()
            self.setPlaceholderText("拖放文件/文件夹到这里，或使用上方按钮添加\n支持多选")

class FeedbackUI(QMainWindow):
    def __init__(self, project_directory: str, prompt: str, current_file: Optional[str] = None, timeout_seconds: int = 600, options: Optional[List[str]] = None):
        super().__init__()
        self.project_directory = project_directory
        self.prompt = prompt
        self.current_file = current_file  # 当前编辑文件路径
        self.timeout_seconds = timeout_seconds  # 超时时间
        self.start_time = time.time()  # 记录开始时间
        self.timeout_triggered = False  # 超时标志
        self.options = options or []  # 解决方案选项列表

        self.feedback_result = None
        self.image_paths: List[str] = []  # 多图片路径列表
        self.image_pixmaps: List[QPixmap] = []  # 存储原始图片列表
        self.context_files: List[str] = []  # 上下文文件路径列表
        self.temp_image_counter = 0  # 临时图片计数器

        # 获取项目名称（用于显示）
        self.project_name = os.path.basename(os.path.normpath(project_directory))
        self.setWindowTitle(f"Interactive Feedback - [{self.project_name}]")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "images", "feedback.png")
        self.setWindowIcon(QIcon(icon_path))
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        
        self.settings = QSettings("InteractiveFeedbackMCP", "InteractiveFeedbackMCP")
        
        # Load general UI settings for the main window (geometry, state)
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
        self.settings.endGroup() # End "MainWindow_General" group
        
        # Load project-specific settings
        self.project_group_name = get_project_settings_group(self.project_directory)
        self.settings.beginGroup(self.project_group_name)
        image_section_visible = self.settings.value("imageSectionVisible", False, type=bool)  # 图片区域可见性
        context_section_visible = self.settings.value("contextSectionVisible", False, type=bool)  # 上下文区域可见性
        self.settings.endGroup() # End project-specific group

        self._create_ui()
        
        # Set image section visibility AFTER _create_ui has created relevant widgets
        self.image_group.setVisible(image_section_visible)
        if image_section_visible:
            self.toggle_image_button.setText("➖ 图片")
        else:
            self.toggle_image_button.setText("🖼️ 图片")
        
        # Set context section visibility AFTER _create_ui has created relevant widgets
        self.context_group.setVisible(context_section_visible)
        if context_section_visible:
            self.toggle_context_button.setText("➖ 上下文引用")
        else:
            self.toggle_context_button.setText("📎 上下文引用")

        set_dark_title_bar(self, True)

        # 启动超时计时器
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
            
            /* 切换按钮特殊样式 */
            QPushButton#toggleButton {
                background-color: #2a4a6a;
                border: 1px solid #3a5a7a;
                text-align: left;
                padding-left: 12px;
            }
            QPushButton#toggleButton:hover {
                background-color: #3a5a8a;
            }
            
            /* 主要操作按钮 */
            QPushButton#primaryButton {
                background-color: #2a82da;
                border: 1px solid #3a92ea;
            }
            QPushButton#primaryButton:hover {
                background-color: #3a92ea;
            }
            
            /* 危险操作按钮 */
            QPushButton#dangerButton {
                background-color: #8a3a3a;
                border: 1px solid #9a4a4a;
            }
            QPushButton#dangerButton:hover {
                background-color: #9a4a4a;
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
            
            /* 输入框样式 */
            QLineEdit {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 8px 12px;
                color: #fff;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #2a82da;
            }
            QLineEdit::placeholder {
                color: #888;
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
            
            /* 复选框样式 */
            QCheckBox {
                color: #ccc;
                font-size: 13px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #555;
                background-color: #3a3a3a;
            }
            QCheckBox::indicator:checked {
                background-color: #2a82da;
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
        layout.setSpacing(12)  # 增加组件间距
        layout.setContentsMargins(16, 16, 16, 16)  # 增加边距

        # 全局样式表
        self._apply_styles()

        # 项目标识和超时计时器区域
        project_info_layout = QHBoxLayout()
        project_info_layout.setSpacing(12)
        
        # 项目名称标签
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
        self.timeout_label.setStyleSheet("""
            font-size: 12px;
            color: #aaa;
            padding: 4px 8px;
            background-color: #333;
            border-radius: 4px;
        """)
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

        # Feedback section with adjusted height
        self.feedback_group = QGroupBox("💬 反馈")
        feedback_layout = QVBoxLayout(self.feedback_group)
        feedback_layout.setSpacing(10)

        # Short description label (from self.prompt)
        self.description_label = QLabel(self.prompt)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("descriptionLabel")
        feedback_layout.addWidget(self.description_label)

        # 可选区域按钮行（水平排列）
        toggle_layout = QHBoxLayout()
        toggle_layout.setSpacing(8)
        
        # Toggle Image Section Button
        self.toggle_image_button = QPushButton("🖼️ 图片")
        self.toggle_image_button.setObjectName("toggleButton")
        self.toggle_image_button.clicked.connect(self._toggle_image_section)
        toggle_layout.addWidget(self.toggle_image_button)
        
        # Toggle Context Section Button
        self.toggle_context_button = QPushButton("📎 上下文引用")
        self.toggle_context_button.setObjectName("toggleButton")
        self.toggle_context_button.clicked.connect(self._toggle_context_section)
        toggle_layout.addWidget(self.toggle_context_button)
        
        toggle_layout.addStretch()
        feedback_layout.addLayout(toggle_layout)

        # 图片区域
        self.image_group = QGroupBox("🖼️ 图片（可选，支持多张）")
        image_layout = QVBoxLayout(self.image_group)
        image_layout.setSpacing(8)
        
        # 图片操作按钮行
        image_btn_layout = QHBoxLayout()
        image_btn_layout.setSpacing(6)
        
        select_image_button = QPushButton("📂 选择图片")
        select_image_button.clicked.connect(self._select_image_file)
        paste_image_button = QPushButton("📋 粘贴")
        paste_image_button.setObjectName("primaryButton")
        paste_image_button.clicked.connect(self._paste_image)
        clear_image_button = QPushButton("🗑️ 清除全部")
        clear_image_button.setObjectName("dangerButton")
        clear_image_button.clicked.connect(self._clear_image)
        
        image_btn_layout.addWidget(select_image_button)
        image_btn_layout.addWidget(paste_image_button)
        image_btn_layout.addStretch()
        image_btn_layout.addWidget(clear_image_button)
        image_layout.addLayout(image_btn_layout)
        
        # 图片列表（支持粘贴和拖放）
        self.image_list = ImageDropArea()
        self.image_list.setMinimumHeight(100)
        self.image_list.setMaximumHeight(200)
        self.image_list.setStyleSheet("""
            border: 2px dashed #555; 
            border-radius: 8px;
            background-color: #2a2a2a; 
            color: #888;
            font-size: 13px;
            padding: 8px;
        """)
        self.image_list.setPlaceholderText("🖼️ 拖放图片到这里，或按 Ctrl+V 粘贴\n支持多张图片")
        self.image_list.image_added_callback = self._on_image_added
        image_layout.addWidget(self.image_list)
        
        self.image_group.setVisible(False)
        feedback_layout.addWidget(self.image_group)

        # 上下文文件区域
        self.context_group = QGroupBox("📎 上下文引用（可选）")
        context_layout = QVBoxLayout(self.context_group)
        context_layout.setSpacing(8)
        
        # 上下文文件操作按钮行
        context_btn_layout = QHBoxLayout()
        context_btn_layout.setSpacing(6)
        add_file_button = QPushButton("📄 添加文件")
        add_file_button.clicked.connect(self._add_context_file)
        add_folder_button = QPushButton("📁 添加文件夹")
        add_folder_button.clicked.connect(self._add_context_folder)
        clear_context_button = QPushButton("🗑️")
        clear_context_button.setObjectName("dangerButton")
        clear_context_button.setFixedWidth(40)
        clear_context_button.clicked.connect(self._clear_context_files)
        
        context_btn_layout.addWidget(add_file_button)
        context_btn_layout.addWidget(add_folder_button)
        context_btn_layout.addStretch()
        context_btn_layout.addWidget(clear_context_button)
        context_layout.addLayout(context_btn_layout)
        
        # 上下文文件列表（支持拖放）
        self.context_list = ContextFileList()
        self.context_list.setMinimumHeight(80)
        self.context_list.setMaximumHeight(150)
        self.context_list.setStyleSheet("""
            border: 2px dashed #555; 
            border-radius: 8px;
            background-color: #2a2a2a; 
            color: #888;
            font-size: 13px;
            padding: 8px;
        """)
        self.context_list.setPlaceholderText("📂 拖放文件/文件夹到这里\n或使用上方按钮添加")
        self.context_list.files_added_callback = self._on_context_files_added
        context_layout.addWidget(self.context_list)
        
        self.context_group.setVisible(False)
        feedback_layout.addWidget(self.context_group)

        # 解决方案选项区域（如果有选项的话）
        if self.options:
            self.options_group = QGroupBox("💡 快速选择（点击填充到输入框）")
            options_layout = QHBoxLayout(self.options_group)  # 改为水平布局
            options_layout.setSpacing(8)
            
            self.option_buttons = []
            for i, option in enumerate(self.options):
                btn = QPushButton(f"{option}")
                btn.setToolTip(f"点击选择: {option}")
                btn.setStyleSheet("""
                    QPushButton {
                        text-align: center;
                        padding: 8px 16px;
                        background-color: #2a4a3a;
                        border: 1px solid #3a6a4a;
                        border-radius: 16px;
                        color: #9fc;
                        font-size: 12px;
                        min-width: 80px;
                    }
                    QPushButton:hover {
                        background-color: #3a5a4a;
                        border-color: #4a7a5a;
                        color: #bfe;
                    }
                    QPushButton:pressed {
                        background-color: #1a3a2a;
                    }
                """)
                btn.clicked.connect(lambda checked, opt=option: self._select_option(opt))
                options_layout.addWidget(btn)
                self.option_buttons.append(btn)
            
            options_layout.addStretch()  # 添加弹性空间
            feedback_layout.addWidget(self.options_group)

        # 反馈文本输入区
        self.feedback_text = FeedbackTextEdit()
        font_metrics = self.feedback_text.fontMetrics()
        row_height = font_metrics.height()
        padding = self.feedback_text.contentsMargins().top() + self.feedback_text.contentsMargins().bottom() + 5
        self.feedback_text.setMinimumHeight(5 * row_height + padding)
        self.feedback_text.setPlaceholderText("✏️ 在此输入您的反馈...\n\n快捷键: Ctrl+Enter 发送")
        feedback_layout.addWidget(self.feedback_text)
        
        # 按钮布局：发送反馈和结束按钮
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

        # Add widgets in a specific order
        layout.addWidget(self.feedback_group)

        # Credits/Contact Label
        contact_label = QLabel('💡 需要改进？联系 Fábio Ferreira <a href="https://x.com/fabiomlferreira">X.com</a> 或访问 <a href="https://dotcursorrules.com/">dotcursorrules.com</a>')
        contact_label.setOpenExternalLinks(True)
        contact_label.setAlignment(Qt.AlignCenter)
        contact_label.setStyleSheet("font-size: 10px; color: #666; padding: 8px;")
        layout.addWidget(contact_label)

    def _setup_timeout_timer(self):
        """设置超时计时器"""
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self._update_timeout_display)
        self.timeout_timer.start(1000)  # 每秒更新一次
        self._update_timeout_display()

    def _update_timeout_display(self):
        """更新超时倒计时显示"""
        elapsed = time.time() - self.start_time
        remaining = max(0, self.timeout_seconds - elapsed)
        
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        
        if remaining <= 0:
            # 超时，触发自动提交
            self.timeout_timer.stop()
            self._trigger_timeout()
        elif remaining <= 60:
            # 最后一分钟，显示红色警告
            self.timeout_label.setText(f"⏱️ {minutes:02d}:{seconds:02d}")
            self.timeout_label.setStyleSheet("""
                font-size: 12px;
                color: #ff6666;
                padding: 4px 8px;
                background-color: #4a2a2a;
                border-radius: 4px;
                font-weight: bold;
            """)
        elif remaining <= 120:
            # 两分钟内，显示橙色
            self.timeout_label.setText(f"⏱️ {minutes:02d}:{seconds:02d}")
            self.timeout_label.setStyleSheet("""
                font-size: 12px;
                color: #ffaa66;
                padding: 4px 8px;
                background-color: #4a3a2a;
                border-radius: 4px;
            """)
        else:
            self.timeout_label.setText(f"⏱️ {minutes:02d}:{seconds:02d}")
            self.timeout_label.setStyleSheet("""
                font-size: 12px;
                color: #aaa;
                padding: 4px 8px;
                background-color: #333;
                border-radius: 4px;
            """)

    def _reset_timeout(self):
        """重新计时"""
        self.start_time = time.time()
        # 如果计时器已停止，重新启动
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
            # 停止计时
            self.timeout_timer.stop()
            self.timeout_label.setText("⏸️ 已暂停")
            self.timeout_label.setStyleSheet("""
                font-size: 12px;
                color: #ffc;
                padding: 4px 8px;
                background-color: #5a4a3a;
                border-radius: 4px;
            """)
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
            # 恢复计时（重新开始计时）
            self.start_time = time.time()
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
            image_path="",
            image_paths=[],
            context_files=[],
            timeout_triggered=True,
        )
        self.close()

    def _adjust_window_height(self):
        """调整窗口高度以适应内容变化（保持宽度不变）"""
        # 保存当前宽度和高度
        current_width = self.width()
        current_height = self.height()
        
        # 先处理布局更新
        self.centralWidget().updateGeometry()
        QApplication.processEvents()
        
        # 使用 sizeHint 获取建议高度
        hint_height = self.centralWidget().sizeHint().height() + 40  # 添加一些边距
        
        # 设置窗口的最小和最大高度限制
        min_height = 300  # 最小高度
        max_height = QApplication.primaryScreen().geometry().height() - 100  # 留出任务栏空间
        
        # 计算新高度
        new_height = max(min_height, min(hint_height, max_height))
        
        # 如果高度变化不大，直接调整
        if abs(new_height - current_height) < 10:
            return
        
        # 使用定时器实现平滑动画效果
        self._animate_height(current_height, new_height, current_width)

    def _animate_height(self, start_height: int, end_height: int, width: int):
        """使用动画效果平滑调整窗口高度"""
        # 计算步数和每步的高度变化
        steps = 8
        height_diff = end_height - start_height
        step_size = height_diff / steps
        
        # 当前步数
        self._animation_step = 0
        self._animation_target = end_height
        self._animation_width = width
        self._animation_step_size = step_size
        self._animation_steps = steps
        self._animation_start = start_height
        
        # 创建动画定时器
        if not hasattr(self, '_height_animation_timer'):
            from PySide6.QtCore import QTimer
            self._height_animation_timer = QTimer()
            self._height_animation_timer.timeout.connect(self._animate_height_step)
        
        # 启动动画
        self._height_animation_timer.start(15)  # 约60fps

    def _animate_height_step(self):
        """动画步骤"""
        self._animation_step += 1
        
        if self._animation_step >= self._animation_steps:
            # 动画完成
            self._height_animation_timer.stop()
            self.resize(self._animation_width, self._animation_target)
            self.setMinimumWidth(400)
            self.setMaximumWidth(16777215)
            return
        
        # 使用缓动函数计算当前高度（ease-out效果）
        progress = self._animation_step / self._animation_steps
        eased_progress = 1 - (1 - progress) ** 2  # 二次缓出
        current_height = int(self._animation_start + (self._animation_target - self._animation_start) * eased_progress)
        
        self.resize(self._animation_width, current_height)

    def _toggle_image_section(self):
        """切换图片区域的显示/隐藏"""
        is_visible = self.image_group.isVisible()
        self.image_group.setVisible(not is_visible)
        if not is_visible:
            self.toggle_image_button.setText("➖ 图片")
        else:
            self.toggle_image_button.setText("🖼️ 图片")
        
        # 立即保存该项目的可见性状态
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("imageSectionVisible", self.image_group.isVisible())
        self.settings.endGroup()

        # 调整窗口高度
        self._adjust_window_height()

    def _toggle_context_section(self):
        """切换上下文引用区域的显示/隐藏"""
        is_visible = self.context_group.isVisible()
        self.context_group.setVisible(not is_visible)
        if not is_visible:
            self.toggle_context_button.setText("➖ 上下文引用")
        else:
            self.toggle_context_button.setText("📎 上下文引用")
        
        # 立即保存该项目的可见性状态
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("contextSectionVisible", self.context_group.isVisible())
        self.settings.endGroup()

        # 调整窗口高度
        self._adjust_window_height()

    def _select_option(self, option: str):
        """选择一个解决方案选项，填充到输入框但不自动提交"""
        self.feedback_text.setPlainText(f"[选择方案] {option}\n\n")
        # 将光标移动到末尾，方便用户追加内容
        cursor = self.feedback_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.feedback_text.setTextCursor(cursor)
        self.feedback_text.setFocus()

    def _get_file_dialog_initial_dir(self) -> str:
        """获取文件对话框的初始目录
        
        优先使用当前编辑文件所在目录，否则使用项目目录
        """
        if self.current_file and os.path.exists(self.current_file):
            # 如果是文件，返回其所在目录
            if os.path.isfile(self.current_file):
                return os.path.dirname(self.current_file)
            # 如果是目录，直接返回
            return self.current_file
        return self.project_directory

    def _add_context_file(self):
        """添加上下文文件"""
        # 优先使用当前文件所在目录，否则使用项目目录
        initial_dir = self._get_file_dialog_initial_dir()
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择文件",
            initial_dir,
            "所有文件 (*.*)"
        )
        if files:
            self._on_context_files_added(files)

    def _add_context_folder(self):
        """添加上下文文件夹"""
        initial_dir = self._get_file_dialog_initial_dir()
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择文件夹",
            initial_dir
        )
        if folder:
            self._on_context_files_added([folder])

    def _on_context_files_added(self, files: List[str]):
        """上下文文件添加回调"""
        for f in files:
            if f not in self.context_files:
                self.context_files.append(f)
        self.context_list.update_display(self.context_files)

    def _clear_context_files(self):
        """清除所有上下文文件"""
        self.context_files.clear()
        self.context_list.update_display(self.context_files)

    def _submit_feedback(self):
        feedback_text = self.feedback_text.toPlainText().strip()
        
        # 如果有图片，在反馈文本中添加图片信息
        if self.image_paths:
            images_info = "\n".join([f"  - {p}" for p in self.image_paths])
            if feedback_text:
                feedback_text += f"\n\n[图片 ({len(self.image_paths)}张):]\n{images_info}"
            else:
                feedback_text = f"[图片 ({len(self.image_paths)}张):]\n{images_info}"
        
        # 如果有上下文文件，添加到反馈中
        if self.context_files:
            context_info = "\n".join([f"  - {f}" for f in self.context_files])
            if feedback_text:
                feedback_text += f"\n\n[上下文文件:]\n{context_info}"
            else:
                feedback_text = f"[上下文文件:]\n{context_info}"
        
        self.feedback_result = FeedbackResult(
            logs="",
            interactive_feedback=feedback_text,
            image_path=self.image_paths[0] if self.image_paths else "",  # 保持兼容
            image_paths=self.image_paths.copy(),
            context_files=self.context_files.copy(),
            timeout_triggered=False,
        )
        self.close()

    def _end_feedback(self):
        # 自动填入"结束"并提交反馈
        self.feedback_text.setPlainText("结束")
        self._submit_feedback()

    def _select_image_file(self):
        """选择本地图片文件（支持多选）"""
        initial_dir = self._get_file_dialog_initial_dir()
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片文件（可多选）",
            initial_dir,
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)"
        )
        for file_path in files:
            if file_path:
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    self._on_image_added(pixmap, file_path)

    def _paste_image(self):
        """粘贴图片按钮处理"""
        self.image_list._paste_from_clipboard()

    def _on_image_added(self, pixmap: QPixmap, source: str):
        """图片添加回调函数"""
        if not pixmap.isNull():
            # 确定图片路径
            if source and os.path.exists(source):
                image_path = source
            else:
                # 如果是粘贴的图片，保存为临时文件
                temp_dir = tempfile.gettempdir()
                self.temp_image_counter += 1
                temp_image_path = os.path.join(temp_dir, f"mcp_feedback_image_{os.getpid()}_{self.temp_image_counter}.png")
                pixmap.save(temp_image_path, "PNG")
                image_path = temp_image_path
            
            # 添加到列表（避免重复）
            if image_path not in self.image_paths:
                self.image_paths.append(image_path)
                self.image_pixmaps.append(pixmap)
                self.image_list.update_display(self.image_paths)

    def _clear_image(self):
        """清除所有图片"""
        self.image_paths.clear()
        self.image_pixmaps.clear()
        self.temp_image_counter = 0
        self.image_list.update_display(self.image_paths)

    def closeEvent(self, event):
        # Save general UI settings for the main window (geometry, state)
        self.settings.beginGroup("MainWindow_General")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.endGroup()

        # Save project-specific section visibility
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("imageSectionVisible", self.image_group.isVisible())
        self.settings.setValue("contextSectionVisible", self.context_group.isVisible())
        self.settings.endGroup()

        super().closeEvent(event)

    def run(self) -> FeedbackResult:
        self.show()
        QApplication.instance().exec()

        if not self.feedback_result:
            return FeedbackResult(logs="", interactive_feedback="", image_path="", image_paths=[], context_files=[], timeout_triggered=False)

        return self.feedback_result

def get_project_settings_group(project_dir: str) -> str:
    # Create a safe, unique group name from the project directory path
    # Using only the last component + hash of full path to keep it somewhat readable but unique
    basename = os.path.basename(os.path.normpath(project_dir))
    full_hash = hashlib.md5(project_dir.encode('utf-8')).hexdigest()[:8]
    return f"{basename}_{full_hash}"

def feedback_ui(project_directory: str, prompt: str, output_file: Optional[str] = None, current_file: Optional[str] = None, timeout_seconds: int = 600, options: Optional[List[str]] = None) -> Optional[FeedbackResult]:
    """启动反馈UI界面
    
    参数:
        project_directory: 项目目录路径
        prompt: 提示信息
        output_file: 输出文件路径
        current_file: 当前编辑的文件路径（用于文件选择器初始目录）
        timeout_seconds: 超时时间（秒），超时后自动提交以保持会话活跃
        options: 可选的解决方案列表，供用户快速选择
    """
    app = QApplication.instance() or QApplication()
    app.setPalette(get_dark_mode_palette(app))
    app.setStyle("Fusion")
    ui = FeedbackUI(project_directory, prompt, current_file, timeout_seconds, options)
    result = ui.run()

    if output_file and result:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
        # Save the result to the output file
        with open(output_file, "w") as f:
            json.dump(result, f)
        return None

    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行反馈界面")
    parser.add_argument("--project-directory", default=os.getcwd(), help="运行命令的项目目录")
    parser.add_argument("--prompt", default="我已经实现了您请求的更改。", help="显示给用户的提示")
    parser.add_argument("--output-file", help="保存反馈结果为 JSON 的路径")
    parser.add_argument("--current-file", help="当前编辑的文件路径（用于文件选择器）")
    parser.add_argument("--timeout", type=int, default=600, help="超时时间（秒），默认600秒")
    parser.add_argument("--options", help="解决方案选项列表（JSON格式）")
    args = parser.parse_args()

    # 解析选项
    options = None
    if args.options:
        try:
            options = json.loads(args.options)
        except json.JSONDecodeError:
            pass

    result = feedback_ui(args.project_directory, args.prompt, args.output_file, args.current_file, args.timeout, options)
    if result:
        print(f"\n收集的日志: \n{result['logs']}")
        print(f"\n收到的反馈:\n{result['interactive_feedback']}")
    sys.exit(0)
