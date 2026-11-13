"""
关键词命中推送脚本（盘中即时通道）
用法：
  python3 keyword_digest.py scan            # 扫描近24h新闻匹配关键词（通常由 daily_collect 后调用）
  python3 keyword_digest.py push            # 推送未推送的 P0 命中到钉钉（附智能体点评占位，agent 应在 cron 中先补充点评再发）
  python3 keyword_digest.py pending         # 列出待推送命中（只读）
  python3 keyword_digest.py digest          # 晨报关键词板块文本
"""
import sys
sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
from core.db import get_conn
from core.keywords import KeywordMonitor, scan_unmatched, pending_alerts, mark_alerted, daily_digest


def cmd_scan():
    conn = get_conn()
    n = scan_unmatched(conn, hours=24)
    p0 = conn.execute("SELECT COUNT(*) c FROM keyword_hits WHERE priority='P0' AND alerted=0").fetchone()["c"]
    p1 = conn.execute("SELECT COUNT(*) c FROM keyword_hits WHERE priority='P1' AND alerted=0").fetchone()["c"]
    print(f"matched {n} hits; pending push: P0={p0} P1={p1}")
    conn.close()


def cmd_pending():
    conn = get_conn()
    mon = KeywordMonitor()
    for pri in ("P0", "P1"):
        alerts = pending_alerts(conn, pri)
        print(f"\n── {pri} 待推送 ({len(alerts)} 条) ──")
        for a in alerts[:30]:
            kws = "/".join(a["keywords"])
            print(f"  [{kws}] {a['title']} ({a['source'].replace('trendradar:','').replace('rss:','')})")
    conn.close()


def cmd_push(dry=False):
    """推送 P0 命中（合并成一条钉钉消息；点评由消息模板给出框架，agent cron 会带上下文改写）"""
    from core import dingtalk
    conn = get_conn()
    alerts = pending_alerts(conn, "P0")
    if not alerts:
        print("no pending P0 alerts")
        conn.close()
        return
    mon = KeywordMonitor()
    # 按标题去重（多源重复采集）
    by_title: dict[str, dict] = {}
    for a in alerts:
        t = a["title"]
        if t in by_title:
            by_title[t]["keywords"] = list(dict.fromkeys(by_title[t]["keywords"] + a["keywords"]))
        else:
            by_title[t] = a
    uniq = list(by_title.values())
    lines = []
    for a in uniq[:20]:  # 上限防刷屏
        kws = "/".join(a["keywords"])
        note = "；".join(filter(None, [mon.note(k) for k in a["keywords"][:2]]))
        src = a["source"].replace("trendradar:", "").replace("rss:", "")
        lines.append(f"- **[{kws}]** {a['title']}（{src}）{('—— ' + note) if note else ''}")
    msg = "### 🔔 关键词监控 | 盘中快报\n\n" + "\n".join(lines) + \
          "\n\n> 以上为关键词订阅命中的实时信号，操作建议见每日晨报与收盘盯市。"
    if dry:
        print(msg)
    else:
        r = dingtalk.send_markdown(f"关键词监控 | {len(uniq)}条命中", msg)
        print(r)
        mark_alerted(conn, [a["raw_id"] for a in alerts])
    conn.close()


def cmd_digest():
    conn = get_conn()
    mon = KeywordMonitor()
    d = daily_digest(conn)
    if not d:
        print("（近24h无关键词命中）")
        conn.close()
        return
    print("### 📡 关键词监控 24h 汇总\n")
    for kw in sorted(d, key=lambda k: (0 if kw_pri(conn, k) == "P0" else 1, k)):
        items = d[kw]
        pri = kw_pri(conn, kw)
        note = mon.note(kw)
        print(f"**[{pri}] {kw}**（{len(items)}条）{('—— ' + note) if note else ''}")
        for it in items[:5]:
            src = it["source"].replace("trendradar:", "").replace("rss:", "")
            print(f"  - {it['title']}（{src}）")
        if len(items) > 5:
            print(f"  - …等{len(items)}条")
        print()
    conn.close()


def kw_pri(conn, kw):
    r = conn.execute("SELECT priority FROM keyword_hits WHERE keyword=? LIMIT 1", (kw,)).fetchone()
    return r["priority"] if r else "P1"


if __name__ == "__main__":
    if any(a in ("-h", "--help", "help") for a in sys.argv[1:]):
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pending"
    cmds = {"scan": cmd_scan, "pending": cmd_pending,
            "push": lambda: cmd_push(dry="--dry" in sys.argv), "digest": cmd_digest}
    if cmd not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[cmd]()
