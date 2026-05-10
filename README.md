# deepseek-export

批量导出 DeepSeek Web Chat 所有对话为 Markdown 文件，可选删除已导出对话。

## 安装

```bash
uv sync
uv run playwright install chromium
```

## 使用

所有命令用 `uv run` 执行，无需手动激活虚拟环境：

### 方式 1：自动获取 token（推荐）

```bash
uv run export.py --output ./deepseek-chats
```

脚本会启动浏览器打开 DeepSeek，登录后自动提取 token。

### 方式 2：手动提供 token

先在浏览器 F12 → Network 中找到任意 API 请求的 `Authorization` 头，
或者在 Console 中执行 `localStorage.getItem('userToken')`，然后：

```bash
uv run export.py --token "Bearer sk-xxx" --output ./deepseek-chats
```

### 导出并删除

```bash
uv run export.py --output ./deepseek-chats --delete
```

### 仅导出指定对话

```bash
uv run export.py --output ./deepseek-chats --filter "关键词"
```

## 输出

```
./deepseek-chats/
├── 2025-01-15_Rust生命周期问题.md
├── 2025-01-14_Zig编译器优化.md
└── _export_report.json
```
