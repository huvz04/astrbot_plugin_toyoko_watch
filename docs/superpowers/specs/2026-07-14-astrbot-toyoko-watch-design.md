# AstrBot Toyoko Watch Plugin Design

## Summary

Build `astrbot_plugin_toyoko_watch`, a native AstrBot plugin that monitors Toyoko Inn availability and sends proactive notifications through OneBot v11 QQ private chats, QQ groups, and optional SMTP email. The plugin replaces the standalone Windows watcher as the production entry point and provides a dedicated AstrBot WebUI page for hotel search, date selection, room requirements, notification targets, status, and test actions.

The plugin targets the locally used AstrBot `v4.26.0-beta.8` or newer and will be published at `https://github.com/huvz04/astrbot_plugin_toyoko_watch`.

## Existing-System Findings

The standalone watcher has three independent notification failure modes:

1. `from win11toast import toast` is imported unconditionally, so a migrated Windows host without `win11toast` exits before any availability check or email send.
2. The launcher passes `--suppress-initial`; rooms found on the first poll are inserted into `seen` without notifying and remain suppressed for the lifetime of the process.
3. Later new hits attempted email delivery, but the runtime log records that `TOYOKO_SMTP_USER` and `TOYOKO_SMTP_PASS` were absent, so email was skipped.

The new plugin must not depend on Windows desktop APIs, must notify on a first-poll hit, and must persist delivery state explicitly rather than using a process-lifetime `set`.

## Goals

- Run entirely inside AstrBot as a Python plugin.
- Support OneBot v11 proactive delivery to any configured combination of QQ private chats and QQ groups.
- Support optional SMTP email delivery using the existing host, port, TLS/SSL, sender, recipient, username, and password capabilities.
- Provide an AstrBot plugin page for creating and operating monitoring tasks.
- Let one monitoring task select multiple hotels.
- Maintain a searchable local catalog containing every Toyoko Inn hotel's ID and name, plus region, address, and detail URL when available.
- Seed the catalog with a bundled snapshot and allow a manual refresh from the official hotel list.
- Default hotel selection to Yokohama Stadium Mae No. 1 (`00075`) and No. 2 (`00073`).
- Support check-in/check-out selection and live room-type probing.
- Model independent room requirements so the user can monitor one single room and one multi-person room, then manually mark either requirement fulfilled without stopping the other.
- Notify immediately when matching inventory is present on the first successful check.
- Avoid repeated messages for unchanged continuously available inventory, while notifying again after inventory disappears and later returns.
- Provide visible, actionable testing for QQ, email, catalog refresh, room probing, and immediate task execution.

## Non-Goals

- Do not provide a public incoming or outgoing webhook in the first version.
- Do not automate booking, login, payment, or reservation confirmation.
- Do not infer that a room was booked merely because availability was reported.
- Do not retain Windows toast, sound, Tk dashboard, browser-opening, batch-file, or PowerShell-launcher behavior in the published plugin.
- Do not poll the hotel catalog during every availability cycle.
- Do not scrape or store Toyoko account credentials.

## Architecture

The plugin is a single AstrBot extension with focused internal modules:

- `main.py`: AstrBot lifecycle, command handlers, configuration injection, background task startup and shutdown, and plugin Web API registration.
- `toyoko_watch/catalog.py`: official hotel-list download, parsing, validation, search indexing, and atomic catalog replacement.
- `toyoko_watch/client.py`: asynchronous Toyoko availability requests and extraction of the embedded `__NEXT_DATA__` `planResponse` payload.
- `toyoko_watch/models.py`: validated task, requirement-slot, target, vacancy, delivery, and runtime-state models.
- `toyoko_watch/matching.py`: room-name normalization, broad category classification, subtype matching, exact-name selection, and custom keyword matching.
- `toyoko_watch/monitor.py`: polling coordination, bounded concurrency, state transitions, and match-event creation.
- `toyoko_watch/notifiers.py`: AstrBot UMO delivery and SMTP delivery with per-target results.
- `toyoko_watch/storage.py`: atomic JSON persistence in the AstrBot plugin data directory.
- `toyoko_watch/web.py`: authenticated plugin-page API handlers and input validation.
- `pages/watch/`: the WebUI page, CSS, and JavaScript using the AstrBot plugin-page bridge.
- `data/hotels.seed.json`: bundled offline hotel-catalog snapshot.
- `tests/`: unit and integration-style tests with recorded HTML/JSON fixtures and fake AstrBot context objects.

