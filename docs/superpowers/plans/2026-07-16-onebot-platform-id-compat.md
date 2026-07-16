# OneBot Platform ID Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make private and group proactive QQ delivery use AstrBot's real OneBot platform instance ID while preserving every existing target and task.

**Architecture:** Persist an optional `platform_id` on each notification target and use the exact ID captured from `event.unified_msg_origin` for new QQ-bound targets. Before every proactive send, resolve legacy adapter-type prefixes such as `aiocqhttp` to the single matching live platform instance, while refusing to guess when multiple matches exist. WebUI-created targets accept an optional instance ID and use the same resolver.

**Tech Stack:** Python 3.10+, AstrBot 4.26.5 plugin API, dataclasses/JSON storage, pytest/pytest-asyncio, vanilla HTML/JavaScript, Ruff.

## Global Constraints

- Keep AstrBot compatibility at `>=4.26.0-beta.8`.
- Keep OneBot v11 adapter support under `aiocqhttp`.
- Preserve old `targets.json` records that do not contain `platform_id`.
- Do not require users to recreate tasks, private targets, or group targets.
- Do not guess among multiple live adapters of the same type.
- Bump the plugin version from `0.1.1` to `0.1.2`.
- Preserve unrelated untracked legacy scripts in the repository root.

---

### Task 1: Persist Real Platform Instance IDs

**Files:**
- Modify: `toyoko_watch/models.py:87-123`
- Test: `tests/test_models_storage.py:68-84`

**Interfaces:**
- Consumes: persisted target mappings with `id`, `label`, `kind`, `number`, `enabled`, and optional `platform_id`.
- Produces: `NotificationTarget.platform_id: str` and `NotificationTarget.umo: str` using `platform_id` as its first segment.

- [ ] **Step 1: Write failing model tests**

Add tests proving explicit instance IDs are used and legacy records remain loadable:

```python
def test_notification_target_uses_platform_instance_id():
    target = NotificationTarget(
        id="private", label="自己", kind="private", number="1686448912",
        enabled=True, platform_id="default-qq",
    )
    assert target.umo == "default-qq:FriendMessage:1686448912"
    assert target.to_dict()["platform_id"] == "default-qq"


def test_notification_target_loads_legacy_record_without_platform_id():
    target = NotificationTarget.from_dict(
        {"id": "group", "label": "群", "kind": "group", "number": "378075060"}
    )
    assert target.platform_id == "aiocqhttp"
    assert target.umo == "aiocqhttp:GroupMessage:378075060"


@pytest.mark.parametrize("platform_id", ["", "bad:id"])
def test_notification_target_rejects_invalid_platform_id(platform_id):
    target = NotificationTarget(
        id="private", label="自己", kind="private", number="1686448912",
        platform_id=platform_id,
    )
    with pytest.raises(ValueError, match="platform_id"):
        _ = target.umo
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_models_storage.py -q
```

Expected: FAIL because `NotificationTarget` does not accept or expose `platform_id`.

- [ ] **Step 3: Implement the minimal compatible model**

Add the field after `enabled`, load a legacy fallback, validate the value, and use it in UMO generation:

```python
enabled: bool = True
platform_id: str = "aiocqhttp"

if not self.platform_id or ":" in self.platform_id:
    raise ValueError("target platform_id must be a non-empty AstrBot platform ID")
return f"{self.platform_id}:{message_type}:{self.number}"
```

In `from_dict` use:

```python
platform_id=str(data.get("platform_id") or "aiocqhttp"),
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run the same model test command. Expected: all tests in `test_models_storage.py` pass.

- [ ] **Step 5: Commit the model change**

```powershell
git add -- toyoko_watch/models.py tests/test_models_storage.py
git commit -m "fix: persist AstrBot platform IDs on QQ targets"
```

---

### Task 2: Resolve Legacy UMOs and Capture Exact Event Sessions

**Files:**
- Modify: `main.py:179-214`
- Modify: `tests/test_plugin_import.py:123-235`

**Interfaces:**
- Consumes: `event.unified_msg_origin`, `context.platform_manager.platform_insts` or `get_insts()`, and legacy/full UMO strings.
- Produces: `ToyokoWatchPlugin._resolve_platform_id(platform_id: str) -> str`, `ToyokoWatchPlugin._resolve_umo(umo: str) -> str`, and event-created targets with `platform_id`.

- [ ] **Step 1: Extend the test doubles and write failing sending tests**

Give `FakeEvent` an exact UMO and create fake platform metadata:

```python
class FakePlatform:
    def __init__(self, platform_id="default-qq", name="aiocqhttp"):
        self.metadata = SimpleNamespace(id=platform_id, name=name)

    def meta(self):
        return self.metadata


