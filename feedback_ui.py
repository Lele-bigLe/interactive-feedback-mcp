# Interactive Feedback MCP UI
# Developed by Fábio Ferreira (https://x.com/fabiomlferreira)
# Inspired by/related to dotcursorrules.com (https://dotcursorrules.com/)
import os
import sys
import json
import psutil
import argparse
import subprocess
import threading
import hashlib
import tempfile
from typing import Optional, TypedDict, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QTextEdit, QGroupBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSettings
from PySide6.QtGui import (
    QTextCursor, QIcon, QKeyEvent, QFont, QFontDatabase, QPalette, QColor, 
    QPixmap, QClipboard
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent

class FeedbackResult(TypedDict):
    command_logs: str
    interactive_feedback: str
    image_path: str  # 图片路径或URL
    context_files: List[str]  # 上下文文件路径列表

class FeedbackConfig(TypedDict):
    run_command: str
    execute_automatically: bool

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

def kill_tree(process: subprocess.Popen):
    killed: list[psutil.Process] = []
    parent = psutil.Process(process.pid)
    for proc in parent.children(recursive=True):
        try:
            proc.kill()
            killed.append(proc)
        except psutil.Error:
            pass
    try:
        parent.kill()
    except psutil.Error:
        pass
    killed.append(parent)

    # Terminate any remaining processes
    for proc in killed:
        try:
            if proc.is_running():
                proc.terminate()
        except psutil.Error:
            pass

def get_user_environment() -> dict[str, str]:
    if sys.platform != "win32":
        return os.environ.copy()

    import ctypes
    from ctypes import wintypes

    # Load required DLLs
    advapi32 = ctypes.WinDLL("advapi32")
    userenv = ctypes.WinDLL("userenv")
    kernel32 = ctypes.WinDLL("kernel32")

    # Constants
    TOKEN_QUERY = 0x0008

    # Function prototypes
    OpenProcessToken = advapi32.OpenProcessToken
    OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    OpenProcessToken.restype = wintypes.BOOL

    CreateEnvironmentBlock = userenv.CreateEnvironmentBlock
    CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.BOOL]
    CreateEnvironmentBlock.restype = wintypes.BOOL

    DestroyEnvironmentBlock = userenv.DestroyEnvironmentBlock
    DestroyEnvironmentBlock.argtypes = [wintypes.LPVOID]
    DestroyEnvironmentBlock.restype = wintypes.BOOL

    GetCurrentProcess = kernel32.GetCurrentProcess
    GetCurrentProcess.argtypes = []
    GetCurrentProcess.restype = wintypes.HANDLE

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    # Get process token
    token = wintypes.HANDLE()
    if not OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise RuntimeError("Failed to open process token")

    try:
        # Create environment block
        environment = ctypes.c_void_p()
        if not CreateEnvironmentBlock(ctypes.byref(environment), token, False):
            raise RuntimeError("Failed to create environment block")

        try:
            # Convert environment block to list of strings
            result = {}
            env_ptr = ctypes.cast(environment, ctypes.POINTER(ctypes.c_wchar))
            offset = 0

            while True:
                # Get string at current offset
                current_string = ""
                while env_ptr[offset] != "\0":
                    current_string += env_ptr[offset]
                    offset += 1

                # Skip null terminator
                offset += 1

                # Break if we hit double null terminator
                if not current_string:
                    break

                equal_index = current_string.index("=")
                if equal_index == -1:
                    continue

                key = current_string[:equal_index]
                value = current_string[equal_index + 1:]
                result[key] = value

            return result

        finally:
            DestroyEnvironmentBlock(environment)

    finally:
        CloseHandle(token)

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

class LogSignals(QObject):
    append_log = Signal(str)

