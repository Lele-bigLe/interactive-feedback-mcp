# Interactive Feedback MCP
# Developed by Fábio Ferreira (https://x.com/fabiomlferreira)
# Inspired by/related to dotcursorrules.com (https://dotcursorrules.com/)
import os
import sys
import json
import tempfile
import subprocess
import time

from typing import Annotated, Dict, Optional, List

from fastmcp import FastMCP
from pydantic import Field

# 从环境变量获取超时配置（秒），默认600秒（10分钟）
INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS = int(os.environ.get("INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS", "600"))

# The log_level is necessary for Cline to work: https://github.com/jlowin/fastmcp/issues/81
mcp = FastMCP("Interactive Feedback MCP", log_level="ERROR")

def launch_feedback_ui(project_directory: str, summary: str, current_file: Optional[str] = None, timeout_seconds: int = INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS, options: Optional[List[str]] = None) -> dict[str, str]:
    """
    启动反馈UI界面
    
    参数:
        project_directory: 项目目录路径
        summary: 摘要说明
        current_file: 当前编辑文件的路径（用于文件选择器）
        timeout_seconds: 超时时间（秒），超时后自动重新调用以保持会话活跃
        options: 可选的解决方案列表，供用户快速选择
    """
    # Create a temporary file for the feedback result
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_file = tmp.name

    try:
        # Get the path to feedback_ui.py relative to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        feedback_ui_path = os.path.join(script_dir, "feedback_ui.py")

        # Run feedback_ui.py as a separate process
        # NOTE: There appears to be a bug in uv, so we need
        # to pass a bunch of special flags to make this work
        args = [
            sys.executable,
            "-u",
            feedback_ui_path,
            "--project-directory", project_directory,
            "--prompt", summary,
            "--output-file", output_file,
            "--timeout", str(timeout_seconds)
        ]
        # 添加当前文件路径参数
        if current_file:
            args.extend(["--current-file", current_file])
        # 添加选项参数
        if options:
            args.extend(["--options", json.dumps(options, ensure_ascii=False)])
        
        result = subprocess.run(
            args,
            check=False,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True
        )
        if result.returncode != 0:
            raise Exception(f"Failed to launch feedback UI: {result.returncode}")

        # Read the result from the temporary file
        with open(output_file, 'r') as f:
            result = json.load(f)
        os.unlink(output_file)
        return result
    except Exception as e:
        if os.path.exists(output_file):
            os.unlink(output_file)
        raise e

def first_line(text: str) -> str:
    return text.split("\n")[0].strip()

@mcp.tool()
def interactive_feedback(
    project_directory: Annotated[str, Field(description="Full path to the project directory")],
    summary: Annotated[str, Field(description="Short, one-line summary of the changes")],
    current_file: Annotated[Optional[str], Field(description="Current file being edited, used for file dialog initial directory")] = None,
    options: Annotated[Optional[List], Field(description="Optional list of solution options for user to choose from, e.g. ['Option A: ...', 'Option B: ...']")] = None,
) -> Dict[str, str]:
    """
    Request interactive feedback for a given project directory and summary.
    
    此工具会启动一个交互式反馈界面，等待用户输入。如果用户在超时时间内未响应，
    工具会自动返回一个特殊标记，提示需要重新调用以保持会话活跃。
    
    超时时间可通过环境变量 INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS 配置，默认600秒。
    
    可以通过 options 参数提供多个解决方案供用户快速选择。
    """
    return launch_feedback_ui(
        first_line(project_directory), 
        first_line(summary),
        first_line(current_file) if current_file else None,
        INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS,
        options
    )

if __name__ == "__main__":
    mcp.run(transport="stdio")
