#!/usr/bin/env python3
"""
预热脚本 - 预先导入所有依赖以加速后续启动
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("预热中：导入依赖...")

# 预先导入所有重要的依赖
try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    print("✓ PySide6 已加载")
except ImportError as e:
    print(f"✗ PySide6 加载失败: {e}")
    sys.exit(1)

try:
    from fastmcp import FastMCP
    print("✓ FastMCP 已加载")
except ImportError as e:
    print(f"✗ FastMCP 加载失败: {e}")
    sys.exit(1)

try:
    import feedback_ui
    print("✓ feedback_ui 已加载")
except ImportError as e:
    print(f"✗ feedback_ui 加载失败: {e}")
    sys.exit(1)

print("\n✓ 预热完成！所有依赖已加载。")
print("MCP 服务器现在可以快速启动。")