class FeedbackUI(QMainWindow):
    def __init__(self, project_directory: str, prompt: str):
        super().__init__()
        self.project_directory = project_directory
        self.prompt = prompt

        self.process: Optional[subprocess.Popen] = None
        self.log_buffer = []
        self.feedback_result = None
        self.log_signals = LogSignals()
        self.log_signals.append_log.connect(self._append_log)
        self.image_path = ""  # 存储图片路径或URL
        self.image_pixmap = None  # 存储原始图片
        self.context_files: List[str] = []  # 上下文文件路径列表
        self.temp_image_path = ""  # 临时图片文件路径

        self.setWindowTitle("Interactive Feedback MCP")
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
        
        # Load project-specific settings (command, auto-execute, command section visibility)
        self.project_group_name = get_project_settings_group(self.project_directory)
        self.settings.beginGroup(self.project_group_name)
        loaded_run_command = self.settings.value("run_command", "", type=str)
        loaded_execute_auto = self.settings.value("execute_automatically", False, type=bool)
        command_section_visible = self.settings.value("commandSectionVisible", False, type=bool)
        image_section_visible = self.settings.value("imageSectionVisible", False, type=bool)  # 图片区域可见性
        context_section_visible = self.settings.value("contextSectionVisible", False, type=bool)  # 上下文区域可见性
        self.settings.endGroup() # End project-specific group
        
        self.config: FeedbackConfig = {
            "run_command": loaded_run_command,
            "execute_automatically": loaded_execute_auto
        }

        self._create_ui() # self.config is used here to set initial values

        # Set command section visibility AFTER _create_ui has created relevant widgets
        self.command_group.setVisible(command_section_visible)
        if command_section_visible:
            self.toggle_command_button.setText("➖ 隐藏命令区域")
        else:
            self.toggle_command_button.setText("📂 显示命令区域")
        
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

        if self.config.get("execute_automatically", False):
            self._run_command()

    def _format_windows_path(self, path: str) -> str:
        if sys.platform == "win32":
            # Convert forward slashes to backslashes
            path = path.replace("/", "\\")
            # Capitalize drive letter if path starts with x:\
            if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
                path = path[0].upper() + path[1:]
        return path

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

        # Toggle Command Section Button
        self.toggle_command_button = QPushButton("📂 显示命令区域")
        self.toggle_command_button.setObjectName("toggleButton")
        self.toggle_command_button.clicked.connect(self._toggle_command_section)
        layout.addWidget(self.toggle_command_button)

        # Command section
        self.command_group = QGroupBox("命令")
        command_layout = QVBoxLayout(self.command_group)

        # Working directory label
        formatted_path = self._format_windows_path(self.project_directory)
        working_dir_label = QLabel(f"工作目录: {formatted_path}")
        command_layout.addWidget(working_dir_label)

        # Command input row
        command_input_layout = QHBoxLayout()
        self.command_entry = QLineEdit()
        self.command_entry.setText(self.config["run_command"])
        self.command_entry.returnPressed.connect(self._run_command)
        self.command_entry.textChanged.connect(self._update_config)
        self.run_button = QPushButton("运行(&R)")
        self.run_button.clicked.connect(self._run_command)

        command_input_layout.addWidget(self.command_entry)
        command_input_layout.addWidget(self.run_button)
        command_layout.addLayout(command_input_layout)

        # Auto-execute and save config row
        auto_layout = QHBoxLayout()
        self.auto_check = QCheckBox("下次运行时自动执行")
        self.auto_check.setChecked(self.config.get("execute_automatically", False))
        self.auto_check.stateChanged.connect(self._update_config)

        save_button = QPushButton("保存配置(&S)")
        save_button.clicked.connect(self._save_config)

        auto_layout.addWidget(self.auto_check)
        auto_layout.addStretch()
        auto_layout.addWidget(save_button)
        command_layout.addLayout(auto_layout)

        # Console section (now part of command_group)
        console_group = QGroupBox("控制台")
        console_layout_internal = QVBoxLayout(console_group)
        console_group.setMinimumHeight(200)

        # Log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        font = QFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        font.setPointSize(9)
        self.log_text.setFont(font)
        console_layout_internal.addWidget(self.log_text)

        # Clear button
        button_layout = QHBoxLayout()
        self.clear_button = QPushButton("清除(&C)")
        self.clear_button.clicked.connect(self.clear_logs)
        button_layout.addStretch()
        button_layout.addWidget(self.clear_button)
        console_layout_internal.addLayout(button_layout)
        
        command_layout.addWidget(console_group)

        self.command_group.setVisible(False) 
        layout.addWidget(self.command_group)

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
        self.image_group = QGroupBox("🖼️ 图片（可选）")
        image_layout = QVBoxLayout(self.image_group)
        image_layout.setSpacing(8)
        
        # 图片输入行
        image_input_layout = QHBoxLayout()
        image_input_layout.setSpacing(6)
        self.image_input = QLineEdit()
        self.image_input.setPlaceholderText("输入图片URL或本地文件路径...")
        self.image_input.textChanged.connect(self._on_image_path_changed)
        self.image_input.returnPressed.connect(self._load_image)
        
        select_image_button = QPushButton("📂 选择")
        select_image_button.clicked.connect(self._select_image_file)
        paste_image_button = QPushButton("📋 粘贴")
        paste_image_button.setObjectName("primaryButton")
        paste_image_button.clicked.connect(self._paste_image)
        clear_image_button = QPushButton("🗑️")
        clear_image_button.setObjectName("dangerButton")
        clear_image_button.setFixedWidth(40)
        clear_image_button.clicked.connect(self._clear_image)
        
        image_input_layout.addWidget(self.image_input, 1)
        image_input_layout.addWidget(select_image_button)
        image_input_layout.addWidget(paste_image_button)
        image_input_layout.addWidget(clear_image_button)
        image_layout.addLayout(image_input_layout)
        
        # 图片预览标签（支持粘贴和拖放）
        self.image_label = ImageLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(150)
        self.image_label.setMaximumHeight(300)
        self.image_label.setStyleSheet("""
            border: 2px dashed #555; 
            border-radius: 8px;
            background-color: #2a2a2a; 
            color: #888;
            font-size: 13px;
        """)
        self.image_label.setText("🖼️ 拖放图片到这里\n或按 Ctrl+V 粘贴")
        self.image_label.setScaledContents(False)
        self.image_label.set_image_loaded_callback(self._on_image_loaded)
        image_layout.addWidget(self.image_label)
        
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

    def _adjust_window_height(self):
        """调整窗口高度以适应内容变化（保持宽度不变）"""
        # 保存当前宽度
        current_width = self.width()
        
        # 先处理布局更新
        self.centralWidget().updateGeometry()
        QApplication.processEvents()
        
        # 使用 sizeHint 获取建议高度
        hint_height = self.centralWidget().sizeHint().height()
        
        # 设置窗口的最小和最大高度限制
        min_height = 300  # 最小高度
        max_height = QApplication.primaryScreen().geometry().height() - 100  # 留出任务栏空间
        
        # 计算新高度
        new_height = max(min_height, min(hint_height, max_height))
        
        # 设置固定宽度，只调整高度
        self.setFixedWidth(current_width)
        self.resize(current_width, new_height)
        
        # 恢复宽度可调整
        self.setMinimumWidth(400)
        self.setMaximumWidth(16777215)  # Qt 默认最大值

    def _toggle_command_section(self):
        is_visible = self.command_group.isVisible()
        self.command_group.setVisible(not is_visible)
        if not is_visible:
            self.toggle_command_button.setText("➖ 隐藏命令区域")
        else:
            self.toggle_command_button.setText("📂 显示命令区域")
        
        # Immediately save the visibility state for this project
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("commandSectionVisible", self.command_group.isVisible())
        self.settings.endGroup()

        # 调整窗口高度
        self._adjust_window_height()

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

    def _add_context_file(self):
        """添加上下文文件"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择文件",
            self.project_directory,
            "所有文件 (*.*)"
        )
        if files:
            self._on_context_files_added(files)

    def _add_context_folder(self):
        """添加上下文文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择文件夹",
            self.project_directory
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

    def _update_config(self):
        self.config["run_command"] = self.command_entry.text()
        self.config["execute_automatically"] = self.auto_check.isChecked()

    def _append_log(self, text: str):
        self.log_buffer.append(text)
        self.log_text.append(text.rstrip())
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)

    def _check_process_status(self):
        if self.process and self.process.poll() is not None:
            # Process has terminated
            exit_code = self.process.poll()
            self._append_log(f"\n进程已退出，退出码: {exit_code}\n")
            self.run_button.setText("运行(&R)")
            self.process = None
            self.activateWindow()
            self.feedback_text.setFocus()

    def _run_command(self):
        if self.process:
            kill_tree(self.process)
            self.process = None
            self.run_button.setText("运行(&R)")
            return

        # Clear the log buffer but keep UI logs visible
        self.log_buffer = []

        command = self.command_entry.text()
        if not command:
            self._append_log("请输入要运行的命令\n")
            return

        self._append_log(f"$ {command}\n")
        self.run_button.setText("停止(&P)")

        try:
            self.process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.project_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=get_user_environment(),
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="ignore",
                close_fds=True,
            )

            def read_output(pipe):
                for line in iter(pipe.readline, ""):
                    self.log_signals.append_log.emit(line)

            threading.Thread(
                target=read_output,
                args=(self.process.stdout,),
                daemon=True
            ).start()

            threading.Thread(
                target=read_output,
                args=(self.process.stderr,),
                daemon=True
            ).start()

            # Start process status checking
            self.status_timer = QTimer()
            self.status_timer.timeout.connect(self._check_process_status)
            self.status_timer.start(100)  # Check every 100ms

        except Exception as e:
            self._append_log(f"运行命令时出错: {str(e)}\n")
            self.run_button.setText("运行(&R)")

    def _submit_feedback(self):
        feedback_text = self.feedback_text.toPlainText().strip()
        
        # 处理图片：如果是粘贴的图片，保存到临时文件
        final_image_path = self.image_path
        if self.image_pixmap and not self.image_pixmap.isNull():
            if not self.image_path or self.image_path == "[粘贴的图片]" or not os.path.exists(self.image_path):
                # 保存图片到临时文件
                temp_dir = tempfile.gettempdir()
                temp_image_path = os.path.join(temp_dir, f"mcp_feedback_image_{os.getpid()}.png")
                self.image_pixmap.save(temp_image_path, "PNG")
                final_image_path = temp_image_path
                self.temp_image_path = temp_image_path
        
        # 如果有图片，在反馈文本中添加图片信息
        if final_image_path:
            if feedback_text:
                feedback_text += f"\n\n[图片: {final_image_path}]"
            else:
                feedback_text = f"[图片: {final_image_path}]"
        
        # 如果有上下文文件，添加到反馈中
        if self.context_files:
            context_info = "\n".join([f"  - {f}" for f in self.context_files])
            if feedback_text:
                feedback_text += f"\n\n[上下文文件:]\n{context_info}"
            else:
                feedback_text = f"[上下文文件:]\n{context_info}"
        
        self.feedback_result = FeedbackResult(
            logs="".join(self.log_buffer),
            interactive_feedback=feedback_text,
            image_path=final_image_path,
            context_files=self.context_files.copy(),
        )
        self.close()

    def _end_feedback(self):
        # 自动填入"结束"并提交反馈
        self.feedback_text.setPlainText("结束")
        self._submit_feedback()

    def _select_image_file(self):
        # 选择本地图片文件
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片文件",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;所有文件 (*.*)"
        )
        if file_path:
            self.image_input.setText(file_path)
            self._load_image()

    def _load_image(self):
        # 加载图片（从URL或本地路径）
        path = self.image_input.text().strip()
        if not path:
            return
        
        self.image_path = path
        
        # 判断是URL还是本地路径
        if path.startswith(("http://", "https://")):
            # URL图片 - 使用网络请求加载（简化版，实际可能需要异步加载）
            self.image_label.setText(f"URL图片: {path}\n(预览需要网络连接)")
            self.image_label.setStyleSheet("border: 1px solid #666; background-color: #2a2a2a; color: #fff;")
        else:
            # 本地文件路径
            if os.path.exists(path):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    # 保存原始图片
                    self.image_pixmap = pixmap
                    # 更新显示
                    self._update_image_display()
                else:
                    self.image_pixmap = None
                    self.image_label.setText("无法加载图片文件")
                    self.image_label.setStyleSheet("border: 1px solid #f00; background-color: #2a2a2a; color: #f00;")
            else:
                self.image_pixmap = None
                self.image_label.setText(f"文件不存在: {path}")
                self.image_label.setStyleSheet("border: 1px solid #f00; background-color: #2a2a2a; color: #f00;")

    def _paste_image(self):
        """粘贴图片按钮处理"""
        self.image_label._paste_from_clipboard()

    def _on_image_loaded(self, pixmap: QPixmap, source: str):
        """图片加载回调函数"""
        if not pixmap.isNull():
            # 保存原始图片
            self.image_pixmap = pixmap
            # 设置图片路径
            if source and os.path.exists(source):
                self.image_path = source
                self.image_input.setText(source)
            else:
                # 如果是粘贴的图片，立即保存为临时文件
                temp_dir = tempfile.gettempdir()
                temp_image_path = os.path.join(temp_dir, f"mcp_feedback_image_{os.getpid()}.png")
                pixmap.save(temp_image_path, "PNG")
                self.image_path = temp_image_path
                self.temp_image_path = temp_image_path
                self.image_input.setText(temp_image_path)
            # 更新显示
            self._update_image_display()
            # 更新样式
            self.image_label.setStyleSheet("border: 2px solid #42a2da; background-color: #2a2a2a;")

    def _clear_image(self):
        # 清除图片
        self.image_input.clear()
        self.image_path = ""
        self.image_pixmap = None
        self.image_label.clear()
        self.image_label.setText("点击或拖放图片到这里\n或按 Ctrl+V 粘贴图片")
        self.image_label.setStyleSheet("border: 2px dashed #666; background-color: #2a2a2a; color: #fff;")

    def _update_image_display(self):
        # 更新图片显示（当窗口大小改变时调用）
        if self.image_pixmap and not self.image_pixmap.isNull():
            # 获取显示区域尺寸，如果为0则使用默认值
            label_width = self.image_label.width() if self.image_label.width() > 0 else 400
            label_height = self.image_label.height() if self.image_label.height() > 0 else 300
            # 缩放图片以适应显示区域
            scaled_pixmap = self.image_pixmap.scaled(
                label_width,
                label_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.setText("")

    def _on_image_path_changed(self, text: str):
        # 当图片路径输入框内容改变时的处理
        pass

    def clear_logs(self):
        self.log_buffer = []
        self.log_text.clear()

    def _save_config(self):
        # Save run_command and execute_automatically to QSettings under project group
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("run_command", self.config["run_command"])
        self.settings.setValue("execute_automatically", self.config["execute_automatically"])
        self.settings.endGroup()
        self._append_log("已保存该项目的配置。\n")

    def resizeEvent(self, event):
        # 窗口大小改变时，更新图片显示
        super().resizeEvent(event)
        if self.image_pixmap:
            self._update_image_display()

    def closeEvent(self, event):
        # Save general UI settings for the main window (geometry, state)
        self.settings.beginGroup("MainWindow_General")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.endGroup()

        # Save project-specific command section visibility (this is now slightly redundant due to immediate save in toggle, but harmless)
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("commandSectionVisible", self.command_group.isVisible())
        self.settings.setValue("imageSectionVisible", self.image_group.isVisible())
        self.settings.setValue("contextSectionVisible", self.context_group.isVisible())
        self.settings.endGroup()

        if self.process:
            kill_tree(self.process)
        super().closeEvent(event)

    def run(self) -> FeedbackResult:
        self.show()
        QApplication.instance().exec()

        if self.process:
            kill_tree(self.process)

        if not self.feedback_result:
            return FeedbackResult(logs="".join(self.log_buffer), interactive_feedback="", image_path="", context_files=[])

        return self.feedback_result

def get_project_settings_group(project_dir: str) -> str:
    # Create a safe, unique group name from the project directory path
    # Using only the last component + hash of full path to keep it somewhat readable but unique
    basename = os.path.basename(os.path.normpath(project_dir))
    full_hash = hashlib.md5(project_dir.encode('utf-8')).hexdigest()[:8]
    return f"{basename}_{full_hash}"

def feedback_ui(project_directory: str, prompt: str, output_file: Optional[str] = None) -> Optional[FeedbackResult]:
    app = QApplication.instance() or QApplication()
    app.setPalette(get_dark_mode_palette(app))
    app.setStyle("Fusion")
    ui = FeedbackUI(project_directory, prompt)
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
    args = parser.parse_args()

    result = feedback_ui(args.project_directory, args.prompt, args.output_file)
    if result:
        print(f"\n收集的日志: \n{result['logs']}")
        print(f"\n收到的反馈:\n{result['interactive_feedback']}")
    sys.exit(0)
