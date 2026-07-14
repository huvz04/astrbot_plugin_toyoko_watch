const bridge = window.AstrBotPluginPage;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const subtypeLabels = {
  economy_single: "经济单人",
  standard_single: "标准单人",
  large_single: "单人大床",
  economy_double: "经济双人",
  double: "双人大床",
  twin: "双床",
  triple: "三人房",
};
const categorySubtypes = {
  single: ["economy_single", "standard_single", "large_single"],
  multi: ["economy_double", "double", "twin", "triple"],
};
const stateLabels = { active: "监控中", paused: "已暂停", fulfilled: "已订到" };

let snapshot = null;
let selectedHotels = new Map();
let toastTimer = null;
let searchTimer = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function makeId(prefix) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${random}`.replaceAll(".", "-");
}

function showToast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.style.background = isError ? "var(--danger)" : "var(--text)";
  node.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), 4200);
}

async function withButton(button, label, operation) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    return await operation();
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

async function loadSnapshot(quiet = false) {
  const error = $("#page-error");
  try {
    snapshot = await bridge.apiGet("status");
    error.classList.add("hidden");
    renderAll();
    if (!quiet) showToast("状态已刷新");
  } catch (requestError) {
    error.textContent = `无法读取插件状态：${requestError.message}`;
    error.classList.remove("hidden");
    $("#health").textContent = "连接失败";
    if (!quiet) showToast(requestError.message, true);
  }
}

function renderAll() {
  renderMetrics();
  renderTasks();
  renderTargets();
  $("#health").textContent = snapshot.status.enabled ? "服务已启用" : "服务已暂停";
  $("#health").classList.toggle("good", snapshot.status.enabled);
  $("#catalog-note").textContent = `本地目录 ${snapshot.status.hotels} 家酒店。最后检查：${
    snapshot.status.last_check ? new Date(snapshot.status.last_check).toLocaleString() : "尚未检查"
  }`;
}

function renderMetrics() {
  const status = snapshot.status;
  const values = [
    [status.enabled_tasks, "启用任务"],
    [status.active_slots, "活动需求"],
    [status.targets, "通知目标"],
    [status.hotels, "本地酒店"],
    [status.pending_events, "待重试通知"],
  ];
  $("#metrics").classList.remove("skeleton");
  $("#metrics").innerHTML = values
    .map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`)
    .join("");
}

function renderTasks() {
  const root = $("#tasks");
  root.classList.remove("loading-list");
  if (!snapshot.tasks.length) {
    root.innerHTML = '<div class="empty">还没有监控任务。先创建一个酒店与房型组合。</div>';
    return;
  }
  root.innerHTML = snapshot.tasks
    .map(
      (task) => `<article class="task-card" data-task-id="${escapeHtml(task.id)}">
        <div class="task-title-row">
          <div>
            <div class="task-title"><h3>${escapeHtml(task.name)}</h3><span class="badge ${
              task.enabled ? "active" : "paused"
            }">${task.enabled ? "已启用" : "未启用"}</span></div>
            <p class="task-meta">${escapeHtml(task.checkin)} 至 ${escapeHtml(task.checkout)} · ${
              task.hotel_ids.length
            } 家酒店 · 每 ${task.interval_seconds} 秒</p>
          </div>
        </div>
        <div class="slot-summary">
          ${task.slots
            .map(
              (slot) => `<div class="slot-row">
                <span><strong>${escapeHtml(slot.label)}</strong> · ${slot.occupants} 人 · ${
                  slot.subtypes.map((item) => subtypeLabels[item] || item).join(" / ") || "按自定义房型"
                }</span>
                <span class="badge ${slot.state}">${stateLabels[slot.state] || slot.state}</span>
                <select class="slot-state" data-slot-id="${escapeHtml(slot.id)}" aria-label="更改需求状态">
                  ${Object.entries(stateLabels)
                    .map(
                      ([value, label]) => `<option value="${value}" ${
                        slot.state === value ? "selected" : ""
                      }>${label}</option>`,
                    )
                    .join("")}
                </select>
              </div>`,
            )
            .join("")}
        </div>
        <div class="card-actions">
          <button class="button text-button task-check" type="button">立即检查</button>
          <button class="button text-button task-edit" type="button">编辑</button>
          <button class="button text-button danger-button task-delete" type="button">删除</button>
        </div>
      </article>`,
    )
    .join("");
}

