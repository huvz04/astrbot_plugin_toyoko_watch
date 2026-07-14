# AstrBot Toyoko Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a native AstrBot plugin with a WebUI that monitors configurable Toyoko Inn room requirements and proactively notifies OneBot v11 private chats, groups, and optional email recipients.

**Architecture:** Keep the deterministic catalog, parsing, matching, state transition, persistence, and notification formatting logic in a small `toyoko_watch` package. `main.py` adapts those services to AstrBot lifecycle, UMO messaging, commands, and plugin-page APIs; `pages/watch` supplies a no-build static administration UI.

**Tech Stack:** Python 3.10+, AstrBot >=4.26.0-beta.8, aiohttp, standard-library SMTP/JSON/dataclasses, pytest, pytest-asyncio, Ruff, HTML/CSS/JavaScript.

## Global Constraints

- Production plugin name is `astrbot_plugin_toyoko_watch` and repository is `https://github.com/huvz04/astrbot_plugin_toyoko_watch`.
- Support OneBot v11 UMOs `aiocqhttp:FriendMessage:<id>` and `aiocqhttp:GroupMessage:<id>`.
- First successful matching observation sends immediately; request errors never become absence.
- Requirement slots are independently fulfilled and restored by the user.
- Mutable data lives only in AstrBot's plugin data directory.
- Existing standalone scripts remain untouched and are not published.
- Use aiohttp rather than requests, and declare all third-party dependencies.
- Follow test-first red/green cycles for production behavior.

---

### Task 1: Plugin scaffold, models, and atomic storage

**Files:**
- Create: `.gitignore`
- Create: `metadata.yaml`
- Create: `_conf_schema.json`
- Create: `requirements.txt`
- Create: `toyoko_watch/__init__.py`
- Create: `toyoko_watch/models.py`
- Create: `toyoko_watch/storage.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models_storage.py`

**Interfaces:**
- Produces `RequirementSlot`, `WatchTask`, `NotificationTarget`, `Vacancy`, `validate_task()`, and `JsonStore.load/save()`.

- [ ] **Step 1: Write failing model and storage tests**

```python
def test_enabled_task_requires_destination():
    task = WatchTask.from_dict({"id": "t1", "enabled": True, "hotel_ids": ["00075"], "checkin": "2026-11-07", "checkout": "2026-11-08", "slots": [{"id": "single", "label": "单人", "state": "active", "category": "single", "subtypes": ["standard_single"], "occupants": 1}], "target_ids": [], "email_enabled": False})
    with pytest.raises(ValueError, match="notification"):
        validate_task(task, enabled_target_ids=set(), smtp_ready=False)

def test_json_store_keeps_last_good_file(tmp_path):
    store = JsonStore(tmp_path / "tasks.json", default_factory=list)
    store.save([{"id": "t1"}])
    assert store.load() == [{"id": "t1"}]
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run `python -m pytest tests/test_models_storage.py -q` and verify collection fails because the package does not exist.**
- [ ] **Step 3: Implement dataclasses, date/occupant/task validation, and temporary-file plus `os.replace` persistence.**
- [ ] **Step 4: Run the targeted test and verify it passes.**
- [ ] **Step 5: Commit with `feat: scaffold Toyoko watch plugin`.**

### Task 2: Official hotel catalog and availability client

**Files:**
- Create: `toyoko_watch/catalog.py`
- Create: `toyoko_watch/client.py`
- Create: `data/hotels.seed.json`
- Create: `tests/fixtures/hotel_list.html`
- Create: `tests/fixtures/room_plan.html`
- Create: `tests/test_catalog_client.py`

**Interfaces:**
- Produces `parse_hotel_catalog(html) -> list[dict]`, `validate_catalog(new, previous)`, `search_hotels(records, query)`, and `ToyokoClient.fetch_availability(hotel_id, checkin, checkout, occupants) -> tuple[str, list[Vacancy], str]`.

- [ ] **Step 1: Write failing fixture-based tests**

```python
def test_catalog_contains_id_name_and_searchable_address(hotel_html):
    records = parse_hotel_catalog(hotel_html)
    stadium = next(row for row in records if row["hotel_id"] == "00075")
    assert stadium["name"] == "東横INN横浜スタジアム前1"
    assert search_hotels(records, "横浜") == [stadium]

def test_room_plan_schema_failure_is_not_empty_inventory():
    with pytest.raises(ToyokoSchemaError):
        extract_plan_response("<html></html>")
```

- [ ] **Step 2: Run `python -m pytest tests/test_catalog_client.py -q` and verify missing imports fail.**
- [ ] **Step 3: Implement official-detail-link parsing, catalog validation, search, URL construction, `__NEXT_DATA__` extraction, and aiohttp retry/timeout behavior.**
- [ ] **Step 4: Generate the bundled seed from the official list and verify it contains unique `00073` and `00075` records.**
- [ ] **Step 5: Run the targeted tests and commit with `feat: add Toyoko catalog and availability client`.**

### Task 3: Room matching and availability state machine

**Files:**
- Create: `toyoko_watch/matching.py`
- Create: `toyoko_watch/monitor.py`
- Create: `tests/test_matching_monitor.py`

**Interfaces:**
- Consumes `RequirementSlot`, `WatchTask`, and `Vacancy`.
- Produces `classify_room_name()`, `match_vacancies()`, `availability_signature()`, `AvailabilityState.apply_success()`, and `MonitorService.run_task()`.

- [ ] **Step 1: Write failing matching and transition tests**

```python
@pytest.mark.parametrize((name, subtype), [("エコノミーシングル", "economy_single"), ("シングル", "standard_single"), ("エコノミーダブル", "economy_double"), ("ツイン", "twin")])
def test_room_subtypes(name, subtype):
    assert subtype in classify_room_name(name)