The availability client, matching engine, state machine, and notifiers communicate through typed data objects. AstrBot-specific objects remain at the lifecycle, Web API, and QQ delivery boundaries so the core behavior can be tested without starting a real bot.

## Persistent Data

All mutable runtime data is stored under AstrBot's plugin data directory, never inside the installed plugin directory.

### `hotels.json`

Each hotel record contains:

```json
{
  "hotel_id": "00075",
  "name": "東横INN横浜スタジアム前1",
  "region": "関東",
  "prefecture": "神奈川県",
  "city": "横浜市",
  "address": "神奈川県横浜市中区山下町205-1",
  "detail_url": "https://www.toyoko-inn.com/search/detail/00075/"
}
```

Search is case-insensitive and matches hotel ID, Japanese name, region, prefecture, city, and address. The bundled seed is copied on first startup. A refresh never deletes the last known-good catalog until the replacement has passed validation.

### `tasks.json`

Each task contains:

- Stable task ID and editable name.
- Enabled/paused flag.
- Selected hotel IDs.
- Check-in and check-out dates.
- One or more requirement slots.
- Selected notification-target IDs.
- Optional per-task polling interval override.
- Whether matching price or inventory-count changes produce another notification.

Check-out must be later than check-in, the stay must be 1 through 30 nights, at least one hotel and one active requirement slot are required before a task can be enabled, and at least one enabled notification channel must be selected.

Two paused starter tasks are created on a fresh installation:

- `横滨周六晚 11/7`: `2026-11-07` to `2026-11-08`.
- `横滨周日晚 11/8`: `2026-11-08` to `2026-11-09`.

Both preselect hotels `00075` and `00073` and include one single-room slot and one multi-person-room slot. The tasks remain paused until a notification target is configured, preventing accidental background traffic or undeliverable alerts.

### Requirement slots

Each requirement slot contains:

- Stable slot ID and label.
- State: `active`, `paused`, or `fulfilled`.
- Broad category: `single` or `multi`.
- Selected normalized subtypes.
- Optional exact room names obtained through live probing.
- Optional custom Japanese keywords.
- Smoking filter: any, non-smoking, or smoking.
- Inventory filter: general, member, or either.
- Occupant count from 1 through 4; single defaults to one and multi defaults to two.
- Quantity goal, initially fixed at one room.

The single category exposes at least economy single, standard single, and large-bed single labels. The multi category exposes at least economy double, double, twin, and triple labels. Matching uses the actual Japanese `roomTypeName`; exact names selected from live probing take precedence over subtype heuristics, and custom keywords extend rather than replace selected filters.

The user manually marks a slot fulfilled after completing a reservation. A fulfilled slot is excluded from checks and notifications while other slots in the same task continue. The slot can be returned to active state at any time.

### `targets.json`

Targets are globally reusable and contain a label, type, numeric QQ/group ID, derived UMO, enabled flag, and last test result.

- Private target UMO: `aiocqhttp:FriendMessage:<QQ number>`.
- Group target UMO: `aiocqhttp:GroupMessage:<group number>`.

A target can be added manually in WebUI or by running `/toyoko bind` in the desired QQ conversation. Tasks select any number of enabled targets.

SMTP settings remain in AstrBot's plugin configuration. Each task contains an `email_enabled` flag. A task can be enabled only when it has at least one selected enabled QQ target, or email is enabled for the task and the global SMTP configuration contains at least one recipient.

### `state.json`

Runtime state contains the last successful check, next scheduled check, recent per-hotel errors, active availability signatures, per-target delivery results, and pending retries. Requirement-slot state, including manual fulfillment, is authoritative in `tasks.json`. Writes use a temporary file followed by atomic replacement. Unknown or corrupt runtime state is backed up and rebuilt without modifying tasks or notification targets.

## Hotel Catalog Synchronization

The catalog source is the official `https://www.toyoko-inn.com/hotel_list/` page. The parser extracts five-digit IDs from official detail links and associates each with its displayed name, region, prefecture, city/address, and canonical detail URL.

A downloaded catalog is accepted only when:

- Every ID matches `^[0-9]{5}$` and is unique.
- Every record has a non-empty name and official detail URL.
- Both default IDs `00073` and `00075` exist.
- The record count is at least 100 and at least 70 percent of the previous valid catalog count.