function renderTargets() {
  const root = $("#targets");
  if (!snapshot.targets.length) {
    root.innerHTML = '<div class="empty">尚未添加 QQ 私聊或群聊目标。</div>';
    return;
  }
  root.innerHTML = snapshot.targets
    .map(
      (target) => `<div class="target-item" data-target-id="${escapeHtml(target.id)}">
        <div><strong>${escapeHtml(target.label)}</strong><span>${escapeHtml(target.umo)}</span></div>
        <div class="mini-actions">
          <button class="button text-button target-test" type="button">测试</button>
          <button class="button text-button danger-button target-delete" type="button">删除</button>
        </div>
      </div>`,
    )
    .join("");
}

function defaultTask() {
  const now = new Date();
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 2);
  const localDate = (value) => {
    const offset = value.getTimezoneOffset() * 60000;
    return new Date(value - offset).toISOString().slice(0, 10);
  };
  return {
    id: makeId("watch"), name: "", enabled: false, hotel_ids: ["00075", "00073"],
    checkin: localDate(tomorrow), checkout: localDate(next), interval_seconds: 300,
    notify_changes: false, email_enabled: false, target_ids: [],
    slots: [defaultSlot("single"), defaultSlot("multi")],
  };
}

function defaultSlot(category = "single") {
  return {
    id: makeId("slot"), label: category === "single" ? "单人房" : "双人房", state: "active",
    category, subtypes: [...categorySubtypes[category]], exact_names: [], keywords: [],
    occupants: category === "single" ? 1 : 2, smoking: "any", inventory: "either",
  };
}

async function openTask(task = null) {
  const data = structuredClone(task || defaultTask());
  $("#dialog-title").textContent = task ? "编辑监控任务" : "新建监控任务";
  $("#task-id").value = data.id;
  $("#task-name").value = data.name;
  $("#task-checkin").value = data.checkin;
  $("#task-checkout").value = data.checkout;
  $("#task-interval").value = data.interval_seconds;
  $("#task-enabled").checked = data.enabled;
  $("#task-notify-changes").checked = data.notify_changes;
  $("#task-email").checked = data.email_enabled;
  selectedHotels = new Map(data.hotel_ids.map((id) => [id, { hotel_id: id, name: id }]));
  renderSelectedHotels();
  renderSlots(data.slots);
  renderTaskTargets(data.target_ids);
  $("#probe-results").classList.add("hidden");
  $("#hotel-search").value = "";
  await searchHotels("");
  await Promise.all(data.hotel_ids.map((id) => searchOneSelectedHotel(id)));
  renderSelectedHotels();
  $("#task-dialog").showModal();
}

async function searchOneSelectedHotel(id) {
  try {
    const result = await bridge.apiGet("hotels", { q: id, limit: 1 });
    if (result.hotels?.[0]?.hotel_id === id) selectedHotels.set(id, result.hotels[0]);
  } catch (_) {
    // The saved ID remains selectable if the local search request fails.
  }
}

function renderSelectedHotels() {
  $("#hotel-count").textContent = `${selectedHotels.size} 家已选`;
  $("#selected-hotels").innerHTML = [...selectedHotels.values()]
    .map(
      (hotel) => `<span class="chip">${escapeHtml(hotel.name)} <code>${escapeHtml(
        hotel.hotel_id,
      )}</code><button type="button" data-remove-hotel="${escapeHtml(hotel.hotel_id)}" aria-label="移除">×</button></span>`,
    )
    .join("");
}

