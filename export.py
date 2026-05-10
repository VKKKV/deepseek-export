#!/usr/bin/env python3
"""
DeepSeek Web Chat 批量导出工具

批量导出所有对话为 Markdown，可选删除已导出对话。
通过 Playwright 获取浏览器登录态的 Bearer token，
然后调用 DeepSeek 内部 API 完成批量操作。
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://chat.deepseek.com"


# ─── Token 获取 ───────────────────────────────────────────────

def get_token_via_browser(headless=False):
    """启动浏览器，通过网络拦截从 DeepSeek 的 API 请求中抓取 Authorization token。
    使用持久化上下文保存登录态，下次无需重复登录。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("错误: 需要 playwright，请运行: uv run playwright install chromium")
        sys.exit(1)

    user_data_dir = os.path.expanduser("~/.local/share/deepseek-export/browser-data")
    os.makedirs(user_data_dir, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--ozone-platform-hint=auto",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 通过网络请求拦截抓取 Authorization 头
        token = None

        def on_response(response):
            nonlocal token
            if token:
                return
            try:
                auth = response.request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and len(auth) > 20:
                    token = auth
            except Exception:
                pass

        page.on("response", on_response)

        print("正在打开 DeepSeek...")
        page.goto(f"{BASE_URL}/a/chat/s/new", wait_until="domcontentloaded")

        # DeepSeek 加载后会自动发 API 请求，拦截即可拿到 token
        # 等页面加载 + 网络请求完成
        for i in range(60):
            if token:
                break
            # 如果页面加载完但没抓到（可能在等登录），手动触发一个 API 请求
            if i == 5 and not token:
                # 先 dump localStorage 帮助调试
                try:
                    keys = page.evaluate("Object.keys(localStorage)")
                    print(f"  localStorage keys: {keys}")
                    for k in (keys or []):
                        v = page.evaluate(f"localStorage.getItem('{k}')")
                        preview = str(v)[:80] if v else "null"
                        print(f"    {k}: {preview}")
                except Exception:
                    pass
                try:
                    page.evaluate(
                        "fetch('/api/v0/chat_session/fetch_page?count=1', {credentials:'include'})"
                    )
                except Exception:
                    pass
            if i == 3:
                print("请在浏览器中登录 DeepSeek...")
            time.sleep(1)

        context.close()

    if not token:
        print("错误: 未能获取 token，请手动提供 --token 参数")
        print("  方法: 浏览器 F12 → Network → 找任意 /api/v0 请求 → 复制 Authorization 头")
        print("  然后: uv run export.py --token 'Bearer <token>'")
        sys.exit(1)

    if not token.startswith("Bearer "):
        token = f"Bearer {token}"

    print(f"✓ Token 获取成功 (前 20 字符: {token[:20]}...)")
    return token


# ─── API 调用 ─────────────────────────────────────────────────

def make_headers(token):
    return {
        "Authorization": token,
        "Accept": "*/*",
        "Referer": f"{BASE_URL}/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }


def fetch_all_sessions(token, count=500):
    """获取所有对话会话列表"""
    headers = make_headers(token)
    url = f"{BASE_URL}/api/v0/chat_session/fetch_page"
    params = {"count": count}

    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    biz = (data.get("data") or {}).get("biz_data") or {}
    sessions = biz.get("chat_sessions") or []

    if not sessions:
        # 打印原始响应帮助调试
        print(f"  原始响应 (前 500 字符): {json.dumps(data, ensure_ascii=False)[:500]}")

    return sessions


def fetch_messages(token, session_id):
    """获取单个会话的消息历史"""
    headers = make_headers(token)
    url = f"{BASE_URL}/api/v0/chat/history_messages"
    params = {"chat_session_id": session_id}

    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    messages = (data.get("data") or {}).get("biz_data") or {}
    messages = messages.get("messages") or []
    return messages


def delete_session(token, session_id):
    """删除单个对话"""
    headers = make_headers(token)
    headers["Content-Type"] = "application/json"
    url = f"{BASE_URL}/api/v0/chat_session/delete"
    body = {"chat_session_id": session_id}

    resp = requests.post(url, headers=headers, json=body)
    return resp.status_code == 200


# ─── Markdown 转换 ────────────────────────────────────────────

def sanitize_filename(name, max_len=60):
    """清理文件名"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def format_timestamp(ts):
    """将毫秒时间戳转为日期字符串"""
    if not ts:
        return "unknown-date"
    try:
        dt = datetime.fromtimestamp(ts / 1000)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "unknown-date"


def extract_thinking_content(msg):
    """提取思考过程内容"""
    parts = []

    # 尝试从多种字段获取思考内容
    for key in ["thinking_content", "thinking", "reasoning_content"]:
        val = msg.get(key)
        if val and isinstance(val, str) and val.strip():
            parts.append(val.strip())

    # 检查 msg 内部的 metadata
    metadata = msg.get("metadata", {})
    if isinstance(metadata, dict):
        for key in ["thinking_content", "reasoning_content"]:
            val = metadata.get(key)
            if val and isinstance(val, str) and val.strip():
                parts.append(val.strip())

    return "\n\n".join(parts) if parts else None


def messages_to_markdown(session_title, messages):
    """将消息列表转换为 Markdown 格式"""
    lines = [f"# {session_title}", ""]

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "user":
            lines.append("## User")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

        elif role == "assistant":
            thinking = extract_thinking_content(msg)
            if thinking:
                lines.append("### 💭 Thinking")
                lines.append("")
                for tline in thinking.split("\n"):
                    lines.append(f"> {tline}")
                lines.append("")

            lines.append("## Assistant")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

        elif role == "system":
            lines.append("## System")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

        else:
            lines.append(f"## {role}")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


# ─── 主流程 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="DeepSeek Web Chat 批量导出工具"
    )
    parser.add_argument(
        "--token", "-t",
        help="Bearer token（不提供则自动从浏览器获取）"
    )
    parser.add_argument(
        "--output", "-o",
        default="./deepseek-chats",
        help="输出目录 (默认: ./deepseek-chats)"
    )
    parser.add_argument(
        "--delete", "-d",
        action="store_true",
        help="导出后删除已导出的对话"
    )
    parser.add_argument(
        "--filter", "-f",
        help="只导出标题包含此关键词的对话"
    )
    parser.add_argument(
        "--count", "-c",
        type=int, default=500,
        help="最大获取对话数 (默认: 500)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="浏览器无头模式（需要已有登录态 cookie）"
    )
    parser.add_argument(
        "--delay",
        type=float, default=0.5,
        help="API 请求间隔秒数，避免限流 (默认: 0.5)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出要导出的对话，不实际执行"
    )

    args = parser.parse_args()

    # 获取 token
    token = args.token
    if not token:
        token = get_token_via_browser(headless=args.headless)

    # 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取所有会话
    print(f"\n正在获取对话列表 (最多 {args.count} 个)...")
    sessions = fetch_all_sessions(token, count=args.count)
    print(f"找到 {len(sessions)} 个对话")

    # 过滤
    if args.filter:
        keyword = args.filter.lower()
        sessions = [s for s in sessions if keyword in (s.get("title") or "").lower()]
        print(f"过滤后剩余 {len(sessions)} 个对话")

    if not sessions:
        print("没有找到要导出的对话")
        return

    if args.dry_run:
        print("\n─── 将要导出的对话 ───")
        for i, s in enumerate(sessions, 1):
            print(f"  {i}. {s.get('title', 'untitled')} (id: {s.get('id', '?')[:12]}...)")
        print(f"\n共 {len(sessions)} 个对话")
        return

    # 逐个导出
    exported = []
    failed = []

    for i, session in enumerate(sessions, 1):
        sid = session.get("id", "")
        title = session.get("title", "untitled") or "untitled"
        created_at = session.get("created_at") or session.get("updated_at")

        print(f"[{i}/{len(sessions)}] 导出: {title}", end="", flush=True)

        try:
            messages = fetch_messages(token, sid)
            if not messages:
                print(" (空对话，跳过)")
                continue

            md_content = messages_to_markdown(title, messages)
            date_str = format_timestamp(created_at)
            safe_title = sanitize_filename(title)
            filename = f"{date_str}_{safe_title}.md"
            filepath = output_dir / filename

            # 避免重名
            counter = 1
            while filepath.exists():
                filepath = output_dir / f"{date_str}_{safe_title}_{counter}.md"
                counter += 1

            filepath.write_text(md_content, encoding="utf-8")
            exported.append({
                "id": sid,
                "title": title,
                "file": str(filepath),
                "messages": len(messages),
            })
            print(f" ✓ ({len(messages)} 条消息 → {filepath.name})")

        except Exception as e:
            failed.append({"id": sid, "title": title, "error": str(e)})
            print(f" ✗ 错误: {e}")

        time.sleep(args.delay)

    # 删除已导出对话
    if args.delete and exported:
        print(f"\n─── 删除已导出的 {len(exported)} 个对话 ───")
        deleted = []
        for item in exported:
            sid = item["id"]
            title = item["title"]
            print(f"  删除: {title}", end="", flush=True)

            try:
                ok = delete_session(token, sid)
                if ok:
                    deleted.append(sid)
                    print(" ✓")
                else:
                    print(" ✗ 删除失败")
            except Exception as e:
                print(f" ✗ {e}")

            time.sleep(args.delay)

        print(f"已删除 {len(deleted)}/{len(exported)} 个对话")

    # 生成报告
    report = {
        "export_time": datetime.now().isoformat(),
        "total_sessions": len(sessions),
        "exported": len(exported),
        "failed": len(failed),
        "deleted": args.delete,
        "exported_files": exported,
        "failed_items": failed,
    }

    report_path = output_dir / "_export_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 汇总
    print(f"\n═══ 完成 ═══")
    print(f"  成功导出: {len(exported)}")
    print(f"  失败:     {len(failed)}")
    if args.delete:
        print(f"  已删除:   {len(deleted)}")
    print(f"  输出目录: {output_dir.resolve()}")
    print(f"  报告文件: {report_path}")


if __name__ == "__main__":
    main()
