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
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from toyoko_watch.service import ToyokoWatchService
from toyoko_watch.web import WebService

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
        self.web = WebService(self.service)
        self._register_web_apis()
        self._scheduler_task: asyncio.Task | None = None

    def _register_web_apis(self) -> None:
        """Register the plugin-page API surface with AstrBot."""
        routes = (
            ("/status", self.page_status, ["GET"], "Toyoko watch status"),
            ("/hotels", self.page_hotels, ["GET"], "Search Toyoko hotels"),
            ("/catalog/refresh", self.page_refresh_catalog, ["POST"], "Refresh hotel catalog"),
            ("/tasks", self.page_save_task, ["POST"], "Save a watch task"),
            ("/tasks/<task_id>/delete", self.page_delete_task, ["POST"], "Delete a watch task"),
            ("/tasks/<task_id>/check", self.page_check_task, ["POST"], "Check one watch task"),
            (
                "/tasks/<task_id>/slots/<slot_id>/state",
                self.page_slot_state,
                ["POST"],
                "Set requirement slot state",
            ),
            ("/rooms/probe", self.page_probe_rooms, ["POST"], "Probe official room names"),
            ("/targets", self.page_save_target, ["POST"], "Save a QQ target"),
            (
                "/targets/<target_id>/delete",
                self.page_delete_target,
                ["POST"],
                "Delete a QQ target",
            ),
            (
                "/targets/<target_id>/test",
                self.page_test_target,
                ["POST"],
                "Test a QQ target",
            ),
            ("/email/test", self.page_test_email, ["POST"], "Test SMTP delivery"),
        )
        for suffix, handler, methods, description in routes:
            self.context.register_web_api(f"/{PLUGIN_NAME}{suffix}", handler, methods, description)

    @staticmethod
    def _page_error(exc: Exception):
        status_code = 404 if isinstance(exc, KeyError) else 400
        return error_response(str(exc).strip("'"), status_code=status_code)

    async def page_status(self):
        """Return plugin status and editable records."""
        return json_response(self.web.snapshot())

    async def page_hotels(self):
        """Search the local hotel catalog."""
        query = request.query.get("q", "")
        limit = request.query.get("limit", 100, type=int)
        return json_response({"hotels": self.web.hotels(query, limit)})

    async def page_refresh_catalog(self):
        """Refresh the local hotel catalog from Toyoko Inn."""
        try:
            return json_response(await self.service.refresh_catalog())
        except Exception as exc:
            logger.exception("东横INN酒店目录刷新失败")
            return self._page_error(exc)

    async def page_save_task(self):
        """Create or replace one watch task."""
        try:
            payload = await request.json(default={})
            return json_response(self.web.save_task(payload))
        except Exception as exc:
            return self._page_error(exc)

    async def page_delete_task(self, task_id: str):
        """Delete one watch task."""
        try:
            return json_response(self.web.delete_task(task_id))
        except Exception as exc:
            return self._page_error(exc)

    async def page_check_task(self, task_id: str):
        """Run one watch task immediately."""
        try:
            return json_response(await self.web.check_task(task_id))
        except Exception as exc:
            return self._page_error(exc)

    async def page_slot_state(self, task_id: str, slot_id: str):
        """Update one requirement slot state."""
        try:
            payload = await request.json(default={})
            return json_response(
                self.web.set_slot_state(task_id, slot_id, str(payload.get("state", "")))
            )
        except Exception as exc:
            return self._page_error(exc)

    async def page_probe_rooms(self):
        """Probe exact official room names for selected hotels and dates."""
        try:
            payload = await request.json(default={})
            result = await self.service.probe_rooms(
                [str(item) for item in payload.get("hotel_ids", [])],
                str(payload.get("checkin", "")),
                str(payload.get("checkout", "")),
                int(payload.get("occupants", 1)),
            )
            return json_response({"results": result})
        except Exception as exc:
            return self._page_error(exc)

    async def page_save_target(self):
        """Create or replace one QQ notification target."""
        try:
            payload = await request.json(default={})
            return json_response(self.web.save_target(payload))
        except Exception as exc:
            return self._page_error(exc)

    async def page_delete_target(self, target_id: str):
        """Delete one QQ notification target."""
        try:
            return json_response(self.web.delete_target(target_id))
        except Exception as exc:
            return self._page_error(exc)

    async def page_test_target(self, target_id: str):
        """Test proactive delivery to one configured QQ target."""
        try:
            return json_response(await self.service.test_target(target_id))
        except Exception as exc:
            return self._page_error(exc)

    async def page_test_email(self):
        """Test SMTP delivery using AstrBot plugin configuration."""
        try:
            return json_response(await self.service.test_email())
        except Exception as exc:
            return self._page_error(exc)

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
                    result = await self.service.check_due()
                    logger.info(
                        f"东横INN检查完成：new_events={result['new_events']}, "
                        f"errors={len(result['errors'])}, pending={result['pending_events']}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("东横INN空房监控循环异常")
            await asyncio.sleep(60 + random.uniform(0, 10))

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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @toyoko.command("catalog-refresh")
    async def toyoko_catalog_refresh(self, event: AstrMessageEvent):
        """Refresh the local hotel catalog from the official list."""
        event.stop_event()
        result = await self.service.refresh_catalog()
        yield event.plain_result(f"酒店目录刷新完成：{result['hotels']} 家。")

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
            "/toyoko catalog-refresh - 从官网刷新酒店目录\n"
            "酒店、日期、房型和需求槽位请在插件 WebUI 中配置。"
        )
