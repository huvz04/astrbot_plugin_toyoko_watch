import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


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
