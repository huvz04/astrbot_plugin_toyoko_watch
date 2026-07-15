# QQ Quick Commands Design

## Summary

Extend `astrbot_plugin_toyoko_watch` with concise QQ commands for creating a basic persistent hotel watch, checking one hotel, listing its configured requirements, and marking one requirement booked or active again. Quick commands reuse the existing task, target, monitoring, persistence, and notification models so every quick task remains editable in the plugin WebUI.

## Commands

### `/toyoko add <hotel_id> <checkin_mmdd> <checkout_mmdd>`

- Require a five-digit hotel ID present in the local catalog.
- Require two valid `MMDD` values.
- Resolve check-in to the nearest future occurrence. If the month/day has already passed in Asia/Shanghai, use the next year.
- Resolve check-out after check-in, rolling into the following year when necessary. The stay must remain within the existing 1-to-30-night task limit.
- Bind or reuse the current QQ private chat or group as a notification target.
- Create an enabled persistent task containing only the requested hotel.
- Create two active requirement slots:
  - `single`: one occupant and all single subtypes.
  - `multi`: two occupants and all multi-person subtypes.
- Use a deterministic task ID based on hotel and ISO dates. Reject an existing identical quick task instead of overwriting WebUI edits.
- Run the new task immediately after saving and report task ID, dates, new matches, errors, and pending deliveries.

### `/toyoko check <hotel_id>`

- Require a five-digit hotel ID.
- Select enabled tasks containing that hotel.
- Check only the requested hotel while retaining each task's configured dates, slots, filters, targets, and state transition history.
- Do not check other hotels selected by those tasks.
- If no enabled task contains the hotel, explain that the user must use `/toyoko add` or the WebUI first.

### `/toyoko list <hotel_id>`

- Require a five-digit hotel ID.
- List all tasks containing that hotel, including enabled state, date range, task ID, slot label, slot ID, and slot state.
- Include paused and disabled tasks so booked requirements can still be discovered and restored.

### `/toyoko booked <task_id> <slot_id>`

- Require AstrBot administrator permission.
- Set exactly one slot to `fulfilled` through the existing `set_slot_state` service method.
- Clear its pending notifications and availability observation as the current implementation already does.
- Return the task name, slot label, and resulting state.

### `/toyoko restore <task_id> <slot_id>`

- Require AstrBot administrator permission.
- Set exactly one slot to `active` through the existing service method.
- The next matching successful observation behaves as a first hit and notifies immediately.

## Validation and User Messages

`add`, `check`, and `list` handlers accept empty default arguments so AstrBot can execute the handler and return a specific usage message instead of rejecting argument binding first. Missing or malformed hotel IDs return:

```text
必须提供 5 位酒店编号，例如 00075。
```

Invalid dates, unknown hotels, duplicate quick tasks, missing tasks, and missing slots return concise actionable messages without stack traces. Mutating and network-triggering commands (`add`, `check`, `booked`, and `restore`) require administrator permission. `list` remains read-only.

## Service Boundaries

Add framework-neutral helpers rather than embedding business rules in command handlers:

- `parse_quick_stay(checkin_mmdd, checkout_mmdd, today)` returns ISO dates using Asia/Shanghai calendar semantics.
- `build_quick_task(...)` creates the same `WatchTask` shape used by WebUI.
- `tasks_for_hotel(hotel_id, enabled_only)` powers list and check discovery.
- `check_hotel(hotel_id)` runs cloned per-task views restricted to one hotel, while event IDs and persisted state continue to reference the original task and slot IDs.

The AstrBot layer owns current-conversation target extraction and user-facing command responses. Existing `/toyoko bind` reuses the same target extraction helper to avoid divergent UMO construction.

## Persistence and Compatibility

No new file format is introduced. Quick tasks are stored in `tasks.json`, targets in `targets.json`, and observations in `state.json`. Existing WebUI tasks and commands remain compatible. The old `/toyoko check` without an ID changes from checking all tasks to returning the mandatory hotel-ID usage message; immediate all-task checks remain available from the WebUI.

## Testing

- Date parsing: same-year future dates, past dates rolling to next year, cross-year checkout, invalid calendar dates, reversed/over-30-night ranges.
- Quick task creation: correct hotel, two default slots, occupants and subtypes, current-conversation target, enabled state, deterministic duplicate rejection.
- Hotel checks: only the requested hotel is fetched, disabled/unrelated tasks are excluded, and no-task behavior is explicit.
- Listing: task and slot IDs/states are present, including fulfilled slots.
- Command handlers: missing hotel ID message, successful add/check/list, booked, restore, and missing task/slot errors.
- Full regression suite, Ruff, format, compile, and plugin import stub checks before publication.

## Non-Goals

- QQ commands do not expose detailed room subtype, smoking, inventory, exact-name, keyword, or multi-hotel editing. Those remain WebUI responsibilities.
- Commands do not automate booking or infer that a notification resulted in a reservation.
- `add` does not overwrite or merge an existing task with the same hotel and dates.