Refresh is user-triggered from WebUI or `/toyoko catalog-refresh`. It uses a 30-second timeout and reports added, changed, removed, and total counts. A failed download or validation leaves the old catalog in service. Availability polling never depends on a catalog refresh succeeding.

## WebUI Design

The plugin page has four operational areas.

### Status header

- Plugin enabled state.
- Background scheduler health.
- Last and next check timestamps.
- Count of enabled tasks and active slots.
- Most recent global error.
- `立即检查全部` action.

### Monitoring tasks

- List, create, edit, copy, pause, and delete tasks.
- Searchable multi-hotel selector backed by the local catalog.
- Check-in and check-out date pickers.
- Requirement-slot editor with broad category, subtypes, exact room names, custom keywords, occupant count, smoking, inventory class, state, and manual `已订到`/`恢复监控` controls.
- `探测房型` action that checks the selected hotels and dates once and returns the actual room names grouped by hotel without changing notification state.
- Per-task `立即执行` action.
- Recent result summary for each selected hotel and slot.

### Notification targets

- Add private QQ or QQ group targets.
- Bind instructions showing `/toyoko bind` as the safer alternative to manual UMO construction.
- Enable, disable, edit label, delete, and send test message.
- Test results show each target independently.

### Maintenance and email

- Catalog record count, update timestamp, source, and `从官网更新酒店目录` action.
- SMTP enable flag, host, port, SSL/TLS mode, username, password, sender, and recipient list.
- `测试邮件` action.
- Recent errors and delivery failures with timestamps and concise causes.

The page communicates only through AstrBot's plugin-page bridge and registered plugin APIs. It does not expose an unauthenticated public endpoint.

## Availability Requests and Matching

For each enabled task, the monitor builds official detail-search URLs using the task's hotel ID, dates, one room, the requirement slot's occupant count, and all smoking classes. Slots sharing the same hotel, dates, and occupant count reuse one response; smoking is filtered from returned room metadata. Requests use `aiohttp`, a browser-like user agent, a 30-second timeout, and at most two attempts with a two-second backoff.

The client extracts the page's `__NEXT_DATA__` JSON and reads `props.pageProps.planResponse`. Missing or incompatible structures are reported as schema errors, not interpreted as no vacancy.

The matcher examines each room's name, smoking metadata, plans, general inventory, member inventory, and prices. A vacancy can satisfy multiple active slots, but a notification message lists each satisfied slot explicitly. The monitor does not attempt to allocate a finite room count across slots because it cannot reserve inventory; it only reports that the observed offer matches each requirement.

## Polling and State Transitions

The global default interval is 300 seconds, configurable from 60 through 3600 seconds. A task may override it within the same range. Checks use a global concurrency limit of three hotel requests and add zero through ten seconds of jitter between cycles.

Each `(task, slot, hotel, stay range)` has one of three observed states:

- `unknown`: no successful observation yet.
- `absent`: the latest successful observation had no matching room.
- `present`: the latest successful observation had matching inventory.

Transitions behave as follows:

- `unknown -> present`: create a notification immediately, including on the first poll.
- `unknown -> absent`: record absence without notifying.
- `absent -> present`: create a notification immediately.
- `present -> present`: do not notify unless change notifications are enabled and the normalized room/plan/price/inventory signature changed.
- `present -> absent`: clear the active signature so a later reappearance notifies again.
- Any state followed by request, parse, or delivery error: retain the last successful availability state; never treat the error as absence.

Marking a slot fulfilled suppresses new checks for that slot and clears pending notification retries for it. Restoring the slot sets it to `unknown`, so matching inventory on the next successful check notifies immediately.

## Notification Delivery

QQ delivery uses `self.context.send_message(umo, MessageChain().message(text))`. Each availability event is delivered independently to every selected QQ target and every configured email recipient.

The message includes:

- Task name and satisfied requirement slot.
- Hotel name and five-digit ID.
- Check-in/check-out dates.
- Actual room name and smoking status.
- Plan name.
- General and member room counts.
- General and member prices when provided.
- Official booking URL.
- Reminder that the slot remains active until manually marked fulfilled.

Delivery state is tracked per event and per target. Successful targets are not retried. Failed targets remain pending and retry on the next scheduler cycle with a maximum of three attempts; after three failures they remain visible as failed and can be retried from WebUI without resending to successful targets.

