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
    """启动浏览器，等待用户登录，从 localStorage 提取 token"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("错误: 需要 playwright，请运行: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        print("正在打开 DeepSeek 登录页面...")
        page.goto(f"{BASE_URL}/a/chat/s/new")

        # 等待用户登录
        print("请在浏览器中登录 DeepSeek（或等待自动登录）...")
        print("如果浏览器未自动打开，请手动访问 https://chat.deepseek.com")

        token = None
        for i in range(120):  # 最多等 2 分钟
            try:
                token = page.evaluate("localStorage.getItem('userToken')")
                if token:
                    break
            except Exception:
                pass
            time.sleep(1)

        browser.close()

    if not token:
        print("错误: 未能获取 token，请手动提供 --token 参数")
        sys.exit(1)

    # token 可能已经包含 "Bearer " 前缀，也可能没有
    if not token.startswith("Bearer "):
        token = f"Bearer {token}"

    print("✓ Token 获取成功")
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

    sessions = data.get("data", {}).get("biz_data", {}).get("chat_sessions", [])
    return sessions


def fetch_messages(token, session_id):
    """获取单个会话的消息历史"""
    headers = make_headers(token)
    url = f"{BASE_URL}/api/v0/chat/history_messages"
    params = {"chat_session_id": session_id}

    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    messages = data.get("data", {}).get("biz_data", {}).get("messages", [])
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
