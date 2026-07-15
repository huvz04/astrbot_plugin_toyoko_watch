# QQ Quick Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe QQ commands for creating a basic persistent hotel watch, checking one hotel, listing configured requirements, and marking one requirement booked or active again.

**Architecture:** Put deterministic date parsing and quick-task construction in a new framework-neutral `toyoko_watch.quick` module. Extend `ToyokoWatchService` with hotel-scoped discovery and checking while reusing the current monitor, transition state, delivery, and JSON models; keep AstrBot argument parsing, current-conversation binding, permissions, and reply text in `main.py`.

**Tech Stack:** Python 3.10+, AstrBot >=4.26.0-beta.8, OneBot v11 `aiocqhttp`, pytest, pytest-asyncio, Ruff.

## Global Constraints

- `add`, `check`, and `list` require a five-digit hotel ID and emit `必须提供 5 位酒店编号，例如 00075。` when it is absent or malformed.
- `MMDD` means the nearest non-past Asia/Shanghai calendar occurrence; checkout rolls into the following year when needed.
- Quick tasks use the existing task/target/state JSON files and remain editable in WebUI.
- `check <hotel_id>` must never fetch other hotels selected by the same tasks.
- `booked` and `restore` change exactly one task slot through `set_slot_state`.
- Mutating or network-triggering commands remain administrator-only.
- Existing standalone Windows scripts and untracked files must not be modified or published.

---

### Task 1: Quick-stay parsing and standard task construction

**Files:**
- Create: `toyoko_watch/quick.py`
- Create: `tests/test_quick.py`

**Interfaces:**
- Produces: `parse_quick_stay(checkin_mmdd: str, checkout_mmdd: str, today: date | None = None) -> tuple[str, str]`.
- Produces: `quick_task_id(hotel_id: str, checkin: str, checkout: str) -> str`.
- Produces: `build_quick_task(hotel_id: str, hotel_name: str, checkin: str, checkout: str, target_id: str, interval_seconds: int = 300) -> dict[str, Any]`.

- [ ] **Step 1: Write failing date parsing tests**

```python
from datetime import date

import pytest

from toyoko_watch.quick import parse_quick_stay


def test_quick_dates_use_nearest_future_occurrence():
    assert parse_quick_stay("1106", "1108", date(2026, 7, 15)) == (
        "2026-11-06",
        "2026-11-08",
    )


def test_quick_dates_roll_past_checkin_and_cross_year_checkout():
    assert parse_quick_stay("0106", "0108", date(2026, 7, 15)) == (
        "2027-01-06",
        "2027-01-08",
    )
    assert parse_quick_stay("1231", "0102", date(2026, 7, 15)) == (
        "2026-12-31",
        "2027-01-02",
    )


@pytest.mark.parametrize(("start", "end"), [("1131", "1201"), ("1106", "1106"), ("1106", "1207")])
def test_quick_dates_reject_invalid_or_out_of_range_stays(start, end):
    with pytest.raises(ValueError):
        parse_quick_stay(start, end, date(2026, 7, 15))
```

- [ ] **Step 2: Run the date tests and verify RED**

Run: `python -m pytest tests/test_quick.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'toyoko_watch.quick'`.

- [ ] **Step 3: Implement strict MMDD parsing**

```python
from datetime import date
from zoneinfo import ZoneInfo
from datetime import datetime


def _calendar_date(value: str, year: int) -> date:
    if len(value) != 4 or not value.isdigit():
        raise ValueError("date must use MMDD")
    return date(year, int(value[:2]), int(value[2:]))


def parse_quick_stay(checkin_mmdd: str, checkout_mmdd: str, today: date | None = None) -> tuple[str, str]:
    current = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    checkin = _calendar_date(checkin_mmdd, current.year)
    if checkin < current:
        checkin = _calendar_date(checkin_mmdd, current.year + 1)
    checkout = _calendar_date(checkout_mmdd, checkin.year)
    if checkout <= checkin:
        checkout = _calendar_date(checkout_mmdd, checkin.year + 1)
    nights = (checkout - checkin).days
    if not 1 <= nights <= 30:
        raise ValueError("stay must be between 1 and 30 nights")
    return checkin.isoformat(), checkout.isoformat()
```

- [ ] **Step 4: Add failing task-construction tests**

