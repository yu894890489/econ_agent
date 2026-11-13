"""
简单示例：直接推送消息到钉钉
"""
import sys
sys.path.insert(0, '/root/.openclaw/workspace/econ_harness')

from core.notify import notifier


def main():
    # 推送 TrendRadar 摘要
    print("推送 TrendRadar 摘要...")
    result = notifier.send_markdown(
        "TrendRadar 实时监控",
        """## 📊 TrendRadar 监控报告

### 监控结果
- 总新闻数: 150
- 关键词命中: 5 条
- 命中关键词: 美联储、加息、黄金

### 最新动态
- 美联储鹰派信号强化
- 地缘政治风险升温

---
*数据来源：TrendRadar*
"""
    )
    print(f"结果: {result}")
    
    # 推送经济分析
    print("\n推送经济分析...")
    result = notifier.send_markdown(
        "经济分析师晨报",
        """## 🌅 经济分析师晨报

### 今日主线
1. 美联储鹰派信号强化
2. 地缘政治风险升温
3. AI 产业链持续景气

### 板块研判
- **能源**: 油价上涨，关注中远海能
- **黄金**: 避险需求支撑
- **科技**: AI 算力需求确认

### 信号
- 无新信号

---
*数据来源：econ_agent*
"""
    )
    print(f"结果: {result}")
    
    print("\n✅ 推送完成！")


if __name__ == "__main__":
    main()
