# Interactive Feedback MCP - 交互式反馈工具

由 Fábio Ferreira ([@fabiomlferreira](https://x.com/fabiomlferreira)) 开发。
更多 AI 开发增强工具请访问 [dotcursorrules.com](https://dotcursorrules.com/)。

一个简单的 [MCP 服务器](https://modelcontextprotocol.io/)，用于在 AI 辅助开发工具中实现「人在回路」的交互工作流。
支持 [Cursor](https://www.cursor.com)、[Cline](https://cline.bot)、[Windsurf](https://windsurf.com)、VS Code Copilot 等工具。

## 这是什么？

在 AI 辅助编程时，AI 经常在完成任务后直接结束，不给用户确认的机会。本工具通过弹出一个交互反馈窗口，让用户可以：

- ✏️ 输入文字反馈或补充说明
- 🖼️ 粘贴截图（Ctrl+V）或拖放图片
- 📄 通过 `@文件路径#行号` 语法引用项目文件
- 💡 从预设选项中快速选择方案
- ⏱️ 超时自动保持会话活跃

## 为什么需要它？

通过引导 AI 在每次操作后向用户确认，而不是盲目执行多步操作，可以：

- **节省 AI 请求次数** — 避免 AI 猜测性地调用大量工具
- **提高准确性** — 用户可以及时纠正方向
- **保持对话活跃** — 超时机制防止会话断开

## 快速开始

### 前置要求

- Python 3.11 或更高版本
- [uv](https://github.com/astral-sh/uv)（Python 包管理器）
  - Windows：`pip install uv`
  - Linux/Mac：`curl -LsSf https://astral.sh/uv/install.sh | sh`

### 安装步骤

1. **克隆代码仓库**

   ```bash
   git clone https://github.com/noopstudios/interactive-feedback-mcp.git
   cd interactive-feedback-mcp
   ```

2. **安装依赖**

   ```bash
   uv sync
   ```

3. **运行服务**

   ```bash
   uv run server.py
   ```

### 配置 MCP 客户端

在你使用的 AI 工具中添加以下 MCP 配置（以 JSON 配置文件为例）：

> ⚠️ 请将路径替换为你本地实际的克隆目录。

```json
{
  "mcpServers": {
    "interactive-feedback-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/你的实际路径/interactive-feedback-mcp",
        "run",
        "server.py"
      ],
      "timeout": 600,
      "autoApprove": ["interactive_feedback"],
      "env": {
        "INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS": "600"
      }
    }
  }
}
```

**各工具配置位置：**

| 工具 | 配置方式 |
|------|---------|
| **Cursor** | 设置 → MCP Servers → 添加上述配置 |
| **VS Code Copilot** | `.vscode/mcp.json` 或用户设置中添加 |
| **Cline** | Cline MCP 设置中添加 |
| **Windsurf** | Windsurf MCP 设置中添加 |

## 提示词工程

为了获得最佳效果，在 AI 助手的自定义提示词中添加以下规则：

> 当你需要向用户提问时，始终调用 `interactive_feedback` MCP 工具。
> 当你即将完成用户请求时，调用 `interactive_feedback` 而不是直接结束任务。
> 持续调用 MCP 直到用户反馈为空或用户明确说「结束」。

## 功能特性

| 功能 | 说明 |
|------|------|
| **文字反馈** | 在输入框中输入反馈内容，Ctrl+Enter 发送 |
| **图片粘贴** | 在输入框中 Ctrl+V 直接粘贴截图，也支持拖放图片文件和文件选择按钮 |
| **文件引用** | 使用 `@src/views/example/index.vue#61-70` 引用项目中的文件和行号 |
| **快速选项** | AI 提供的方案选项，垂直排列，点击切换选中（不覆盖输入内容） |
| **超时机制** | 倒计时显示，支持暂停/重置，超时后自动返回标记让 AI 重新调用 |
| **项目标识** | 窗口标题显示项目名称，多项目并行时方便识别 |
| **临时图片清理** | 点击「结束」按钮时自动清除所有临时截图文件 |

### 文件引用语法

在反馈输入框中支持以下引用格式：

```
@src/views/dataAdmin/uploadHead/index.vue          → 引用整个文件
@src/views/dataAdmin/uploadHead/index.vue#61        → 引用第 61 行
@src/views/dataAdmin/uploadHead/index.vue#61-70     → 引用第 61 到 70 行
```

输入时底部会实时预览检测到的引用。

### 图片功能

支持三种方式添加图片：

1. **Ctrl+V 粘贴** — 在输入框中直接粘贴剪贴板截图（如 Win+Shift+S 截图后粘贴）
2. **拖放文件** — 将图片文件拖放到输入框中
3. **文件选择** — 通过底部的「📂 选择图片」按钮选择本地图片

图片会保存为临时文件，路径通过 `image_paths` 字段返回给 AI。点击「结束」按钮时会自动清除所有临时图片。

### 快速选项

AI 可以通过 `options` 参数提供预设选项供用户快速选择：

- 每个选项独占一行，垂直排列
- 点击选中（显示 ✔ 标记），再次点击取消选中
- 选中的选项**追加**到反馈中，**不会覆盖**输入框已有内容
- 支持同时选中多个选项

## 工具参数

### `interactive_feedback` 工具

| 参数 | 类型 | 必需 | 说明 |
|-----|------|------|------|
| `project_directory` | string | ✅ | 项目目录的完整路径 |
| `summary` | string | ✅ | 简短的变更摘要说明（一行） |
| `current_file` | string | ❌ | 当前正在编辑的文件路径 |
| `options` | array | ❌ | 解决方案选项列表，例如 `["方案A: ...", "方案B: ..."]` |

### 返回结果

| 字段 | 类型 | 说明 |
|-----|------|------|
| `interactive_feedback` | string | 用户反馈文本（含文件引用和选项信息） |
| `image_paths` | array | 用户添加的图片文件路径列表 |
| `selected_options` | array | 用户选中的选项列表 |
| `timeout_triggered` | bool | 是否因超时触发（为 `true` 时需要重新调用） |

### 调用示例

```xml
<use_mcp_tool>
  <server_name>interactive-feedback-mcp</server_name>
  <tool_name>interactive_feedback</tool_name>
  <arguments>
    {
      "project_directory": "/path/to/your/project",
      "summary": "已完成登录页面的重构，请确认是否符合预期。",
      "current_file": "/path/to/your/project/src/views/login/index.vue",
      "options": ["符合预期", "需要修改", "有新的需求"]
    }
  </arguments>
</use_mcp_tool>
```

### `health_check` 工具

健康检查工具，无需参数，用于验证 MCP 服务器和依赖是否正常运行。

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `INTERACTIVE_FEEDBACK_TIMEOUT_SECONDS` | 超时时间（秒），超时后自动返回标记 | `600`（10分钟） |

## 开发调试

使用 FastMCP 的开发模式启动，会打开一个 Web 测试界面：

```bash
uv run fastmcp dev server.py
```

## 配置存储

窗口大小和位置等设置通过 Qt 的 `QSettings` 自动保存：

| 系统 | 存储位置 |
|------|---------|
| **Windows** | 注册表 `HKEY_CURRENT_USER\Software\InteractiveFeedbackMCP` |
| **macOS** | `~/Library/Preferences/` |
| **Linux** | `~/.config/InteractiveFeedbackMCP/` |

## 致谢

由 Fábio Ferreira 开发，如果觉得有用请关注 [X @fabiomlferreira](https://x.com/fabiomlferreira)。
更多 AI 开发资源请访问 [dotcursorrules.com](https://dotcursorrules.com/)。
