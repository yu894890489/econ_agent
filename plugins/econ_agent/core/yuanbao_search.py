"""
元宝搜索（腾讯云 WSA SearchPro API）
用于盘中关键词搜索补充
"""
import os
import hashlib
import hmac
import json
import time
import logging
from datetime import datetime
from http.client import HTTPSConnection

log = logging.getLogger(__name__)


def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def load_keys():
    """从文件加载密钥（cron 环境读不到 shell 环境变量）"""
    key_file = "/root/.openclaw/workspace/econ_agent/.tencent_keys"
    if os.path.exists(key_file):
        with open(key_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()


def search(query: str, count: int = 20) -> list[dict]:
    """
    调用元宝搜索 API
    返回结果列表: [{"title": ..., "url": ..., "snippet": ..., "source": ...}, ...]
    """
    load_keys()  # 从文件加载密钥
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    
    if not secret_id or not secret_key:
        log.error("TENCENTCLOUD_SECRET_ID or TENCENTCLOUD_SECRET_KEY not set")
        return []
    
    service = "wsa"
    host = "wsa.tencentcloudapi.com"
    region = ""
    version = "2025-05-08"
    action = "SearchPro"
    
    # 构造请求参数
    params = {
        "Query": query,
    }
    payload = json.dumps(params)
    endpoint = "https://wsa.tencentcloudapi.com"
    algorithm = "TC3-HMAC-SHA256"
    timestamp = int(time.time())
    date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    
    # 步骤 1：拼接规范请求串
    http_request_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    ct = "application/json; charset=utf-8"
    canonical_headers = "content-type:%s\nhost:%s\nx-tc-action:%s\n" % (ct, host, action.lower())
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (http_request_method + "\n" +
                         canonical_uri + "\n" +
                         canonical_querystring + "\n" +
                         canonical_headers + "\n" +
                         signed_headers + "\n" +
                         hashed_request_payload)
    
    # 步骤 2：拼接待签名字符串
    credential_scope = date + "/" + service + "/" + "tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = (algorithm + "\n" +
                      str(timestamp) + "\n" +
                      credential_scope + "\n" +
                      hashed_canonical_request)
    
    # 步骤 3：计算签名
    secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = sign(secret_date, service)
    secret_signing = sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    
    # 步骤 4：拼接 Authorization
    authorization = (algorithm + " " +
                     "Credential=" + secret_id + "/" + credential_scope + ", " +
                     "SignedHeaders=" + signed_headers + ", " +
                     "Signature=" + signature)
    
    # 步骤 5：构造并发起请求
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version
    }
    if region:
        headers["X-TC-Region"] = region
    
    try:
        req = HTTPSConnection(host, timeout=15)
        req.request("POST", "/", headers=headers, body=payload.encode("utf-8"))
        resp = req.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        
        if "Response" in data:
            resp_data = data["Response"]
            if "Error" in resp_data:
                log.error("Yuanbao search error: %s", resp_data["Error"])
                return []
            
            # 解析结果 - Pages 是 JSON 字符串数组
            results = []
            pages = resp_data.get("Pages", [])
            for page_str in pages:
                try:
                    page = json.loads(page_str)
                    # 每个 page 可能有多个字段，提取关键信息
                    title = page.get("title", page.get("passage", ""))[:200]
                    url = page.get("url", page.get("link", ""))
                    snippet = page.get("snippet", page.get("passage", ""))[:500]
                    source = page.get("source", page.get("site", "yuanbao"))
                    
                    if title:
                        results.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                            "source": source,
                        })
                except json.JSONDecodeError as e:
                    log.warning("Failed to parse page: %s", e)
                    continue
            return results
        else:
            log.error("Unexpected response format: %s", data)
            return []
            
    except Exception as e:
        log.error("Yuanbao search failed: %s", e)
        return []


def search_keywords(keywords: list[str], count_per_query: int = 10) -> list[dict]:
    """
    批量搜索关键词列表
    返回去重后的结果
    """
    seen_urls = set()
    all_results = []
    
    for kw in keywords:
        results = search(kw, count=count_per_query)
        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                r["matched_keyword"] = kw
                all_results.append(r)
        time.sleep(0.5)  # 礼貌间隔
    
    return all_results


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    results = search("AI芯片")
    print(f"Found {len(results)} results")
    for r in results[:3]:
        print(f"  - {r['title'][:50]}...")
        print(f"    {r['url']}")