```python
from toyoko_watch.quick import build_quick_task, quick_task_id


def test_quick_task_contains_single_and_multi_defaults():
    data = build_quick_task(
        "00075", "東横INN横浜スタジアム前1", "2026-11-06", "2026-11-08", "private-123"
    )
    assert data["id"] == quick_task_id("00075", "2026-11-06", "2026-11-08")
    assert data["hotel_ids"] == ["00075"]
    assert data["target_ids"] == ["private-123"]
    assert data["enabled"] is True
    assert [(slot["id"], slot["occupants"]) for slot in data["slots"]] == [
        ("single", 1),
        ("multi", 2),
    ]
```

- [ ] **Step 5: Run the construction test and verify RED**

Run: `python -m pytest tests/test_quick.py::test_quick_task_contains_single_and_multi_defaults -q`

Expected: import or attribute failure for `build_quick_task`.

- [ ] **Step 6: Implement deterministic task construction**

```python
def quick_task_id(hotel_id: str, checkin: str, checkout: str) -> str:
    return f"quick-{hotel_id}-{checkin.replace('-', '')}-{checkout.replace('-', '')}"


def build_quick_task(hotel_id, hotel_name, checkin, checkout, target_id, interval_seconds=300):
    return {
        "id": quick_task_id(hotel_id, checkin, checkout),
        "name": f"快捷监控 {hotel_name} {checkin} 至 {checkout}",
        "enabled": True,
        "hotel_ids": [hotel_id],
        "checkin": checkin,
        "checkout": checkout,
        "slots": [
            {"id": "single", "label": "全部单人房", "state": "active", "category": "single", "subtypes": ["economy_single", "standard_single", "large_single"], "exact_names": [], "keywords": [], "occupants": 1, "smoking": "any", "inventory": "either"},
            {"id": "multi", "label": "全部多人房", "state": "active", "category": "multi", "subtypes": ["economy_double", "double", "twin", "triple"], "exact_names": [], "keywords": [], "occupants": 2, "smoking": "any", "inventory": "either"},
        ],
        "target_ids": [target_id],
        "email_enabled": False,
        "notify_changes": False,
        "interval_seconds": min(3600, max(60, int(interval_seconds))),
    }
```

- [ ] **Step 7: Run quick tests, Ruff, and commit**

Run: `python -m pytest tests/test_quick.py -q && python -m ruff check toyoko_watch/quick.py tests/test_quick.py`

Expected: all quick tests pass and Ruff reports no errors.

```bash
git add toyoko_watch/quick.py tests/test_quick.py
git commit -m "feat: add QQ quick task parsing"
```

### Task 2: Hotel-scoped task service and checking

**Files:**
- Modify: `toyoko_watch/service.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: `build_quick_task(...)` and existing `WatchTask`, `MonitorService`, `save_task`, and delivery state.
- Produces: `tasks_for_hotel(hotel_id: str, enabled_only: bool = False) -> list[WatchTask]`.
- Produces: `create_quick_task(hotel_id: str, checkin: str, checkout: str, target_id: str) -> WatchTask`.
- Produces: `check_hotel(hotel_id: str) -> dict[str, Any]`.

- [ ] **Step 1: Write failing discovery and duplicate tests**

```python
def test_tasks_for_hotel_can_include_disabled_tasks(tmp_path):
    service = make_service(tmp_path)
    assert len(service.tasks_for_hotel("00075")) == 2
    assert service.tasks_for_hotel("00075", enabled_only=True) == []


def test_create_quick_task_rejects_unknown_hotel_and_duplicate(tmp_path):
    service = make_service(tmp_path)
    service.save_target(target())
    with pytest.raises(ValueError, match="unknown hotel"):
        service.create_quick_task("99999", "2026-11-06", "2026-11-08", "private")
    service.create_quick_task("00075", "2026-11-06", "2026-11-08", "private")
    with pytest.raises(ValueError, match="already exists"):
        service.create_quick_task("00075", "2026-11-06", "2026-11-08", "private")
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_service.py -k "tasks_for_hotel or create_quick_task" -q`

Expected: `AttributeError` for the missing service methods.

- [ ] **Step 3: Implement discovery and creation using the local catalog**

```python
def tasks_for_hotel(self, hotel_id: str, enabled_only: bool = False) -> list[WatchTask]:
    normalized = str(hotel_id).zfill(5)
    return [
        task for task in self.tasks
        if normalized in task.hotel_ids and (task.enabled or not enabled_only)
    ]