class FakeEvent:
    def __init__(self, group_id="", sender_id="12345", platform_id="default-qq"):
        self.group_id = group_id
        self.sender_id = sender_id
        message_type = "GroupMessage" if group_id else "FriendMessage"
        session_id = group_id or sender_id
        self.unified_msg_origin = f"{platform_id}:{message_type}:{session_id}"
        self.stopped = False
```

Construct plugin contexts with one `FakePlatform`:

```python
platforms = [FakePlatform()]
context = SimpleNamespace(
    send_message=AsyncMock(return_value=True),
    register_web_api=lambda *_args: None,
    platform_manager=SimpleNamespace(
        platform_insts=platforms,
        get_insts=lambda: platforms,
    ),
)
```

Then add:

```python
@pytest.mark.asyncio
async def test_send_qq_resolves_legacy_adapter_name_to_unique_instance(plugin):
    await plugin._send_qq("aiocqhttp:FriendMessage:1686448912", "test")
    plugin.context.send_message.assert_awaited_once()
    assert plugin.context.send_message.await_args.args[0] == (
        "default-qq:FriendMessage:1686448912"
    )


@pytest.mark.asyncio
async def test_send_qq_preserves_exact_platform_instance(plugin):
    await plugin._send_qq("default-qq:GroupMessage:378075060", "test")
    assert plugin.context.send_message.await_args.args[0] == (
        "default-qq:GroupMessage:378075060"
    )


def test_resolver_does_not_guess_between_multiple_onebot_instances(plugin):
    plugin.context.platform_manager.platform_insts.append(
        FakePlatform("backup-qq", "aiocqhttp")
    )
    assert plugin._resolve_platform_id("aiocqhttp") == "aiocqhttp"
```

Update the quick-add assertion to expect `default-qq:GroupMessage:67890`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_plugin_import.py -q
```

Expected: FAIL because legacy UMO prefixes are passed through and event targets omit `platform_id`.

- [ ] **Step 3: Implement platform and UMO resolution**

Add a helper that reads live platform objects without assuming which manager accessor is present:

```python
def _platform_instances(self) -> list[object]:
    manager = getattr(self.context, "platform_manager", None)
    if manager is None:
        return []
    get_insts = getattr(manager, "get_insts", None)
    return list(get_insts()) if callable(get_insts) else list(
        getattr(manager, "platform_insts", [])
    )

def _resolve_platform_id(self, platform_id: str) -> str:
    metadata = [platform.meta() for platform in self._platform_instances()]
    if any(item.id == platform_id for item in metadata):
        return platform_id
    matches = [item.id for item in metadata if item.name == platform_id]
    return matches[0] if len(matches) == 1 else platform_id

def _resolve_umo(self, umo: str) -> str:
    platform_id, message_type, session_id = umo.split(":", 2)
    resolved = self._resolve_platform_id(platform_id)
    return f"{resolved}:{message_type}:{session_id}"
```

Use `_resolve_umo` in `_send_qq`. In `_target_from_event`, parse the first segment of `event.unified_msg_origin` and include it as `platform_id` in the returned mapping.

