"""配置管理"""

import yaml
from pathlib import Path
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class Config:
    """配置管理器"""
    
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
    
    def load(self):
        """加载配置"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            logger.info(f"Loaded config from {self.config_path}")
        else:
            logger.warning(f"Config file not found: {self.config_path}")
            self._config = {}
    
    def save(self):
        """保存配置"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"Saved config to {self.config_path}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """返回配置字典"""
        return self._config.copy()
    
    @classmethod
    def default_config(cls) -> Dict[str, Any]:
        """默认配置"""
        return {
            "database": {
                "path": "./data/econ_harness.db",
            },
            "trendradar": {
                "platforms": [
                    "weibo",
                    "zhihu",
                    "thepaper",
                    "wallstreetcn",
                    "cls",
                ],
                "rss_sources": [],
                "dingtalk_webhook": "",
            },
            "keywords": {
                "p0": [],
                "p1": [],
                "exclude": [],
            },
            "portfolio": {
                "initial_capital": 1000000,
                "max_position": 0.2,
                "max_total_position": 0.9,
                "stop_loss": -0.08,
                "commission_rate": 0.0003,
                "stamp_tax_rate": 0.0005,
            },
            "plugins": {
                "enabled": [
                    "trendradar",
                    "econ_agent",
                    "portfolio",
                    "report",
                    "keyword",
                ],
            },
        }