def create_quick_task(self, hotel_id, checkin, checkout, target_id):
    normalized = str(hotel_id).zfill(5)
    hotel = next((item for item in self.hotels if item["hotel_id"] == normalized), None)
    if hotel is None:
        raise ValueError(f"unknown hotel: {normalized}")
    data = build_quick_task(normalized, hotel["name"], checkin, checkout, target_id, self.config.get("interval_seconds", 300))
    if any(task.id == data["id"] for task in self.tasks):
        raise ValueError(f"quick task already exists: {data['id']}")
    return self.save_task(data)
```

- [ ] **Step 4: Write a failing hotel-scoped check test**

```python
@pytest.mark.asyncio
async def test_check_hotel_fetches_only_requested_hotel(tmp_path):
    service = make_service(tmp_path)
    service.save_target(target())
    data = enabled_task()
    data["hotel_ids"] = ["00075", "00073"]
    service.save_task(data)
    service.client.calls.clear()

    result = await service.check_hotel("00075")

    assert result["checked_tasks"] == 1
    assert {hotel_id for hotel_id, _occupants in service.client.calls} == {"00075"}
```

- [ ] **Step 5: Run the scoped check and verify RED**

Run: `python -m pytest tests/test_service.py::test_check_hotel_fetches_only_requested_hotel -q`

Expected: `AttributeError: 'ToyokoWatchService' object has no attribute 'check_hotel'`.

- [ ] **Step 6: Extract common execution and implement hotel-scoped clones**

Refactor the body shared by `check_all` and `check_hotel` into:

```python
async def _run_tasks(self, tasks: list[WatchTask]) -> dict[str, Any]:
    new_events = 0
    errors: list[dict[str, str]] = []
    for task in tasks:
        events, task_errors = await self.monitor.run_task(task)
        errors.extend(task_errors)
        for event in events:
            event_id = self._event_id(event)
            self.pending_events[event_id] = {
                "event": event.to_dict(),
                "target_ids": list(task.target_ids),
                "email_enabled": task.email_enabled,
            }
            new_events += 1
    await self._deliver_pending()
    self.last_check = datetime.now(timezone.utc).isoformat()
    for task in tasks:
        self.task_last_checks[task.id] = self.last_check
    self.last_errors = errors[-50:]
    self._save_state()
    return {
        "checked_tasks": len(tasks),
        "new_events": new_events,
        "errors": errors,
        "pending_events": len(self.pending_events),
        "last_check": self.last_check,
    }


async def check_hotel(self, hotel_id: str) -> dict[str, Any]:
    normalized = str(hotel_id).zfill(5)
    scoped = []
    for task in self.tasks_for_hotel(normalized, enabled_only=True):
        data = task.to_dict()
        data["hotel_ids"] = [normalized]
        scoped.append(WatchTask.from_dict(data))
    return await self._run_tasks(scoped)


async def check_all(self, task_id: str | None = None) -> dict[str, Any]:
    tasks = [self._task(task_id)] if task_id else [item for item in self.tasks if item.enabled]
    return await self._run_tasks(tasks)
```

- [ ] **Step 7: Run service regression tests and commit**

Run: `python -m pytest tests/test_service.py -q && python -m ruff check toyoko_watch/service.py tests/test_service.py`

Expected: all service tests pass and Ruff reports no errors.

```bash
git add toyoko_watch/service.py tests/test_service.py
git commit -m "feat: add hotel-scoped quick monitoring"
```

### Task 3: AstrBot QQ commands, replies, and documentation

**Files:**
- Modify: `main.py`
- Modify: `tests/test_plugin_import.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `parse_quick_stay`, `ToyokoWatchService.create_quick_task`, `tasks_for_hotel`, `check_hotel`, and `set_slot_state`.
- Produces: `/toyoko add`, hotel-required `/toyoko check`, `/toyoko list`, `/toyoko booked`, `/toyoko restore`, and updated `/toyoko help`.

- [ ] **Step 1: Add failing handler tests for mandatory IDs and state commands**

Add an event fake and async-generator collector:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest


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


@pytest.mark.asyncio
async def test_check_requires_five_digit_hotel_id(plugin):
    replies = await collect(plugin.toyoko_check(FakeEvent(), ""))
    assert replies == ["必须提供 5 位酒店编号，例如 00075。"]


@pytest.mark.asyncio
async def test_booked_and_restore_change_exact_slot(plugin):
    plugin.service.set_slot_state = MagicMock(return_value=SimpleNamespace(name="横滨", slots=[SimpleNamespace(id="single", label="单人房", state="fulfilled")]))
    replies = await collect(plugin.toyoko_booked(FakeEvent(), "task", "single"))
    plugin.service.set_slot_state.assert_called_once_with("task", "single", "fulfilled")
    assert "已订到" in replies[0]
