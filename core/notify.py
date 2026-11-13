"""
钉钉推送模块
"""
import json
import time
import logging
import requests
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)

# 默认 webhook（从 econ_agent 复制）
DEFAULT_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=d7b9ba6972dbd851e2b626e7dee87c1e2ccd869d9a19abca010b9ef98bf39dff"
TAG = "【AI】"


class DingTalkNotifier:
    """钉钉通知器"""
    
    def __init__(self, webhook: str = DEFAULT_WEBHOOK):
        self.webhook = webhook
    
    def send_markdown(self, title: str, text: str, retry: int = 2) -> Dict[str, Any]:
        """推送 markdown 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"{TAG}{title}",
                "text": f"{TAG} {text}",
            },
        }
        
        for attempt in range(retry + 1):
            try:
                r = requests.post(self.webhook, json=payload, timeout=10)
                r.raise_for_status()
                res = r.json()
                
                if res.get("errcode") == 0:
                    log.info(f"dingtalk sent: {title}")
                    return {"ok": True}
                
                log.warning(f"dingtalk error: {res.get('errcode')} {res.get('errmsg')}")
                
                if res.get("errcode") == 130101:  # 频率限制
                    time.sleep(5)
                    continue
                
                return {"ok": False, "error": res}
            
            except Exception as e:
                log.error(f"dingtalk request failed: {e} (attempt {attempt})")
                time.sleep(3)
        
        return {"ok": False, "error": "max retries"}
    
    def send_text(self, text: str) -> Dict[str, Any]:
        """推送文本消息"""
        payload = {
            "msgtype": "text",
            "text": {"content": f"{TAG} {text}"}
        }
        
        try:
            r = requests.post(self.webhook, json=payload, timeout=10)
            res = r.json()
            return {"ok": True} if res.get("errcode") == 0 else {"ok": False, "error": res}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def batch_send(self, messages: list, interval: float = 1.5):
        """批量发送消息"""
        results = []
        for m in messages:
            results.append(self.send_markdown(m["title"], m["text"]))
            time.sleep(interval)
        return results


# 全局实例
notifier = DingTalkNotifier()