async function searchHotels(query) {
  const root = $("#hotel-results");
  root.innerHTML = '<div class="empty">正在检索本地目录</div>';
  try {
    const result = await bridge.apiGet("hotels", { q: query, limit: 60 });
    if (!result.hotels.length) {
      root.innerHTML = '<div class="empty">没有匹配的酒店</div>';
      return;
    }
    root.innerHTML = result.hotels
      .map(
        (hotel) => `<button class="hotel-option" type="button" data-hotel-id="${escapeHtml(
          hotel.hotel_id,
        )}"><code>${escapeHtml(hotel.hotel_id)}</code><span>${escapeHtml(
          hotel.name,
        )}<small>${escapeHtml(hotel.prefecture)} ${escapeHtml(hotel.city)} · ${escapeHtml(
          hotel.address,
        )}</small></span></button>`,
      )
      .join("");
    $$(".hotel-option", root).forEach((button, index) => {
      button.addEventListener("click", () => {
        const hotel = result.hotels[index];
        selectedHotels.set(hotel.hotel_id, hotel);
        renderSelectedHotels();
      });
    });
  } catch (error) {
    root.innerHTML = `<div class="empty">检索失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderTaskTargets(selectedIds) {
  const root = $("#task-targets");
  if (!snapshot.targets.length) {
    root.innerHTML = '<div class="empty">请先在主页面添加 QQ 通知目标。</div>';
    return;
  }
  root.innerHTML = snapshot.targets
    .map(
      (target) => `<label><input type="checkbox" value="${escapeHtml(target.id)}" ${
        selectedIds.includes(target.id) ? "checked" : ""
      } />${escapeHtml(target.label)} · ${target.kind === "group" ? "群聊" : "私聊"}</label>`,
    )
    .join("");
}

function renderSlots(slots) {
  const root = $("#slots");
  root.innerHTML = slots.map(slotTemplate).join("");
}

function slotTemplate(slot) {
  const subtypes = categorySubtypes[slot.category] || categorySubtypes.single;
  return `<div class="slot-editor" data-slot-id="${escapeHtml(slot.id)}">
    <div class="slot-editor-head"><strong>${escapeHtml(slot.label || "房间需求")}</strong><button class="button text-button danger-button remove-slot" type="button">移除</button></div>
    <div class="slot-grid">
      <label class="wide">需求名称<input data-field="label" value="${escapeHtml(slot.label)}" required /></label>
      <label>大类<select data-field="category"><option value="single" ${
        slot.category === "single" ? "selected" : ""
      }>单人</option><option value="multi" ${slot.category === "multi" ? "selected" : ""}>多人</option></select></label>
      <label>人数<input data-field="occupants" type="number" min="1" max="4" value="${slot.occupants}" /></label>
      <label>状态<select data-field="state">${Object.entries(stateLabels)
        .map(([value, label]) => `<option value="${value}" ${slot.state === value ? "selected" : ""}>${label}</option>`)
        .join("")}</select></label>
      <label>吸烟偏好<select data-field="smoking"><option value="any" ${slot.smoking === "any" ? "selected" : ""}>不限</option><option value="non_smoking" ${slot.smoking === "non_smoking" ? "selected" : ""}>禁烟</option><option value="smoking" ${slot.smoking === "smoking" ? "selected" : ""}>吸烟</option></select></label>
      <label>库存类型<select data-field="inventory"><option value="either" ${slot.inventory === "either" ? "selected" : ""}>一般或会员</option><option value="general" ${slot.inventory === "general" ? "selected" : ""}>仅一般</option><option value="member" ${slot.inventory === "member" ? "selected" : ""}>仅会员</option></select></label>
      <label class="wide">官网精确房型名<input data-field="exact_names" value="${escapeHtml(slot.exact_names.join(", "))}" placeholder="多个名称用逗号分隔" /></label>
      <label class="wide">日文关键词<input data-field="keywords" value="${escapeHtml(slot.keywords.join(", "))}" placeholder="例如：ワイド, デラックス" /></label>
      <div class="subtypes">${subtypes
        .map(
          (subtype) => `<label><input type="checkbox" data-subtype="${subtype}" ${
            slot.subtypes.includes(subtype) ? "checked" : ""
          } />${subtypeLabels[subtype]}</label>`,
        )
        .join("")}</div>
    </div>
  </div>`;
}

function parseList(value) {
  return value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
}

function serializeSlots() {
  return $$(".slot-editor", $("#slots")).map((node) => {
    const value = (field) => $(`[data-field="${field}"]`, node).value;
    return {
      id: node.dataset.slotId, label: value("label"), state: value("state"), category: value("category"),
      subtypes: $$('[data-subtype]:checked', node).map((input) => input.dataset.subtype),
      exact_names: parseList(value("exact_names")), keywords: parseList(value("keywords")),
      occupants: Number(value("occupants")), smoking: value("smoking"), inventory: value("inventory"),
    };
  });
}

function taskPayload() {
  return {
    id: $("#task-id").value, name: $("#task-name").value.trim(), enabled: $("#task-enabled").checked,
    hotel_ids: [...selectedHotels.keys()], checkin: $("#task-checkin").value,
    checkout: $("#task-checkout").value, slots: serializeSlots(),
    target_ids: $$('#task-targets input:checked').map((input) => input.value),
    email_enabled: $("#task-email").checked, notify_changes: $("#task-notify-changes").checked,
    interval_seconds: Number($("#task-interval").value),
  };
}

async function saveTask(event) {
  event.preventDefault();
  const button = $("#save-task");
  try {
    await withButton(button, "正在保存", () => bridge.apiPost("tasks", taskPayload()));
    $("#task-dialog").close();
    await loadSnapshot(true);
    showToast("任务已保存");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function probeRooms(button) {
  const payload = taskPayload();
  if (!payload.hotel_ids.length || !payload.checkin || !payload.checkout) {
    showToast("请先选择酒店和日期", true);
    return;
  }
  const occupants = [...new Set(payload.slots.map((slot) => slot.occupants))];
  try {
    const groups = [];
    await withButton(button, "正在探测", async () => {
      for (const count of occupants) {
        const result = await bridge.apiPost("rooms/probe", {
          hotel_ids: payload.hotel_ids, checkin: payload.checkin, checkout: payload.checkout, occupants: count,
        });
        groups.push({ occupants: count, results: result.results });
      }
    });
    const root = $("#probe-results");
    root.innerHTML = groups
      .flatMap((group) => group.results.map((item) => `<div class="probe-hotel"><strong>${escapeHtml(item.hotel_name || item.hotel_id)} · ${group.occupants} 人</strong><br />${item.rooms.map((room) => `${escapeHtml(room.name)}（${room.smoking === "smoking" ? "吸烟" : "禁烟"}）`).join("、") || "官网未返回房型"}</div>`))
      .join("");
    root.classList.remove("hidden");
  } catch (error) {
    showToast(error.message, true);
  }
}

$("#reload").addEventListener("click", (event) => withButton(event.currentTarget, "正在刷新", () => loadSnapshot(true)));
$("#new-task").addEventListener("click", () => openTask());
$("#close-dialog").addEventListener("click", () => $("#task-dialog").close());
$("#cancel-task").addEventListener("click", () => $("#task-dialog").close());
$("#task-form").addEventListener("submit", saveTask);
$("#add-slot").addEventListener("click", () => {
  const slots = serializeSlots();
  slots.push(defaultSlot("single"));
  renderSlots(slots);
});
$("#probe-rooms").addEventListener("click", (event) => probeRooms(event.currentTarget));
$("#hotel-search").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => searchHotels(event.target.value.trim()), 220);
});
$("#selected-hotels").addEventListener("click", (event) => {
  const id = event.target.dataset.removeHotel;
  if (id) { selectedHotels.delete(id); renderSelectedHotels(); }
});
$("#slots").addEventListener("click", (event) => {
  if (!event.target.classList.contains("remove-slot")) return;
  event.target.closest(".slot-editor").remove();
});
$("#slots").addEventListener("change", (event) => {
  if (event.target.dataset.field !== "category") return;
  const changed = event.target.closest(".slot-editor");
  const slots = serializeSlots();
  const slot = slots.find((item) => item.id === changed.dataset.slotId);
  slot.subtypes = [...categorySubtypes[slot.category]];
  slot.occupants = slot.category === "single" ? 1 : 2;
  renderSlots(slots);
});

$("#tasks").addEventListener("click", async (event) => {
  const card = event.target.closest(".task-card");
  if (!card) return;
  const task = snapshot.tasks.find((item) => item.id === card.dataset.taskId);
  if (event.target.classList.contains("task-edit")) return openTask(task);
  if (event.target.classList.contains("task-check")) {
    try {
      const result = await withButton(event.target, "检查中", () => bridge.apiPost(`tasks/${task.id}/check`, {}));
      await loadSnapshot(true);
      showToast(`检查完成：新命中 ${result.new_events}，错误 ${result.errors.length}`);
    } catch (error) { showToast(error.message, true); }
  }
  if (event.target.classList.contains("task-delete") && confirm(`确定删除“${task.name}”吗？`)) {
    try {
      await bridge.apiPost(`tasks/${task.id}/delete`, {});
      await loadSnapshot(true);
      showToast("任务已删除");
    } catch (error) { showToast(error.message, true); }
  }
});

$("#tasks").addEventListener("change", async (event) => {
  if (!event.target.classList.contains("slot-state")) return;
  const card = event.target.closest(".task-card");
  try {
    await bridge.apiPost(`tasks/${card.dataset.taskId}/slots/${event.target.dataset.slotId}/state`, { state: event.target.value });
    await loadSnapshot(true);
    showToast("需求状态已更新");
  } catch (error) { showToast(error.message, true); await loadSnapshot(true); }
});

$("#target-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const kind = $("#target-kind").value;
  const number = $("#target-number").value.trim();
  const payload = {
    id: $("#target-id").value || `${kind}-${number}`, label: $("#target-label").value.trim(),
    kind, number, enabled: true,
  };
  try {
    await bridge.apiPost("targets", payload);
    event.target.reset();
    await loadSnapshot(true);
    showToast("通知目标已保存");
  } catch (error) { showToast(error.message, true); }
});

$("#targets").addEventListener("click", async (event) => {
  const item = event.target.closest(".target-item");
  if (!item) return;
  const id = item.dataset.targetId;
  try {
    if (event.target.classList.contains("target-test")) {
      await withButton(event.target, "发送中", () => bridge.apiPost(`targets/${id}/test`, {}));
      showToast("QQ 测试消息已发送");
    }
    if (event.target.classList.contains("target-delete") && confirm("确定删除这个通知目标吗？")) {
      await bridge.apiPost(`targets/${id}/delete`, {});
      await loadSnapshot(true);
      showToast("通知目标已删除");
    }
  } catch (error) { showToast(error.message, true); }
});

$("#refresh-catalog").addEventListener("click", async (event) => {
  try {
    const result = await withButton(event.currentTarget, "正在从官网刷新", () => bridge.apiPost("catalog/refresh", {}));
    await loadSnapshot(true);
    showToast(`酒店目录已更新，共 ${result.hotels} 家`);
  } catch (error) { showToast(error.message, true); }
});

$("#test-email").addEventListener("click", async (event) => {
  try {
    await withButton(event.currentTarget, "发送中", () => bridge.apiPost("email/test", {}));
    showToast("测试邮件已发送");
  } catch (error) { showToast(error.message, true); }
});

await bridge.ready();
await loadSnapshot(true);