```

Use this fixture to exercise the real decorated methods while keeping AstrBot itself stubbed:

```python
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
```

- [ ] **Step 2: Run handler tests and verify RED**

Run: `python -m pytest tests/test_plugin_import.py -k "check_requires or booked_and_restore" -q`

Expected: command signature mismatch and missing `toyoko_booked` method.

- [ ] **Step 3: Refactor current-conversation target extraction**

```python
@staticmethod
def _target_from_event(event: AstrMessageEvent) -> dict[str, object]:
    group_id = str(event.get_group_id() or "")
    kind = "group" if group_id else "private"
    number = group_id or str(event.get_sender_id())
    return {
        "id": f"{kind}-{number}",
        "label": f"QQ群 {number}" if kind == "group" else f"QQ私聊 {number}",
        "kind": kind,
        "number": number,
        "enabled": True,
    }
```

Make `/toyoko bind` use this helper without changing its reply.

- [ ] **Step 4: Implement argument validation and commands**

Use default empty arguments on every new handler. The command behavior is:

```python
HOTEL_ID_REQUIRED = "必须提供 5 位酒店编号，例如 00075。"


@staticmethod
def _valid_hotel_id(value: str) -> str | None:
    return value if len(value) == 5 and value.isdigit() else None


@filter.permission_type(filter.PermissionType.ADMIN)
@toyoko.command("check")
async def toyoko_check(self, event, hotel_id: str = ""):
    event.stop_event()
    normalized = self._valid_hotel_id(hotel_id)
    if normalized is None:
        yield event.plain_result(HOTEL_ID_REQUIRED)
        return
    result = await self.service.check_hotel(normalized)
    if result["checked_tasks"] == 0:
        yield event.plain_result(
            f"酒店 {normalized} 没有已启用任务，请使用 /toyoko add "
            f"{normalized} <入住MMDD> <退房MMDD> 或在 WebUI 配置。"
        )
        return
    yield event.plain_result(
        f"酒店 {normalized} 检查完成：任务 {result['checked_tasks']}，"
        f"新命中 {result['new_events']}，错误 {len(result['errors'])}，"
        f"待投递 {result['pending_events']}。"
    )


@filter.permission_type(filter.PermissionType.ADMIN)
@toyoko.command("add")
async def toyoko_add(self, event, hotel_id: str = "", checkin: str = "", checkout: str = ""):
    event.stop_event()
    normalized = self._valid_hotel_id(hotel_id)
    if normalized is None:
        yield event.plain_result(HOTEL_ID_REQUIRED)
        return
    try:
        checkin_iso, checkout_iso = parse_quick_stay(checkin, checkout)
        target = self.service.save_target(self._target_from_event(event))
        task = self.service.create_quick_task(
            normalized, checkin_iso, checkout_iso, target.id
        )
        result = await self.service.check_all(task.id)
    except (KeyError, ValueError) as exc:
        yield event.plain_result(str(exc).strip("'"))
        return
    yield event.plain_result(
        f"快捷任务已创建并检查：{task.id}\n"
        f"酒店：{normalized}\n日期：{checkin_iso} 至 {checkout_iso}\n"
        f"新命中 {result['new_events']}，错误 {len(result['errors'])}，"
        f"待投递 {result['pending_events']}。"
    )


@toyoko.command("list")
async def toyoko_list(self, event, hotel_id: str = ""):
    event.stop_event()
    normalized = self._valid_hotel_id(hotel_id)
    if normalized is None:
        yield event.plain_result(HOTEL_ID_REQUIRED)
        return
    tasks = self.service.tasks_for_hotel(normalized)
    if not tasks:
        yield event.plain_result(f"酒店 {normalized} 还没有监控任务。")
        return
    lines = [f"酒店 {normalized} 的监控任务"]
    for task in tasks:
        lines.append(
            f"任务ID：{task.id}｜{'启用' if task.enabled else '停用'}｜"
            f"{task.checkin} 至 {task.checkout}"
        )
        for slot in task.slots:
            lines.append(
                f"  需求ID：{slot.id}｜{slot.label}｜{slot.state}"
            )
    yield event.plain_result("\n".join(lines))


