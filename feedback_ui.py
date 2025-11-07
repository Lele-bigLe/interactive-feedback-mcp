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
from typing import Optional, TypedDict

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
    def __init__(self, parent=None):
        super().__init__(parent)

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
        self.settings.endGroup() # End project-specific group
        
        self.config: FeedbackConfig = {
            "run_command": loaded_run_command,
            "execute_automatically": loaded_execute_auto
        }

        self._create_ui() # self.config is used here to set initial values

        # Set command section visibility AFTER _create_ui has created relevant widgets
        self.command_group.setVisible(command_section_visible)
        if command_section_visible:
            self.toggle_command_button.setText("隐藏命令区域")
        else:
            self.toggle_command_button.setText("显示命令区域")
        
        # Set image section visibility AFTER _create_ui has created relevant widgets
        self.image_group.setVisible(image_section_visible)
        if image_section_visible:
            self.toggle_image_button.setText("隐藏图片区域")
        else:
            self.toggle_image_button.setText("显示图片区域")

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

    def _create_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Toggle Command Section Button
        self.toggle_command_button = QPushButton("显示命令区域")
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
        self.feedback_group = QGroupBox("反馈")
        feedback_layout = QVBoxLayout(self.feedback_group)

        # Short description label (from self.prompt)
        self.description_label = QLabel(self.prompt)
        self.description_label.setWordWrap(True)
        feedback_layout.addWidget(self.description_label)

        # Toggle Image Section Button
        self.toggle_image_button = QPushButton("显示图片区域")
        self.toggle_image_button.clicked.connect(self._toggle_image_section)
        feedback_layout.addWidget(self.toggle_image_button)

        # 图片区域
        self.image_group = QGroupBox("图片（可选）")
        image_layout = QVBoxLayout(self.image_group)
        
        # 图片输入行
        image_input_layout = QHBoxLayout()
        self.image_input = QLineEdit()
        self.image_input.setPlaceholderText("输入图片URL或本地文件路径")
        self.image_input.textChanged.connect(self._on_image_path_changed)
        self.image_input.returnPressed.connect(self._load_image)
        
        select_image_button = QPushButton("选择文件(&I)")
        select_image_button.clicked.connect(self._select_image_file)
        load_image_button = QPushButton("加载(&L)")
        load_image_button.clicked.connect(self._load_image)
        paste_image_button = QPushButton("粘贴图片 (Ctrl+V)(&P)")
        paste_image_button.clicked.connect(self._paste_image)
        clear_image_button = QPushButton("清除(&X)")
        clear_image_button.clicked.connect(self._clear_image)
        
        image_input_layout.addWidget(self.image_input)
        image_input_layout.addWidget(select_image_button)
        image_input_layout.addWidget(load_image_button)
        image_input_layout.addWidget(paste_image_button)
        image_input_layout.addWidget(clear_image_button)
        image_layout.addLayout(image_input_layout)
        
        # 图片预览标签（支持粘贴和拖放）
        self.image_label = ImageLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(200)
        self.image_label.setMaximumHeight(400)
        self.image_label.setStyleSheet("border: 2px dashed #666; background-color: #2a2a2a; color: #fff;")
        self.image_label.setText("点击或拖放图片到这里\n或按 Ctrl+V 粘贴图片")
        self.image_label.setScaledContents(False)  # 使用手动缩放以保持质量
        self.image_label.set_image_loaded_callback(self._on_image_loaded)
        image_layout.addWidget(self.image_label)
        
        self.image_group.setVisible(False)  # 默认隐藏
        feedback_layout.addWidget(self.image_group)

        self.feedback_text = FeedbackTextEdit()
        font_metrics = self.feedback_text.fontMetrics()
        row_height = font_metrics.height()
        # Calculate height for 5 lines + some padding for margins
        padding = self.feedback_text.contentsMargins().top() + self.feedback_text.contentsMargins().bottom() + 5 # 5 is extra vertical padding
        self.feedback_text.setMinimumHeight(5 * row_height + padding)

        self.feedback_text.setPlaceholderText("在此输入您的反馈（Ctrl+Enter 提交）")
        
        # 按钮布局：发送反馈和结束按钮
        button_layout = QHBoxLayout()
        submit_button = QPushButton("发送反馈 (Ctrl+Enter)(&S)")
        submit_button.clicked.connect(self._submit_feedback)
        end_button = QPushButton("结束(&E)")
        end_button.clicked.connect(self._end_feedback)
        
        button_layout.addWidget(submit_button)
        button_layout.addWidget(end_button)

        feedback_layout.addWidget(self.feedback_text)
        feedback_layout.addLayout(button_layout)

        # Set minimum height for feedback_group to accommodate its contents
        # This will be based on the description label and the 5-line feedback_text
        self.feedback_group.setMinimumHeight(self.description_label.sizeHint().height() + self.feedback_text.minimumHeight() + submit_button.sizeHint().height() + feedback_layout.spacing() * 2 + feedback_layout.contentsMargins().top() + feedback_layout.contentsMargins().bottom() + 10) # 10 for extra padding

        # Add widgets in a specific order
        layout.addWidget(self.feedback_group)

        # Credits/Contact Label
        contact_label = QLabel('需要改进？联系 Fábio Ferreira <a href="https://x.com/fabiomlferreira">X.com</a> 或访问 <a href="https://dotcursorrules.com/">dotcursorrules.com</a>')
        contact_label.setOpenExternalLinks(True)
        contact_label.setAlignment(Qt.AlignCenter)
        # Optionally, make font a bit smaller and less prominent
        # contact_label_font = contact_label.font()
        # contact_label_font.setPointSize(contact_label_font.pointSize() - 1)
        # contact_label.setFont(contact_label_font)
        contact_label.setStyleSheet("font-size: 9pt; color: #cccccc;") # Light gray for dark theme
        layout.addWidget(contact_label)

    def _toggle_command_section(self):
        is_visible = self.command_group.isVisible()
        self.command_group.setVisible(not is_visible)
        if not is_visible:
            self.toggle_command_button.setText("隐藏命令区域")
        else:
            self.toggle_command_button.setText("显示命令区域")
        
        # Immediately save the visibility state for this project
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("commandSectionVisible", self.command_group.isVisible())
        self.settings.endGroup()

        # Adjust window height only
        new_height = self.centralWidget().sizeHint().height()
        if self.command_group.isVisible() and self.command_group.layout().sizeHint().height() > 0 :
             # if command group became visible and has content, ensure enough height
             min_content_height = self.command_group.layout().sizeHint().height() + self.feedback_group.minimumHeight() + self.toggle_command_button.height() + layout().spacing() * 2
             new_height = max(new_height, min_content_height)

        current_width = self.width()
        self.resize(current_width, new_height)

    def _toggle_image_section(self):
        """切换图片区域的显示/隐藏"""
        is_visible = self.image_group.isVisible()
        self.image_group.setVisible(not is_visible)
        if not is_visible:
            self.toggle_image_button.setText("隐藏图片区域")
        else:
            self.toggle_image_button.setText("显示图片区域")
        
        # 立即保存该项目的可见性状态
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("imageSectionVisible", self.image_group.isVisible())
        self.settings.endGroup()

        # 调整窗口高度
        new_height = self.centralWidget().sizeHint().height()
        if self.image_group.isVisible() and self.image_group.layout().sizeHint().height() > 0:
            # 如果图片区域变为可见且有内容，确保有足够的高度
            min_content_height = self.image_group.layout().sizeHint().height() + self.feedback_group.minimumHeight()
            new_height = max(new_height, min_content_height)

        current_width = self.width()
        self.resize(current_width, new_height)

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
        # 如果有图片，在反馈文本中添加图片信息
        if self.image_path:
            if feedback_text:
                feedback_text += f"\n\n[图片: {self.image_path}]"
            else:
                feedback_text = f"[图片: {self.image_path}]"
        
        self.feedback_result = FeedbackResult(
            logs="".join(self.log_buffer),
            interactive_feedback=feedback_text,
            image_path=self.image_path,
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
                # 如果是粘贴的图片，保存为临时文件或标记为粘贴
                self.image_path = f"[粘贴的图片]"
                self.image_input.setText("[粘贴的图片]")
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
            return FeedbackResult(logs="".join(self.log_buffer), interactive_feedback="", image_path="")

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
