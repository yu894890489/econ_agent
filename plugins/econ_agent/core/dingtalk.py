"""
钉钉推送模块
- 所有消息自动加【AI】前缀
- markdown 格式
- 支持合并推送（避免触发频率限制：20条/分钟）
"""
import json
import time
import logging
import requests

log = logging.getLogger(__name__)

WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=d7b9ba6972dbd851e2b626e7dee87c1e2ccd869d9a19abca010b9ef98bf39dff"
TAG = "【AI】"


def send_markdown(title: str, text: str, webhook: str = WEBHOOK, retry: int = 2) -> dict:
    """推送 markdown 消息，text 会自动加【AI】前缀"""
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"{TAG}{title}",
            "text": f"{TAG} {text}",
        },
    }
    for attempt in range(retry + 1):
        try:
            r = requests.post(webhook, json=payload, timeout=10)
            r.raise_for_status()
            res = r.json()
            if res.get("errcode") == 0:
                log.info("dingtalk sent: %s", title)
                return {"ok": True}
            log.warning("dingtalk error: %s %s", res.get("errcode"), res.get("errmsg"))
            if res.get("errcode") == 130101:  # 频率限制
                time.sleep(5)
                continue
            return {"ok": False, "error": res}
        except Exception as e:
            log.error("dingtalk request failed: %s (attempt %d)", e, attempt)
            time.sleep(3)
    return {"ok": False, "error": "max retries"}


def send_text(text: str, webhook: str = WEBHOOK) -> dict:
    payload = {"msgtype": "text", "text": {"content": f"{TAG} {text}"}}
    try:
        r = requests.post(webhook, json=payload, timeout=10)
        return {"ok": True, "resp": r.json()} if r.json().get("errcode") == 0 else {"ok": False, "resp": r.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def batch_send(messages: list[dict], interval: float = 1.5):
    """messages: [{title, text}] 逐条发送，带间隔"""
    results = []
    for m in messages:
        results.append(send_markdown(m["title"], m["text"]))
        time.sleep(interval)
    return results


if __name__ == "__main__":
    r = send_markdown("系统上线测试", "经济分析师智能体已部署。\n\n- 数据源：TrendRadar 热榜 + 每日情报日报\n- 推送：钉钉机器人\n- 交易：模拟盘（初始资金 ¥1,000,000）\n\n测试时间：{t}".format(t=time.strftime("%Y-%m-%d %H:%M:%S")))
    print(r)
