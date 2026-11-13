# Econ Harness - 统一经济智能体系统

模块化、可扩展的经济分析智能体框架，整合 TrendRadar、econ_agent、模拟交易等功能。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Econ Harness Core                        │
├─────────────────────────────────────────────────────────────┤
│  Plugin Manager  │  Task Scheduler  │  Event Bus  │  DB     │
├─────────────────────────────────────────────────────────────┤
│                      Plugin Layer                            │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ TrendRadar   │ Econ Agent   │ Portfolio    │ Report         │
│ Plugin       │ Plugin       │ Plugin       │ Plugin         │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ 热榜监控     │ 新闻分析     │ 模拟交易     │ 日报/晨报      │
│ 关键词匹配   │ 信号生成     │ 净值计算     │ HTML/MD 输出   │
│ 钉钉推送     │ 产业链扫描   │ 止损检查     │ 钉钉推送       │
└──────────────┴──────────────┴──────────────┴────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   CLI / API       │
                    └───────────────────┘
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python -m econ_harness init

# 运行所有插件
python -m econ_harness run --all

# 运行单个插件
python -m econ_harness run --plugin trendradar

# 查看状态
python -m econ_harness status

# 手动触发任务
python -m econ_harness task morning-report
python -m econ_harness task evening-snapshot
python -m econ_harness task keyword-monitor
```

## 插件列表

| 插件 | 功能 | 状态 |
|------|------|------|
| `trendradar` | 热榜监控、关键词匹配、钉钉推送 | ✅ |
| `econ_agent` | 新闻分析、信号生成、产业链扫描 | ✅ |
| `portfolio` | 模拟交易、净值计算、止损检查 | ✅ |
| `report` | 日报/晨报生成、HTML 输出 | ✅ |
| `keyword` | 关键词订阅、P0/P1 分级、命中推送 | ✅ |

## 配置

编辑 `config/settings.yaml`：

```yaml
# 数据库
database:
  path: ./data/econ_harness.db

# TrendRadar
trendradar:
  platforms:
    - weibo
    - zhihu
    - thepaper
    - wallstreetcn
    - cls
  rss_sources:
    - name: 华尔街见闻
      url: https://rss.example.com/wsj

# 关键词
keywords:
  p0: [美联储, 加息, 降息, 关税, 制裁]
  p1: [AI, 芯片, 半导体, 新能源]

# 钉钉
dingtalk:
  webhook: https://oapi.dingtalk.com/robot/send?access_token=xxx

# 模拟盘
portfolio:
  initial_capital: 1000000
  max_position: 0.2
  max_total_position: 0.9
  stop_loss: -0.08
```

## 开发插件

创建 `plugins/my_plugin/__init__.py`：

```python
from econ_harness.core.plugin import BasePlugin

class MyPlugin(BasePlugin):
    name = "my_plugin"
    version = "1.0.0"
    
    async def on_start(self):
        """插件启动时调用"""
        pass
    
    async def on_task(self, task_name: str, **kwargs):
        """接收任务"""
        if task_name == "my_task":
            await self.do_something()
    
    async def do_something(self):
        """你的逻辑"""
        pass
```

注册插件：在 `config/settings.yaml` 添加：

```yaml
plugins:
  enabled:
    - my_plugin
```

## 命令参考

```bash
# 系统管理
econ-harness init              # 初始化数据库
econ-harness status            # 查看系统状态
econ-harness config show       # 显示配置
econ-harness config edit       # 编辑配置

# 任务执行
econ-harness run --all         # 运行所有插件
econ-harness run --plugin <name>  # 运行指定插件
econ-harness task <name>       # 手动触发任务

# 数据查询
econ-harness query signals     # 查看信号
econ-harness query portfolio   # 查看持仓
econ-harness query nav         # 查看净值
econ-harness query keywords    # 查看关键词命中

# 报告生成
econ-harness report daily      # 生成日报
econ-harness report morning    # 生成晨报
econ-harness report evening    # 生成收盘报告
```

## 迁移指南

从旧系统迁移：

1. 复制数据库：
```bash
cp /root/.openclaw/workspace/econ_agent/data/econ_agent.db ./data/
cp /root/.openclaw/workspace/trendradar/output/*.db ./data/
```

2. 复制配置：
```bash
cp /root/.openclaw/workspace/econ_agent/config/* ./config/
cp /root/.openclaw/workspace/trendradar/config/* ./config/
```

3. 运行迁移脚本：
```bash
python -m econ_harness migrate
```

## License

MIT
