#!/usr/bin/env python3
"""通用钉钉推送脚本（econ_agent 唯一对外推送入口）

用法:
  python3 push_dingtalk.py --title "标题" --file /tmp/msg.md
  echo "正文" | python3 push_dingtalk.py --title "标题"

说明:
  - webhook 已内置，调用方无需提供任何目标 ID/token
  - 正文为 markdown；自动加【AI】前缀
  - 成功打印 {"ok": true}；失败以非零码退出
"""
import argparse
import sys

sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
from core import dingtalk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="消息标题（不含【AI】前缀）")
    ap.add_argument("--file", help="正文文件路径；省略则从 stdin 读取")
    args = ap.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        print("ERROR: empty message body", file=sys.stderr)
        sys.exit(2)

    r = dingtalk.send_markdown(args.title, text)
    print(r)
    if not r.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
