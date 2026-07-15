import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def install_astrbot_stubs(monkeypatch, tmp_path: Path):
    astrbot = ModuleType("astrbot")
    api = ModuleType("astrbot.api")
    event = ModuleType("astrbot.api.event")
    star = ModuleType("astrbot.api.star")
    web = ModuleType("astrbot.api.web")
    core = ModuleType("astrbot.core")
    utils = ModuleType("astrbot.core.utils")
    path_module = ModuleType("astrbot.core.utils.astrbot_path")

    class AstrBotConfig(dict):
        pass

    class Star:
        def __init__(self, context, config=None):
            self.context = context
            self.config = config

    class MessageChain:
        def __init__(self):
            self.text = ""

        def message(self, text):
            self.text = text
            return self

    def passthrough_decorator(*_args, **_kwargs):
        def decorate(function):
            return function

        return decorate

    def command_group(*_args, **_kwargs):
        def decorate(function):
            function.command = passthrough_decorator
            return function

        return decorate

    api.AstrBotConfig = AstrBotConfig
    api.logger = SimpleNamespace(
        info=lambda *_: None, warning=lambda *_: None, exception=lambda *_: None
    )
    event.AstrMessageEvent = object
    event.MessageChain = MessageChain
    event.filter = SimpleNamespace(
        command_group=command_group,
        permission_type=passthrough_decorator,
        on_astrbot_loaded=passthrough_decorator,
        PermissionType=SimpleNamespace(ADMIN="admin"),
    )
    star.Context = object
    star.Star = Star
    web.request = SimpleNamespace(query={}, json=None)
    web.json_response = lambda value: value
    web.error_response = lambda message, status_code=400: {
        "status": "error",
        "message": message,
        "status_code": status_code,
    }
    path_module.get_astrbot_plugin_data_path = lambda: str(tmp_path)

    for name, module in {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.star": star,
        "astrbot.api.web": web,
        "astrbot.core": core,
        "astrbot.core.utils": utils,
        "astrbot.core.utils.astrbot_path": path_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


class FakeEvent:
    def __init__(self, group_id="", sender_id="12345"):
        self.group_id = group_id
        self.sender_id = sender_id
        self.stopped = False

    def stop_event(self):
        self.stopped = True

    def get_group_id(self):
        return self.group_id

    def get_sender_id(self):
        return self.sender_id

    def plain_result(self, text):
        return text


async def collect(generator):
    return [item async for item in generator]


@pytest.fixture
def plugin(monkeypatch, tmp_path):
    install_astrbot_stubs(monkeypatch, tmp_path)
    sys.modules.pop("main", None)
    plugin_module = importlib.import_module("main")
    context = SimpleNamespace(
        send_message=AsyncMock(return_value=True),
        register_web_api=lambda *_args: None,
    )
    return plugin_module.ToyokoWatchPlugin(context, {"enabled": False})


def test_plugin_imports_and_builds_service_with_astrbot_api(monkeypatch, tmp_path):
    install_astrbot_stubs(monkeypatch, tmp_path)
    sys.modules.pop("main", None)
    plugin_module = importlib.import_module("main")
    routes = []
    context = SimpleNamespace(
        send_message=None,
        register_web_api=lambda *args: routes.append(args),
    )

    plugin = plugin_module.ToyokoWatchPlugin(context, {"enabled": False})

    assert plugin.service.status()["hotels"] >= 2
    assert plugin._scheduler_task is None
    assert {route[0] for route in routes} >= {
        "/astrbot_plugin_toyoko_watch/status",
        "/astrbot_plugin_toyoko_watch/tasks",
        "/astrbot_plugin_toyoko_watch/rooms/probe",
        "/astrbot_plugin_toyoko_watch/targets/<target_id>/test",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["toyoko_check", "toyoko_add", "toyoko_list"])
async def test_hotel_commands_require_five_digit_id(plugin, command):
    replies = await collect(getattr(plugin, command)(FakeEvent(), ""))

    assert replies == ["必须提供 5 位酒店编号，例如 00075。"]


@pytest.mark.asyncio
async def test_booked_and_restore_change_exact_slot(plugin):
    event = FakeEvent()

    booked = await collect(plugin.toyoko_booked(event, "yokohama-sat", "single"))
    task = next(item for item in plugin.service.tasks if item.id == "yokohama-sat")
    assert task.slots[0].state == "fulfilled"
    assert "已标记为已订到" in booked[0]

    restored = await collect(plugin.toyoko_restore(event, "yokohama-sat", "single"))
    assert task.slots[0].state == "active"
    assert "已恢复监控" in restored[0]


@pytest.mark.asyncio
async def test_add_binds_current_group_and_runs_immediately(plugin, monkeypatch):
    event = FakeEvent(group_id="67890")
    monkeypatch.setattr(
        sys.modules["main"],
        "parse_quick_stay",
        lambda _start, _end: ("2026-11-06", "2026-11-08"),
    )
    task = SimpleNamespace(id="quick-00075-20261106-20261108")
    plugin.service.create_quick_task = MagicMock(return_value=task)
    plugin.service.check_all = AsyncMock(
        return_value={"new_events": 0, "errors": [], "pending_events": 0}
    )

    replies = await collect(plugin.toyoko_add(event, "00075", "1106", "1108"))

    assert "00075" in replies[0]
    assert "2026-11-06" in replies[0]
    assert plugin.service.targets[-1].umo == "aiocqhttp:GroupMessage:67890"
    plugin.service.check_all.assert_awaited_once_with(task.id)


@pytest.mark.asyncio
async def test_check_calls_hotel_scoped_service(plugin):
    plugin.service.check_hotel = AsyncMock(
        return_value={
            "checked_tasks": 1,
            "new_events": 0,
            "errors": [],
            "pending_events": 0,
        }
    )

    replies = await collect(plugin.toyoko_check(FakeEvent(), "00075"))

    plugin.service.check_hotel.assert_awaited_once_with("00075")
    assert "酒店 00075 检查完成" in replies[0]


@pytest.mark.asyncio
async def test_check_without_enabled_task_suggests_add(plugin):
    plugin.service.check_hotel = AsyncMock(
        return_value={
            "checked_tasks": 0,
            "new_events": 0,
            "errors": [],
            "pending_events": 0,
        }
    )

    replies = await collect(plugin.toyoko_check(FakeEvent(), "00075"))

    assert "/toyoko add 00075" in replies[0]


@pytest.mark.asyncio
async def test_list_exposes_task_and_slot_ids(plugin):
    replies = await collect(plugin.toyoko_list(FakeEvent(), "00075"))

    assert "任务ID：yokohama-sat" in replies[0]
    assert "需求ID：single" in replies[0]