- [ ] **Step 4: Run focused and service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_plugin_import.py tests\test_service.py tests\test_notifiers.py -q
```

Expected: all focused tests pass, including legacy retry behavior.

- [ ] **Step 5: Commit the AstrBot sending change**

```powershell
git add -- main.py tests/test_plugin_import.py
git commit -m "fix: resolve OneBot targets to the active platform instance"
```

---

### Task 3: Support Platform IDs in WebUI and Release Metadata

**Files:**
- Modify: `main.py:145-154`
- Modify: `pages/watch/index.html:47-59`
- Modify: `pages/watch/app.js:460-468`
- Modify: `metadata.yaml:5`
- Create: `tests/test_plugin_assets.py`

**Interfaces:**
- Consumes: optional `platform_id` from the WebUI target form.
- Produces: saved target payloads containing a resolved platform instance ID and plugin release `0.1.2`.

- [ ] **Step 1: Write failing asset and page-save tests**

Create `tests/test_plugin_assets.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_target_form_exposes_optional_platform_instance_id():
    html = (ROOT / "pages" / "watch" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "pages" / "watch" / "app.js").read_text(encoding="utf-8")
    assert 'id="target-platform-id"' in html
    assert 'platform_id: $("#target-platform-id").value.trim()' in script


def test_release_metadata_is_0_1_2():
    metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    assert "version: 0.1.2" in metadata
```

Add a plugin test that calls `page_save_target` with a blank platform ID and asserts the saved target becomes `default-qq:FriendMessage:1686448912`:

```python
@pytest.mark.asyncio
async def test_page_save_target_resolves_blank_platform_id(plugin):
    plugin_module = sys.modules[plugin.__class__.__module__]
    plugin_module.request.json = AsyncMock(
        return_value={
            "id": "private-1686448912",
            "label": "自己",
            "kind": "private",
            "number": "1686448912",
            "platform_id": "",
            "enabled": True,
        }
    )

    result = await plugin.page_save_target()

    assert result["umo"] == "default-qq:FriendMessage:1686448912"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_plugin_assets.py tests\test_plugin_import.py -q
```

Expected: FAIL because the form, payload, page resolver, and release version are absent.

- [ ] **Step 3: Implement the WebUI and page-save path**

Add this optional field to the notification target form:

```html
<label>平台实例 ID
  <input id="target-platform-id" placeholder="留空自动识别，例如 default-qq" />
</label>
```

Include it in the JavaScript payload:

```javascript
platform_id: $("#target-platform-id").value.trim(),
```

Before calling `self.web.save_target(payload)` in `page_save_target`, normalize the value:

```python
platform_id = str(payload.get("platform_id") or "aiocqhttp")
payload["platform_id"] = self._resolve_platform_id(platform_id)
```

Set `metadata.yaml` to `version: 0.1.2`.

- [ ] **Step 4: Run the asset and plugin tests**

Run the same command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit WebUI and version changes**

```powershell
git add -- main.py pages/watch/index.html pages/watch/app.js metadata.yaml tests/test_plugin_assets.py tests/test_plugin_import.py
git commit -m "feat: configure OneBot platform IDs in WebUI"
```

---

### Task 4: Full Verification and Delivery

**Files:**
- Verify all tracked plugin files.
- Do not add `.codegraph/` or the untracked root-level legacy scripts.

**Interfaces:**
- Consumes: the three preceding tested changes.
- Produces: a verified `0.1.2` commit on `master` and the same commit on `origin/master`.

- [ ] **Step 1: Run the full automated test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Run static, format, compile, and frontend syntax checks**

```powershell
.\.venv\Scripts\python.exe -m ruff check main.py toyoko_watch tests
.\.venv\Scripts\python.exe -m ruff format --check main.py toyoko_watch tests
.\.venv\Scripts\python.exe -m compileall -q main.py toyoko_watch tests
node --check pages\watch\app.js
git diff --check
```

Expected: every command exits with code 0.

- [ ] **Step 3: Review repository state and commit any final test-only adjustment**

```powershell
git status --short
git log --oneline -8
```

Expected: no tracked modifications; only the user's pre-existing untracked files remain.

- [ ] **Step 4: Push and verify the remote commit**

```powershell
git push origin master
$local = git rev-parse HEAD
$remote = (git ls-remote origin refs/heads/master).Split("`t")[0]
if ($local -ne $remote) { throw "origin/master did not update" }
```

Expected: push succeeds and local/remote hashes are identical.

- [ ] **Step 5: Runtime handoff**

Tell the user to update/reinstall plugin `0.1.2`, reload it, and use the target test button. The expected AstrBot log/session prefix is `default-qq`, with no new `cannot find platform for session aiocqhttp:...` warning.
