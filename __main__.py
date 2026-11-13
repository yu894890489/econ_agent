"""Econ Harness CLI 入口"""

import asyncio
import click
from pathlib import Path
import sys

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from econ_harness.core.config import Config
from econ_harness.core.database import Database
from econ_harness.core.plugin import PluginManager
from econ_harness.core.scheduler import TaskScheduler
from econ_harness.core.event_bus import EventBus


@click.group()
@click.option("--config", "-c", default="config/settings.yaml", help="配置文件路径")
@click.pass_context
def cli(ctx, config):
    """Econ Harness - 统一经济智能体系统"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command()
@click.pass_context
def init(ctx):
    """初始化数据库和配置"""
    config_path = ctx.obj["config_path"]
    config = Config(config_path)
    
    if not config.config_path.exists():
        click.echo("Creating default config...")
        default = Config.default_config()
        config._config = default
        config.save()
    
    db = Database(config.get("database.path", "./data/econ_harness.db"))
    
    async def _init():
        await db.connect()
        await db.init_schema()
        await db.close()
    
    asyncio.run(_init())
    click.echo("✓ Database initialized")
    click.echo(f"✓ Config saved to {config_path}")


@cli.command()
@click.pass_context
def status(ctx):
    """查看系统状态"""
    config_path = ctx.obj["config_path"]
    config = Config(config_path)
    config.load()
    
    click.echo("Econ Harness Status")
    click.echo("=" * 50)
    click.echo(f"Config: {config_path}")
    click.echo(f"Database: {config.get('database.path')}")
    click.echo(f"Plugins: {', '.join(config.get('plugins.enabled', []))}")
    click.echo()
    
    # TODO: 显示运行状态


@cli.command()
@click.option("--all", "run_all", is_flag=True, help="运行所有插件")
@click.option("--plugin", "-p", help="运行指定插件")
@click.pass_context
def run(ctx, run_all, plugin):
    """运行插件"""
    if not run_all and not plugin:
        click.echo("Error: Specify --all or --plugin <name>")
        return
    
    click.echo(f"Running: {'all plugins' if run_all else f'plugin {plugin}'}")
    # TODO: 实现运行逻辑


@cli.command()
@click.argument("task_name")
@click.pass_context
def task(ctx, task_name):
    """手动触发任务"""
    click.echo(f"Triggering task: {task_name}")
    # TODO: 实现任务触发


@cli.group()
def query():
    """数据查询"""
    pass


@query.command()
@click.pass_context
def signals(ctx):
    """查看信号"""
    click.echo("Signals:")
    # TODO: 查询并显示信号


@query.command()
@click.pass_context
def portfolio(ctx):
    """查看持仓"""
    click.echo("Portfolio:")
    # TODO: 查询并显示持仓


@query.command()
@click.pass_context
def nav(ctx):
    """查看净值"""
    click.echo("NAV:")
    # TODO: 查询并显示净值


@cli.group()
def report():
    """报告生成"""
    pass


@report.command()
@click.pass_context
def daily(ctx):
    """生成日报"""
    click.echo("Generating daily report...")
    # TODO: 实现日报生成


@report.command()
@click.pass_context
def morning(ctx):
    """生成晨报"""
    click.echo("Generating morning report...")
    # TODO: 实现晨报生成


if __name__ == "__main__":
    cli()