SMTP supports STARTTLS and implicit SSL. Blocking SMTP operations run through `asyncio.to_thread` so they do not block AstrBot's event loop. Passwords are never logged, returned by status APIs, or stored in the repository.

## Commands

All mutating and test commands require AstrBot administrator permission.

- `/toyoko status`: show scheduler, task, slot, target, and recent-error status.
- `/toyoko bind`: add the current private chat or group as a notification target.
- `/toyoko test`: send a test message to the current conversation.
- `/toyoko check`: run all enabled tasks immediately.
- `/toyoko catalog-refresh`: refresh and validate the hotel catalog.
- `/toyoko help`: show concise usage and direct users to the plugin page.

Commands stop event propagation so they are not forwarded to the LLM.

## Error Handling and Observability

- Network, timeout, HTTP, HTML-schema, JSON, matching, persistence, QQ, and SMTP errors are recorded separately.
- One hotel failure does not cancel checks for other hotels or tasks.
- Scheduler exceptions are caught and logged without terminating the background loop.
- Plugin shutdown cancels the scheduler and awaits its completion; in-flight HTTP sessions are closed.
- WebUI displays the latest error per hotel and delivery target, while AstrBot logs retain stack traces for unexpected exceptions.
- User-facing errors redact SMTP passwords and avoid returning raw page bodies or authentication material.

## Migration and Repository Hygiene

The existing `toyoko_watch.py` parsing behavior and SMTP capabilities are migration inputs, not runtime dependencies. The plugin implementation will be written in the current repository without modifying or deleting the user's standalone scripts. Legacy scripts, logs, caches, desktop launchers, `.codegraph`, SMTP data, and generated runtime JSON are excluded from the published Git repository.

The repository includes `metadata.yaml`, `_conf_schema.json`, `requirements.txt`, `README.md`, plugin code, WebUI assets, the seed catalog, and tests. Plugin dependencies are declared explicitly; Windows-only packages are not included.

## Testing Strategy

Development follows test-first red/green cycles.

### Unit tests

- Official hotel-list fixture parsing, searchable fields, validation, and atomic fallback.
- `__NEXT_DATA__` extraction and explicit schema-failure behavior.
- Single/multi broad classification, every named subtype, exact room selection, custom keywords, smoking, and general/member filters.
- Task validation, occupant-aware request grouping, and independent requirement-slot state changes.
- Every availability state transition, including first-poll notification, unchanged suppression, disappearance, reappearance, change notifications, fulfilled suppression, and restore-to-unknown behavior.
- Per-target delivery success, partial failure, retry limit, and no resend to successful targets.
- SMTP STARTTLS/SSL configuration without exposing secrets.

### Integration-style tests

- Background scheduler lifecycle using a fake clock and fake availability client.
- AstrBot proactive QQ delivery using a fake context and real UMO strings.
- Plugin Web APIs for catalog search, task CRUD, room probing, target tests, email tests, manual fulfillment, and immediate checks.
- Persistence recovery from missing and corrupt state files.

### Verification

- Run the complete pytest suite.
- Run Ruff format and lint checks.
- Import the plugin against the sibling AstrBot checkout.
- Start the sibling AstrBot development instance, load/reload the plugin, open the plugin page, and exercise a read-only live availability probe.
- Use the WebUI QQ test action against a configured OneBot private or group target.
- Use the WebUI email test only when SMTP credentials are configured.
- Confirm that no logs, credentials, caches, or standalone legacy files are staged before publishing.

## Acceptance Criteria

The feature is complete when:

1. AstrBot loads, reloads, and unloads the plugin without orphan background tasks.
2. The WebUI can search the complete local hotel catalog by ID, name, region, city, or address, with `00073` and `00075` preselected in starter tasks.
3. A user can configure dates, multiple hotels, independent single/multi requirement slots, occupant count, exact probed room names, custom keywords, smoking, and inventory class.
4. A first successful check with matching inventory sends an immediate QQ notification.
5. Unchanged continuous inventory does not resend; disappearance followed by reappearance does resend.
6. Marking one slot fulfilled stops only that slot while other slots continue.
7. Private and group QQ targets can be bound, selected per task, and tested independently.
8. Optional SMTP email can be configured and tested without storing secrets in the repository or logs.
9. A catalog refresh failure or hotel-check error does not erase valid local data or create a false no-room transition.
10. Automated tests, Ruff checks, plugin import, and the agreed manual AstrBot smoke checks pass before the repository is pushed to `huvz04`.
