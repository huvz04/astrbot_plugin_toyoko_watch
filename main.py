"""AstrBot entry point for the Toyoko Inn availability monitor."""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from toyoko_watch.service import ToyokoWatchService

PLUGIN_NAME = "astrbot_plugin_toyoko_watch"


class ToyokoWatchPlugin(Star):
    """Manage the scheduler, commands, and proactive AstrBot delivery."""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context, config)
        self.context = context
        self.config = config or {}
        self.plugin_dir = Path(__file__).resolve().parent
        seed = json.loads(
            (self.plugin_dir / "data" / "hotels.seed.json").read_text(encoding="utf-8")
        )
        data_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.service = ToyokoWatchService(
            data_dir=data_dir,
            seed_catalog=seed,
            config=self.config,
            qq_sender=self._send_qq,
        )
        self._scheduler_task: asyncio.Task | None = None

    async def _send_qq(self, umo: str, text: str) -> bool:
        """Send a plain proactive message through AstrBot."""
        result = await self.context.send_message(umo, MessageChain().message(text))
        return bool(result)

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        """Start the monitor after platform adapters are initialized."""
        self._ensure_scheduler()

    def _ensure_scheduler(self) -> None:
        """Create exactly one background scheduler task."""
        if self._scheduler_task and not self._scheduler_task.done():
            return
        self._scheduler_task = asyncio.create_task(self._scheduler())
        logger.info("东横INN空房监控后台任务已启动")

    async def _scheduler(self) -> None:
        """Run checks continuously without terminating on one cycle error."""
        while True:
            try:
                if self.config.get("enabled", True):
                    result = await self.service.check_all()
                    logger.info(
                        f"东横INN检查完成：new_events={result['new_events']}, "
                        f"errors={len(result['errors'])}, pending={result['pending_events']}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("东横INN空房监控循环异常")
            interval = min(3600, max(60, int(self.config.get("interval_seconds", 300))))
            await asyncio.sleep(interval + random.uniform(0, 10))

    async def terminate(self):
        """Cancel and await the background monitor during unload."""
        if self._scheduler_task:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None

    @filter.command_group("toyoko")
    def toyoko(self):
        """东横INN空房监控。"""

    @toyoko.command("status")
    async def toyoko_status(self, event: AstrMessageEvent):
        """Show scheduler and monitoring status."""
        event.stop_event()
        status = self.service.status()
        scheduler_alive = bool(self._scheduler_task and not self._scheduler_task.done())
        lines = [
            "东横INN空房监控状态",
            f"scheduler_alive: {scheduler_alive}",
            f"hotels: {status['hotels']}",
            f"tasks: {status['enabled_tasks']}/{status['tasks']}",
            f"active_slots: {status['active_slots']}",
            f"targets: {status['targets']}",
            f"pending_events: {status['pending_events']}",
            f"last_check: {status['last_check'] or '尚未检查'}",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @toyoko.command("bind")
    async def toyoko_bind(self, event: AstrMessageEvent):
        """Bind the current private chat or group as a reusable target."""
        event.stop_event()
        group_id = str(event.get_group_id() or "")
        if group_id:
            kind = "group"
            number = group_id
            label = f"QQ群 {group_id}"
        else:
            kind = "private"
            number = str(event.get_sender_id())
            label = f"QQ私聊 {number}"
        target_id = f"{kind}-{number}"
        target = self.service.save_target(
            {
                "id": target_id,
                "label": label,
                "kind": kind,
                "number": number,
                "enabled": True,
            }
        )
        yield event.plain_result(
            f"已绑定通知目标：{target.label}\n{target.umo}\n请在插件 WebUI 的任务中勾选该目标。"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @toyoko.command("test")
    async def toyoko_test(self, event: AstrMessageEvent):
        """Test proactive delivery to the current conversation."""
        event.stop_event()
        message = "【测试】东横INN空房监控主动消息发送成功。"
        ok = await self.context.send_message(
            event.unified_msg_origin, MessageChain().message(message)
        )
        yield event.plain_result(f"主动发送结果：{'成功' if ok else '失败'}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @toyoko.command("check")
    async def toyoko_check(self, event: AstrMessageEvent):
        """Run all enabled monitoring tasks immediately."""
        event.stop_event()
        result = await self.service.check_all()
        yield event.plain_result(
            f"检查完成：新命中 {result['new_events']}，错误 {len(result['errors'])}，"
            f"待投递 {result['pending_events']}。"
        )

    @toyoko.command("help")
    async def toyoko_help(self, event: AstrMessageEvent):
        """Show concise plugin commands."""
        event.stop_event()
        yield event.plain_result(
            "东横INN空房监控\n"
            "/toyoko status - 查看状态\n"
            "/toyoko bind - 绑定当前私聊或群聊\n"
            "/toyoko test - 测试当前会话主动消息\n"
            "/toyoko check - 立即检查全部任务\n"
            "酒店、日期、房型和需求槽位请在插件 WebUI 中配置。"
        )