def test_first_present_notifies_and_reappearance_notifies_again():
    state = AvailabilityState()
    assert state.apply_success("key", "sig") is True
    assert state.apply_success("key", "sig") is False
    assert state.apply_success("key", None) is False
    assert state.apply_success("key", "sig") is True
```

- [ ] **Step 2: Run `python -m pytest tests/test_matching_monitor.py -q` and verify missing modules fail.**
- [ ] **Step 3: Implement normalized subtype/category/exact/custom matching and occupant-aware request grouping.**
- [ ] **Step 4: Implement unknown/absent/present transitions where errors preserve state and restored slots return to unknown.**
- [ ] **Step 5: Run the targeted tests and commit with `feat: add room matching and monitor state`.**

### Task 4: QQ/email delivery and AstrBot lifecycle

**Files:**
- Create: `toyoko_watch/notifiers.py`
- Create: `main.py`
- Create: `tests/test_notifiers_plugin.py`

**Interfaces:**
- Produces `format_availability_message()`, `DeliveryTracker`, `send_smtp()`, and `ToyokoWatchPlugin` lifecycle/command handlers.

- [ ] **Step 1: Write failing delivery tests**

```python
@pytest.mark.asyncio
async def test_partial_failure_retries_only_failed_target(fake_context):
    tracker = DeliveryTracker(max_attempts=3)
    targets = [
        NotificationTarget(id="private-1", label="私聊", kind="private", number="1", enabled=True),
        NotificationTarget(id="group-2", label="群聊", kind="group", number="2", enabled=True),
    ]
    first = await deliver_qq(fake_context, targets, "hello", tracker)
    assert first["private-1"] is True
    assert first["group-2"] is False
    assert tracker.pending_ids() == ["group-2"]

def test_message_contains_booking_details():
    event = {"task_name": "横滨", "slot_label": "单人", "hotel_name": "東横INN横浜スタジアム前1", "hotel_id": "00075", "checkin": "2026-11-07", "checkout": "2026-11-08", "room": "シングル", "smoking": "禁煙", "plan": "スタンダード", "general": 1, "member": 1, "general_price": 7410, "member_price": 6935, "url": "https://www.toyoko-inn.com/search/result/room_plan/"}
    text = format_availability_message(event)
    assert "東横INN横浜スタジアム前1" in text
    assert "2026-11-07" in text
    assert "一般1" in text
    assert "https://www.toyoko-inn.com/" in text
```

- [ ] **Step 2: Run `python -m pytest tests/test_notifiers_plugin.py -q` and verify missing imports fail.**
- [ ] **Step 3: Implement per-target QQ tracking, `asyncio.to_thread` SMTP, scheduler lifecycle, `/toyoko status|bind|test|check|catalog-refresh|help`, and clean cancellation.**
- [ ] **Step 4: Run the targeted tests and an import smoke test against the sibling AstrBot checkout.**
- [ ] **Step 5: Commit with `feat: integrate AstrBot notifications and scheduler`.**

### Task 5: Authenticated plugin APIs and WebUI

**Files:**
- Create: `toyoko_watch/web.py`
- Create: `pages/watch/index.html`
- Create: `pages/watch/app.js`
- Create: `pages/watch/style.css`
- Create: `.astrbot-plugin/i18n/zh-CN.json`
- Create: `tests/test_web_api.py`

**Interfaces:**
- Produces plugin-local APIs `status`, `hotels`, `catalog/refresh`, `tasks`, `tasks/<id>`, `tasks/<id>/check`, `tasks/<id>/slots/<slot_id>/state`, `rooms/probe`, `targets`, `targets/<id>/test`, and `email/test`.

- [ ] **Step 1: Write failing handler tests**

```python
@pytest.mark.asyncio
async def test_fulfill_only_selected_slot(web_service):
    result = await web_service.set_slot_state("task-1", "single", "fulfilled")
    assert result["slots"][0]["state"] == "fulfilled"
    assert result["slots"][1]["state"] == "active"

@pytest.mark.asyncio
async def test_hotel_search_returns_local_results(web_service):
    result = await web_service.search_hotels("横浜")
    assert {item["hotel_id"] for item in result} >= {"00073", "00075"}
```

- [ ] **Step 2: Run `python -m pytest tests/test_web_api.py -q` and verify missing service fails.**
- [ ] **Step 3: Implement validated service methods and register AstrBot web handlers using `astrbot.api.web` response helpers.**
- [ ] **Step 4: Implement the no-build page with status, task editor, hotel search, slot controls, target tests, catalog refresh, room probe, and email test.**
- [ ] **Step 5: Run API tests, static JavaScript syntax check, and commit with `feat: add Toyoko watch WebUI`.**

### Task 6: Documentation, end-to-end verification, and publication

**Files:**
- Create: `README.md`
- Modify: `metadata.yaml`
- Modify: `_conf_schema.json`

**Interfaces:**
- Produces an installable repository and operator instructions.

- [ ] **Step 1: Document installation, OneBot UMO binding, starter tasks, room probing, manual fulfillment, SMTP, test buttons, and troubleshooting.**
- [ ] **Step 2: Run `python -m pytest -q`, `ruff format --check .`, `ruff check .`, `python -m compileall -q main.py toyoko_watch`, and the sibling-AstrBot import smoke test.**
- [ ] **Step 3: Start the sibling AstrBot development instance, reload the plugin, open the plugin page, and execute a read-only room probe; record any environment limitation instead of claiming it passed.**
- [ ] **Step 4: Review staged paths and confirm no legacy scripts, logs, caches, runtime JSON, or secrets are tracked.**
- [ ] **Step 5: Commit with `docs: document Toyoko watch plugin`, merge the feature branch after fresh verification, and push `master` to `origin`.**
