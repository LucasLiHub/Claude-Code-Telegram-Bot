# Claude Code Telegram Bot

Control your local Claude Code CLI remotely via Telegram — send messages from your phone to have Claude execute coding tasks on your server or local machine.

## Features

- **Remote execution**: Drive Claude Code through Telegram messages, supporting file read/write, shell commands, code editing, and more
- **Real-time feedback**: Displays the current tool call in real time while a task runs, no need to wait until completion
- **Multi-session management**: Create, switch, and delete named sessions; state is restored automatically after restart
- **Image / file input**: Send images for Claude to analyze directly, or send files to be saved to the working directory
- **Audit log**: All tool calls are logged by date for easy review and traceability
- **Concurrency protection**: Only one task runs at a time per user, preventing parallel Claude process conflicts
- **Cross-platform**: Works on Linux, macOS, and Windows WSL

## Prerequisites

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- A Telegram Bot Token (create one via [@BotFather](https://t.me/BotFather))
- Your Telegram user ID (get it from [@userinfobot](https://t.me/userinfobot))

## Project Structure

```
claude-code-telegram-bot/
├── bot.py              # Main program
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── .gitignore
├── state.json          # Generated at runtime — session state (not committed)
└── logs/               # Generated at runtime — daily audit logs (not committed)
    └── 2026-03-27.log
```

## Quick Start

**1. Clone and install dependencies**

```bash
git clone https://github.com/your-username/claude-code-telegram-bot.git
cd claude-code-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

```
TELEGRAM_BOT_TOKEN=your-bot-token
ALLOWED_USER_ID=your-telegram-user-id
```

Choose one authentication method:

```
# Option 1: Standard Anthropic API key
ANTHROPIC_API_KEY=sk-ant-...

# Option 2: Claude.ai subscription token
ANTHROPIC_AUTH_TOKEN=...

# Option 3: Third-party proxy service
ANTHROPIC_AUTH_TOKEN=...
ANTHROPIC_BASE_URL=https://your-proxy.com
```

**3. Run**

```bash
python3 bot.py
```

## Command Reference

| Command | Description |
|---|---|
| `/sessions` | List all sessions, with the active one marked |
| `/session <name>` | Switch to a named session, or create it if it doesn't exist |
| `/session_delete <name>` | Delete a session and its history |
| `/clear` | Clear the current session's conversation history |
| `/setdir <path>` | Set the working directory for the current session |
| `/cancel` | Cancel the currently running task |

Send any text message to chat with Claude. Images and files are also supported — images are analyzed directly by Claude; files are saved to the working directory.

## Important Notes

**Security**
- The bot runs in `bypassPermissions` mode — Claude can execute arbitrary commands and read/write any file. Keep your Bot Token secret.
- `.env` contains sensitive credentials and is excluded via `.gitignore`. **Never commit it to a repository.**
- `ALLOWED_USER_ID` restricts access to a single user. Set it to your own Telegram user ID.

**Limitations**
- Single task at a time: new messages are rejected while a task is running; use `/cancel` to interrupt
- Task timeout: tasks are automatically terminated after 120 seconds
- Session history is stored locally in `~/.claude/projects/` and is never uploaded to the cloud

**Platform notes**
- Windows requires WSL; native Windows is not supported
- macOS works out of the box with no additional configuration

---

# Claude Code Telegram Bot

通过 Telegram 远程控制本机的 Claude Code CLI，让你随时随地用手机发消息来让 Claude 在服务器或本地执行编程任务。

## 功能特性

- **远程执行**：通过 Telegram 消息驱动 Claude Code，支持文件读写、执行命令、代码编辑等操作
- **实时反馈**：任务执行时实时显示当前工具调用内容，无需等待任务结束
- **多 Session 管理**：支持创建、切换、删除命名 Session，重启后自动恢复上次会话
- **图片/文件输入**：支持发送图片（Claude 直接分析）和文件（保存到工作目录供 Claude 处理）
- **操作日志**：按日期记录所有工具调用，便于审计和回溯
- **并发保护**：同一时间只处理一条消息，防止多个 Claude 进程并发冲突
- **多平台支持**：兼容 Linux、macOS 及 Windows WSL

## 前置要求

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 已安装并完成认证
- Telegram Bot Token（通过 [@BotFather](https://t.me/BotFather) 创建）
- 你的 Telegram 用户 ID（可通过 [@userinfobot](https://t.me/userinfobot) 获取）

## 项目结构

```
claude-code-telegram-bot/
├── bot.py              # 主程序
├── requirements.txt    # Python 依赖
├── .env.example        # 环境变量配置模板
├── .gitignore
├── state.json          # 运行时生成，保存 Session 状态（不上传）
└── logs/               # 运行时生成，按日期存储操作日志（不上传）
    └── 2026-03-27.log
```

## 快速开始

**1. 克隆项目并安装依赖**

```bash
git clone https://github.com/your-username/claude-code-telegram-bot.git
cd claude-code-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

**2. 配置环境变量**

```bash
cp .env.example .env
```

编辑 `.env`，填写以下内容：

```
TELEGRAM_BOT_TOKEN=你的Bot Token
ALLOWED_USER_ID=你的Telegram用户ID
```

认证方式三选一：

```
# 方式一：标准 Anthropic API Key
ANTHROPIC_API_KEY=sk-ant-...

# 方式二：Claude.ai 订阅 Token
ANTHROPIC_AUTH_TOKEN=...

# 方式三：第三方中转服务
ANTHROPIC_AUTH_TOKEN=...
ANTHROPIC_BASE_URL=https://your-proxy.com
```

**3. 启动**

```bash
python3 bot.py
```

## 命令参考

| 命令 | 说明 |
|---|---|
| `/sessions` | 列出所有 Session，标出当前激活的 |
| `/session <名称>` | 切换到指定 Session，不存在则新建 |
| `/session_delete <名称>` | 删除指定 Session 及其历史记录 |
| `/clear` | 清除当前 Session 的对话历史 |
| `/setdir <路径>` | 设置当前 Session 的工作目录 |
| `/cancel` | 中断正在执行的任务 |

直接发送文本消息即可与 Claude 对话，也支持发送图片（Claude 直接分析）和文件（保存到工作目录）。

## 注意事项

**安全**
- Bot 以 `bypassPermissions` 模式运行，Claude 可执行任意命令、读写任意文件，请确保 Bot Token 不外泄
- `.env` 文件包含敏感信息，已在 `.gitignore` 中排除，**切勿上传至代码仓库**
- `ALLOWED_USER_ID` 只允许单个用户使用，请填写你自己的 Telegram 用户 ID

**使用限制**
- 单任务执行：同一用户同时只能运行一个任务，新消息在任务执行期间会被拒绝
- 任务超时：单次任务最长执行 120 秒，超时后自动终止
- Session 历史存储在本地 `~/.claude/projects/` 目录，不会上传至云端

**平台说明**
- Windows 需在 WSL 环境下运行，不支持原生 Windows
- macOS 可直接运行，无需额外配置
