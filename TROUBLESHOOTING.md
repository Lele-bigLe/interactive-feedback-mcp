# Interactive Feedback MCP - 故障排查指南

## 启动不稳定问题解决方案

### 问题描述
MCP 工具启动时偶尔会失败，表现为工具无响应或启动超时。

### 已实施的优化

#### 1. 服务器端优化 (server.py)

**改进的进程管理：**
- ✅ 增加了 subprocess 超时时间（timeout_seconds + 30秒）
- ✅ 改用 PIPE 捕获 stdout/stderr，而非 DEVNULL
- ✅ 添加详细的错误信息记录
- ✅ 新增 `health_check` 工具用于诊断

**使用健康检查：**
```python
# 在 Claude 中调用
health_check()
```

返回示例：
```json
{
  "python_version": "3.13.0",
  "pyside6": "✓ 已安装",
  "feedback_ui": "✓ 存在",
  "timeout_seconds": "600"
}
```

#### 2. MCP 配置优化 (mcp.json)

**推荐配置：**
```json
{
  "interactive-feedback-mcp": {
    "command": "uv",
    "args": [
      "--directory",
      "D:\\lt\\interactive-feedback-mcp",
      "run",
      "server.py"
    ],
    "timeout": 900,
    "env": {
      "INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS": "600",
      "PYTHONUNBUFFERED": "1",
      "PYTHONUTF8": "1"
    },
    "autoApprove": [
      "interactive_feedback"
    ],
    "type": "stdio"
  }
}
```

**关键改进：**
- `timeout: 900` - 增加到15分钟，给 PySide6 足够的加载时间
- `PYTHONUNBUFFERED: "1"` - 禁用 Python 输出缓冲，确保实时输出
- `PYTHONUTF8: "1"` - 强制使用 UTF-8 编码，避免中文乱码

#### 3. 预热脚本 (warmup.py)

**首次使用时运行：**
```bash
cd D:\lt\interactive-feedback-mcp
uv run warmup.py
```

这会预先加载所有依赖，加速后续启动。

### 故障排查步骤

#### 步骤1：验证环境
```bash
# 检查 Python 版本
python --version

# 检查 PySide6 安装
python -c "import PySide6; print('PySide6 已安装')"

# 检查 uv 版本
uv --version
```

#### 步骤2：测试直接启动
```bash
cd D:\lt\interactive-feedback-mcp
python feedback_ui.py --project-directory "D:\lt\interactive-feedback-mcp" --prompt "测试"
```

如果直接启动成功，说明问题在 MCP 配置或 uv 环境。

#### 步骤3：检查 MCP 日志
查看 Claude Desktop 或 VSCode 的 MCP 日志：
- Claude Desktop: `%APPDATA%\Claude\logs\`
- VSCode: 输出面板 → MCP

#### 步骤4：使用健康检查
在 Claude 中运行：
```
请使用 health_check 工具检查服务器状态
```

### 常见问题

#### Q1: "Failed to launch feedback UI: 1"
**原因：** PySide6 导入失败或 feedback_ui.py 有语法错误

**解决：**
```bash
# 重新安装依赖
cd D:\lt\interactive-feedback-mcp
uv sync --reinstall
```

#### Q2: 启动超时
**原因：** PySide6 首次加载慢，或系统资源不足

**解决：**
1. 增加 `timeout` 到 900 或更高
2. 运行预热脚本 `uv run warmup.py`
3. 关闭其他占用资源的程序

#### Q3: 中文乱码
**原因：** 编码问题

**解决：**
在 `mcp.json` 的 `env` 中添加：
```json
"PYTHONUTF8": "1"
```

#### Q4: uv 环境初始化慢
**原因：** uv 需要时间设置虚拟环境

**解决：**
1. 预先运行 `uv sync` 创建环境
2. 考虑使用系统 Python 而非 uv：
```json
{
  "command": "python",
  "args": ["D:\\lt\\interactive-feedback-mcp\\server.py"]
}
```

### 性能优化建议

1. **首次启动预热**
   ```bash
   uv run warmup.py
   ```

2. **保持 MCP 服务器运行**
   - 不要频繁重启 Claude Desktop/VSCode
   - MCP 服务器会缓存已加载的模块

3. **使用 SSD**
   - 将项目放在 SSD 上可显著提升启动速度

4. **减少启动时的系统负载**
   - 关闭不必要的后台程序
   - 确保有足够的可用内存（建议 4GB+）

### 联系支持

如果问题仍然存在，请提供：
1. `health_check` 的输出
2. MCP 日志文件
3. 直接运行 `feedback_ui.py` 的输出
4. 系统信息（Windows 版本、Python 版本、可用内存）

---

**最后更新：** 2026-01-28
**版本：** 0.1.0