@filter.permission_type(filter.PermissionType.ADMIN)
@toyoko.command("booked")
async def toyoko_booked(self, event, task_id: str = "", slot_id: str = ""):
    event.stop_event()
    if not task_id or not slot_id:
        yield event.plain_result("用法：/toyoko booked <任务ID> <需求ID>")
        return
    try:
        task = self.service.set_slot_state(task_id, slot_id, "fulfilled")
        slot = next(item for item in task.slots if item.id == slot_id)
    except (KeyError, ValueError) as exc:
        yield event.plain_result(str(exc).strip("'"))
        return
    yield event.plain_result(f"已标记为已订到：{task.name} / {slot.label}")


@filter.permission_type(filter.PermissionType.ADMIN)
@toyoko.command("restore")
async def toyoko_restore(self, event, task_id: str = "", slot_id: str = ""):
    event.stop_event()
    if not task_id or not slot_id:
        yield event.plain_result("用法：/toyoko restore <任务ID> <需求ID>")
        return
    try:
        task = self.service.set_slot_state(task_id, slot_id, "active")
        slot = next(item for item in task.slots if item.id == slot_id)
    except (KeyError, ValueError) as exc:
        yield event.plain_result(str(exc).strip("'"))
        return
    yield event.plain_result(f"已恢复监控：{task.name} / {slot.label}")
```

Catch `ValueError` and `KeyError` and return their concise messages rather than propagating command exceptions.

- [ ] **Step 5: Add successful add/list/check handler tests**

```python
@pytest.mark.asyncio
async def test_add_binds_current_group_and_runs_immediately(plugin, monkeypatch):
    event = FakeEvent(group_id="67890")
    monkeypatch.setattr(
        sys.modules["main"],
        "parse_quick_stay",
        lambda _start, _end: ("2026-11-06", "2026-11-08"),
    )
    target = SimpleNamespace(id="group-67890", umo="aiocqhttp:GroupMessage:67890")
    task = SimpleNamespace(id="quick-00075-20261106-20261108")
    plugin.service.save_target = MagicMock(return_value=target)
    plugin.service.create_quick_task = MagicMock(return_value=task)
    plugin.service.check_all = AsyncMock(
        return_value={"new_events": 0, "errors": [], "pending_events": 0}
    )

    replies = await collect(plugin.toyoko_add(event, "00075", "1106", "1108"))

    assert "00075" in replies[0]
    assert "2026-11-06" in replies[0]
    target_payload = plugin.service.save_target.call_args.args[0]
    assert target_payload["kind"] == "group"
    assert target_payload["number"] == "67890"
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
async def test_list_exposes_task_and_slot_ids(plugin):
    replies = await collect(plugin.toyoko_list(FakeEvent(), "00075"))
    assert "任务ID" in replies[0]
    assert "需求ID" in replies[0]
```

- [ ] **Step 6: Update help and README**

Document these exact examples:

```text
/toyoko add 00075 1106 1108
/toyoko check 00075
/toyoko list 00075
/toyoko booked <任务ID> <需求ID>
/toyoko restore <任务ID> <需求ID>
```

State that `add/check/list` require a five-digit hotel ID and that detailed filters remain in WebUI.

- [ ] **Step 7: Run targeted tests and commit**

Run: `python -m pytest tests/test_plugin_import.py tests/test_quick.py tests/test_service.py -q`

Expected: all targeted tests pass.

```bash
git add main.py tests/test_plugin_import.py README.md
git commit -m "feat: add QQ quick monitoring commands"
```

### Task 4: Full verification and publication

**Files:**
- Verify only; no production files should change unless a verification failure is reproduced by a new failing test.

**Interfaces:**
- Consumes: the complete plugin and QQ quick command feature.
- Produces: a verified merge and push to `origin/master`.

- [ ] **Step 1: Run the full automated suite**

```powershell
python -m pytest -q
python -m ruff check main.py toyoko_watch tests tools
python -m ruff format --check main.py toyoko_watch tests tools
python -m compileall -q main.py toyoko_watch
node --check pages/watch/app.js
```

Expected: zero failed tests, zero Ruff errors, no formatting changes, successful compile, and successful JavaScript syntax check.

- [ ] **Step 2: Audit tracked paths and diff**

Run: `git diff master...HEAD --check` and inspect `git status --short` plus `git diff master...HEAD --stat`.

Expected: only the spec, plan, plugin implementation, tests, and README changes are tracked; no legacy `.py`, `.ps1`, `.bat`, logs, credentials, runtime JSON, or `.codegraph` files are staged.

- [ ] **Step 3: Merge, verify again, and push**

Merge `codex/qq-quick-commands` into `master`, rerun Step 1 from the merged tree, then run `git push origin master`.

Expected: remote `refs/heads/master` resolves to the verified local merge commit.
