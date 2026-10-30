"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  page: "dashboard",
  operator: localStorage.getItem("reestr.operator") || "",
  contractsPage: 1,
  contractsPages: 1,
  contracts: new Map(),
  reportType: "counterparties",
  report: null,
  conflict: null,
  importFile: null,
  importPreview: null,
  backups: new Map(),
  pendingRestore: null,
  restoring: false,
  admin: { configured: false, authenticated: false, username: null },
  toastTimer: null,
};

const PAGE_INFO = {
  dashboard: ["Главная", "Контроль договоров и оплат в одном окне"],
  contracts: ["Договоры", "Общий реестр с совместным редактированием"],
  reports: ["Отчёты", "Анализ контрагентов, сроков и просроченных оплат"],
  import: ["Импорт Excel", "Загрузка данных из существующего реестра"],
  backups: ["Копии и восстановление", "Расписание резервных копий и простое восстановление базы"],
};

const FIELD_LABELS = {
  party_type: "Тип контрагента",
  counterparty: "Контрагент",
  country: "Страна",
  contract_number: "Номер договора",
  contract_date: "Дата договора",
  request_number: "Номер заявки",
  request_date: "Дата заявки",
  invoice_number: "Номер счёта",
  invoice_date: "Дата счёта",
  invoice_status: "Статус счёта",
  payment_date: "Дата оплаты",
  payment_due_date: "Срок оплаты",
  payment_terms: "Условия оплаты",
  avr_number: "Номер АВР",
  avr_date: "Дата АВР",
  avr_amount: "Сумма АВР",
  vat_amount: "НДС",
  currency: "Валюта",
  client: "Под клиента",
  notes: "Примечания",
  payment_reference: "Платёжное поручение",
  date_from: "Начало периода",
  date_to: "Конец периода",
  version: "Версия записи",
};

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(value) {
  return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
}

function dateText(value) {
  if (!value) return "—";
  const parts = String(value).slice(0, 10).split("-");
  return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : String(value);
}

function dateTimeText(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function debounce(callback, delay = 350) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => callback(...args), delay);
  };
}

function toast(message, isError = false) {
  const element = $("#toast");
  clearTimeout(state.toastTimer);
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.add("visible");
  state.toastTimer = setTimeout(() => element.classList.remove("visible"), 4500);
}

function setConnection(online, text) {
  $("#connection-dot").className = `status-dot ${online ? "online" : "offline"}`;
  $("#connection-text").textContent = text || (online ? "Сервер доступен" : "Нет связи с сервером");
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  headers.set("X-Operator", encodeURIComponent(state.operator || "Не указан"));
  let body = options.body;
  if (body && !(body instanceof FormData) && typeof body !== "string") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  try {
    const response = await fetch(path, { ...options, headers, body });
    const contentType = response.headers.get("Content-Type") || "";
    const data = contentType.includes("json") ? await response.json() : { error: await response.text() };
    if (!response.ok) {
      if (data.code === "admin_required") applyAdmin({ configured: true, authenticated: false, username: null });
      if (data.code === "admin_not_configured") applyAdmin({ configured: false, authenticated: false, username: null });
      throw new ApiError(data.error || `Ошибка сервера (${response.status})`, response.status, data);
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    setConnection(false);
    throw new ApiError("Нет связи с сервером. Проверьте сетевой ярлык и запуск серверной части.", 0, {});
  }
}

function updateOperator() {
  const name = state.operator || "Не указан";
  $("#operator-name").textContent = name;
  $("#operator-avatar").textContent = state.operator ? [...state.operator.trim()][0].toUpperCase() : "—";
}

function requireOperator() {
  if (state.operator) return true;
  $("#operator-dialog").showModal();
  toast("Сначала укажите ваше имя", true);
  return false;
}

function applyAdmin(session) {
  state.admin = {
    configured: !!session.configured,
    authenticated: !!session.authenticated,
    username: session.username || null,
  };
  const authenticated = state.admin.authenticated;
  $("#backups-nav").hidden = !authenticated;
  $("#sidebar-backup-link").hidden = !authenticated;
  $("#admin-button").classList.toggle("authenticated", authenticated);
  $("#admin-button-text").textContent = authenticated ? `Админ: ${state.admin.username}` : "Администратор";
  $("#admin-login-view").hidden = authenticated;
  $("#admin-profile-view").hidden = !authenticated;
  $("#admin-not-configured").hidden = state.admin.configured;
  if (authenticated) $("#admin-profile-name").textContent = state.admin.username;
  if (!authenticated && state.page === "backups") showPage("dashboard");
}

async function loadAdminSession() {
  try {
    applyAdmin(await api("/api/admin/session"));
  } catch (error) {
    console.error(error);
  }
}

function openAdmin() {
  if (!state.admin.authenticated) {
    const form = $("#admin-login-form");
    form.reset();
    $("#admin-login-message").hidden = true;
  }
  if (!$("#admin-dialog").open) $("#admin-dialog").showModal();
  if (!state.admin.authenticated) setTimeout(() => $("#admin-login-form").elements.password.focus(), 50);
}

async function loginAdmin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#admin-login-submit");
  const message = $("#admin-login-message");
  button.disabled = true;
  message.hidden = true;
  try {
    const result = await api("/api/admin/login", {
      method: "POST",
      body: { username: form.elements.username.value.trim(), password: form.elements.password.value },
    });
    applyAdmin({ configured: true, authenticated: true, username: result.username });
    form.reset();
    $("#admin-dialog").close();
    toast("Вход администратора выполнен");
    showPage("backups");
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function logoutAdmin() {
  try {
    await api("/api/admin/logout", { method: "POST", body: {} });
    applyAdmin({ configured: state.admin.configured, authenticated: false, username: null });
    $("#admin-dialog").close();
    toast("Вы вышли из административной сессии");
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadHealth(silent = false) {
  try {
    const health = await api("/api/health");
    setConnection(true);
    $("#app-version").textContent = `Версия ${health.version} · SQLite`;
    return health;
  } catch (error) {
    if (!silent) toast(error.message, true);
    return null;
  }
}

function replaceOptions(select, values, allLabel) {
  const current = select.value;
  select.replaceChildren();
  const first = document.createElement("option");
  first.value = "";
  first.textContent = allLabel;
  select.append(first);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
  if (values.includes(current)) select.value = current;
}

async function loadMeta() {
  try {
    const meta = await api("/api/meta");
    $$('[data-counterparties]').forEach((select) => replaceOptions(select, meta.counterparties, "Все контрагенты"));
    const currencies = [...new Set(["RUB", "BYN", "USD", "EUR", "CNY", ...meta.currencies])].sort();
    $$('[data-currencies]').forEach((select) => replaceOptions(select, currencies, "Все валюты"));
    const dataList = $("#counterparty-list");
    dataList.replaceChildren();
    meta.counterparties.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      dataList.append(option);
    });
  } catch (error) {
    console.error(error);
  }
}

function showPage(page) {
  if (!PAGE_INFO[page]) return;
  if (page === "backups" && !state.admin.authenticated) {
    openAdmin();
    toast("Для управления копиями войдите как администратор", true);
    return;
  }
  state.page = page;
  $$(".page").forEach((section) => {
    const active = section.id === `page-${page}`;
    section.hidden = !active;
    section.classList.toggle("active", active);
  });
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.page === page));
  $("#page-title").textContent = PAGE_INFO[page][0];
  $("#page-subtitle").textContent = PAGE_INFO[page][1];
  if (page === "dashboard") loadDashboard(true);
  if (page === "contracts") loadContracts(true);
  if (page === "reports" && !state.report) generateReport();
  if (page === "backups") {
    loadBackupSettings();
    loadBackups();
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}

function statusBadge(item) {
  const days = item.days_overdue ? ` · ${item.days_overdue} дн.` : "";
  return `<span class="badge ${esc(item.code)}" title="${esc(item.label)}">${esc(item.label)}${days}</span>`;
}

function dashboardRow(item, overdue = false) {
  return `<tr>
    <td><strong class="cell-title">${esc(item.counterparty)}</strong><span class="cell-subtitle">${esc(item.contract_number)}</span></td>
    <td>${esc(item.invoice_number || "—")}</td>
    <td>${overdue ? `<span class="validation-ok" hidden></span><strong>${item.days_overdue} дн.</strong><span class="cell-subtitle">срок ${dateText(item.payment_due_date)}</span>` : `${dateText(item.payment_due_date)}${item.code === "due_soon" ? '<span class="cell-subtitle">скоро</span>' : ""}`}</td>
    <td class="number amount">${money(item.avr_amount)}<small>${esc(item.currency)}</small></td>
  </tr>`;
}

function renderHistory(items) {
  const actions = {
    create: ["＋", "Создана запись"],
    update: ["✎", "Изменена запись"],
    delete: ["×", "Удалена запись"],
    import: ["⇥", "Импортирована запись"],
  };
  $("#dashboard-history").innerHTML = items.length ? items.map((item) => {
    const action = actions[item.action] || ["•", item.action];
    return `<div class="history-item"><span class="history-action">${action[0]}</span><div><strong>${esc(action[1])}</strong><span class="cell-subtitle">${esc(item.counterparty || "—")} · ${esc(item.contract_number || "—")}</span></div><span class="history-user">${esc(item.actor)}</span><time class="history-date">${dateTimeText(item.changed_at)}</time></div>`;
  }).join("") : '<div class="empty-state compact">История изменений пока пуста</div>';
}

async function loadDashboard(silent = false) {
  try {
    const data = await api("/api/dashboard");
    $("#metric-contracts").textContent = data.totals.contracts;
    $("#metric-counterparties").textContent = `${data.totals.counterparties} контрагентов`;
    $("#metric-unpaid").textContent = data.totals.unpaid;
    $("#metric-due-soon").textContent = `${data.totals.due_soon} в ближайшие 7 дней`;
    $("#metric-overdue").textContent = data.totals.overdue;
    $("#metric-paid-late").textContent = `${data.totals.paid_late} оплачено позже срока`;
    $("#metric-outstanding").innerHTML = data.amounts.length
      ? data.amounts.map((item) => `<div>${money(item.outstanding)} <small>${esc(item.currency)}</small></div>`).join("")
      : "0,00";
    $("#dashboard-upcoming").innerHTML = data.upcoming.map((item) => dashboardRow(item)).join("");
    $("#dashboard-overdue").innerHTML = data.overdue_items.map((item) => dashboardRow(item, true)).join("");
    $("#upcoming-empty").hidden = data.upcoming.length > 0;
    $("#overdue-empty").hidden = data.overdue_items.length > 0;
    $("#dashboard-upcoming").closest(".table-wrap").hidden = !data.upcoming.length;
    $("#dashboard-overdue").closest(".table-wrap").hidden = !data.overdue_items.length;
    renderHistory(data.history);
  } catch (error) {
    if (!silent) toast(error.message, true);
  }
}

function contractQuery() {
  const params = new URLSearchParams(new FormData($("#contract-filters")));
  [...params].forEach(([key, value]) => { if (!value) params.delete(key); });
  params.set("page", state.contractsPage);
  params.set("page_size", 50);
  return params;
}

function contractRow(item) {
  const contractDate = item.contract_date ? ` от ${dateText(item.contract_date)}` : "";
  const avrDate = item.avr_date ? ` от ${dateText(item.avr_date)}` : "";
  return `<tr>
    <td><strong class="cell-title">${esc(item.counterparty)}</strong><span class="cell-subtitle">${esc(item.party_type)} · ${esc(item.contract_number)}${contractDate}</span><span class="cell-subtitle">${esc(item.country || "")}</span></td>
    <td><strong class="cell-title">${esc(item.invoice_number || "Без счёта")}</strong><span class="cell-subtitle">Заявка: ${esc(item.request_number || "—")}</span></td>
    <td>${esc(item.avr_number || "—")}<span class="cell-subtitle">${avrDate ? avrDate.slice(4) : ""}</span></td>
    <td>${dateText(item.payment_due_date)}${item.payment_terms ? `<span class="cell-subtitle">${esc(item.payment_terms)}</span>` : ""}</td>
    <td class="number amount">${money(item.avr_amount)}<small>${esc(item.currency)} · НДС ${money(item.vat_amount)}</small></td>
    <td>${statusBadge(item)}</td>
    <td class="no-print"><div class="row-actions"><button class="icon-button" data-action="edit-contract" data-id="${item.id}" title="Редактировать">✎</button></div></td>
  </tr>`;
}

async function loadContracts(silent = false) {
  try {
    const data = await api(`/api/contracts?${contractQuery()}`);
    if (data.page > data.pages && data.total) {
      state.contractsPage = data.pages;
      return loadContracts(silent);
    }
    state.contractsPages = data.pages;
    state.contracts = new Map(data.items.map((item) => [item.id, item]));
    $("#contracts-table").innerHTML = data.items.map(contractRow).join("");
    $("#contracts-empty").hidden = data.items.length > 0;
    $("#contracts-table").closest(".table-wrap").hidden = !data.items.length;
    $("#contracts-count").textContent = `${data.total} записей · одновременная работа с общей базой`;
    $("#contracts-page").textContent = `${data.page} / ${data.pages}`;
    $("#contracts-prev").disabled = data.page <= 1;
    $("#contracts-next").disabled = data.page >= data.pages;
  } catch (error) {
    if (!silent) toast(error.message, true);
  }
}

function clearFormErrors() {
  $$('[aria-invalid="true"]', $("#contract-form")).forEach((input) => input.removeAttribute("aria-invalid"));
  $("#contract-form-message").hidden = true;
}

function openContract(item = null) {
  const form = $("#contract-form");
  form.reset();
  clearFormErrors();
  form.elements.country.value = "РФ";
  form.elements.currency.value = "RUB";
  form.elements.avr_amount.value = "0";
  form.elements.vat_amount.value = "0";
  form.elements.id.value = "";
  form.elements.version.value = "";
  $("#delete-contract-button").hidden = !item;
  $("#contract-dialog-title").textContent = item ? `Договор ${item.contract_number}` : "Новый договор";
  if (item) {
    Object.entries(item).forEach(([key, value]) => {
      if (form.elements[key] && !["id", "version"].includes(key)) form.elements[key].value = value ?? "";
    });
    form.elements.id.value = item.id;
    form.elements.version.value = item.version;
    $("#record-meta").textContent = `Версия ${item.version} · ${item.updated_by || "—"} · ${dateTimeText(item.updated_at)}`;
  } else {
    $("#record-meta").textContent = "Новая запись в общей базе";
  }
  if (!$("#contract-dialog").open) $("#contract-dialog").showModal();
  setTimeout(() => form.elements.counterparty.focus(), 50);
}

function showValidation(data) {
  const fields = data.fields || {};
  Object.keys(fields).forEach((field) => {
    const input = $("#contract-form").elements[field];
    if (input) input.setAttribute("aria-invalid", "true");
  });
  const details = Object.entries(fields).map(([field, message]) => `${FIELD_LABELS[field] || field}: ${message}`).join("; ");
  const element = $("#contract-form-message");
  element.textContent = details || data.error || "Проверьте данные";
  element.hidden = false;
}

async function saveContract(event) {
  event.preventDefault();
  if (!requireOperator()) return;
  clearFormErrors();
  const form = $("#contract-form");
  const payload = Object.fromEntries(new FormData(form));
  const id = payload.id;
  delete payload.id;
  const button = $("#save-contract-button");
  button.disabled = true;
  button.textContent = "Сохранение…";
  try {
    await api(id ? `/api/contracts/${id}` : "/api/contracts", { method: id ? "PUT" : "POST", body: payload });
    $("#contract-dialog").close();
    toast(id ? "Изменения сохранены" : "Договор зарегистрирован");
    await Promise.all([loadMeta(), loadDashboard(true), loadContracts(true)]);
    state.report = null;
  } catch (error) {
    if (error.status === 409 && error.data.code === "version_conflict") {
      state.conflict = error.data.current;
      $("#conflict-dialog").showModal();
    } else if (error.status === 422) {
      showValidation(error.data);
    } else {
      showValidation({ error: error.message });
    }
  } finally {
    button.disabled = false;
    button.textContent = "Сохранить";
  }
}

async function deleteContract() {
  if (!requireOperator()) return;
  const form = $("#contract-form");
  const id = form.elements.id.value;
  const version = form.elements.version.value;
  if (!id || !confirm("Удалить эту запись из реестра? Операция сохранится в истории.")) return;
  try {
    await api(`/api/contracts/${id}`, { method: "DELETE", body: { version } });
    $("#contract-dialog").close();
    toast("Запись удалена");
    await Promise.all([loadMeta(), loadDashboard(true), loadContracts(true)]);
    state.report = null;
  } catch (error) {
    if (error.status === 409 && error.data.current) {
      state.conflict = error.data.current;
      $("#conflict-dialog").showModal();
    } else showValidation({ error: error.message });
  }
}

function setReportType(type, status = null) {
  state.reportType = type;
  state.report = null;
  $$(".report-tab").forEach((button) => button.classList.toggle("active", button.dataset.report === type));
  if (status !== null) $("#report-status").value = status;
  if (state.page === "reports") generateReport();
}

function reportQuery() {
  const params = new URLSearchParams(new FormData($("#report-filters")));
  [...params].forEach(([key, value]) => { if (!value) params.delete(key); });
  return params;
}

function reportCell(value, kind) {
  if (value === null || value === "" || value === undefined) return "—";
  if (kind === "money") return money(value);
  if (kind === "date") return dateText(value);
  return esc(value);
}

function renderReport(report) {
  state.report = report;
  $("#report-title").textContent = report.title;
  const filterText = Object.entries(report.filters).map(([key, value]) => `${FIELD_LABELS[key] || key}: ${key.startsWith("date_") ? dateText(value) : value}`).join(" · ");
  $("#report-meta").textContent = `Сформирован ${dateTimeText(report.generated_at)} · ${report.row_count} строк${filterText ? ` · ${filterText}` : ""}`;
  $("#report-totals").innerHTML = report.totals.map((total) => `<span class="total-chip">${esc(total.currency)}<strong>всего ${money(total.amount)}</strong><span> · к оплате ${money(total.outstanding)} · просрочено ${money(total.overdue)}</span></span>`).join("");
  $("#report-head").innerHTML = `<tr>${report.columns.map((column) => `<th class="${["money", "integer"].includes(column.kind) ? "number" : ""}">${esc(column.title)}</th>`).join("")}</tr>`;
  $("#report-body").innerHTML = report.rows.map((row) => `<tr>${report.columns.map((column) => `<td class="${["money", "integer"].includes(column.kind) ? "number" : ""}">${reportCell(row[column.key], column.kind)}</td>`).join("")}</tr>`).join("");
  $("#report-empty").hidden = report.rows.length > 0;
  $("#report-body").closest(".table-wrap").hidden = !report.rows.length;
}

async function generateReport() {
  $("#report-loading").hidden = false;
  try {
    const report = await api(`/api/reports/${state.reportType}?${reportQuery()}`);
    renderReport(report);
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("#report-loading").hidden = true;
  }
}

async function downloadReport(format) {
  const path = `/api/reports/${state.reportType}/export/${format}?${reportQuery()}`;
  try {
    const response = await fetch(path);
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || "Не удалось сформировать файл");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `otchet_${state.reportType}.${format}`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Файл отчёта подготовлен");
  } catch (error) {
    toast(error.message, true);
  }
}

async function printReport() {
  if (!state.report) await generateReport();
  if (!state.report) return;
  document.body.classList.add("print-report");
  const cleanup = () => document.body.classList.remove("print-report");
  window.addEventListener("afterprint", cleanup, { once: true });
  window.print();
  setTimeout(cleanup, 1500);
}

function bytesText(bytes) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

function importMessage(text, type = "") {
  const element = $("#import-message");
  element.textContent = text;
  element.className = `message ${type}`;
  element.hidden = !text;
}

function clearImport() {
  state.importFile = null;
  state.importPreview = null;
  $("#import-file").value = "";
  $("#import-selected").hidden = true;
  $("#import-preview").hidden = true;
  $("#import-preview-button").disabled = true;
  importMessage("");
}

function selectImportFile(file) {
  if (!file) return;
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    toast("Выберите файл .xlsx или .xls", true);
    return;
  }
  if (file.size > 15 * 1024 * 1024) {
    toast("Файл больше 15 МБ", true);
    return;
  }
  state.importFile = file;
  state.importPreview = null;
  $("#import-filename").textContent = file.name;
  $("#import-filesize").textContent = bytesText(file.size);
  $("#import-selected").hidden = false;
  $("#import-preview").hidden = true;
  $("#import-preview-button").disabled = false;
  importMessage("");
}

function importFormData() {
  const data = new FormData();
  data.append("file", state.importFile, state.importFile.name);
  return data;
}

function renderImportPreview(preview) {
  state.importPreview = preview;
  $("#import-preview").hidden = false;
  $("#import-summary").textContent = `Всего ${preview.total} · корректных ${preview.valid} · с ошибками ${preview.invalid}${preview.preview_truncated ? ` · показаны первые ${preview.rows.length}` : ""}`;
  const existing = $("#import-existing");
  existing.hidden = !preview.already_imported;
  if (preview.already_imported) existing.textContent = `Этот файл уже импортирован ${dateTimeText(preview.already_imported.imported_at)} пользователем ${preview.already_imported.operator}. Повторный импорт заблокирован.`;
  $("#import-commit-button").disabled = !preview.valid || !!preview.already_imported;
  $("#import-preview-table").innerHTML = preview.rows.map((row) => {
    const data = row.data;
    const errors = Object.entries(row.errors).map(([field, message]) => `${FIELD_LABELS[field] || field}: ${message}`).join("; ");
    return `<tr><td>${row.source_row}</td><td>${esc(data.counterparty)}</td><td>${esc(data.contract_number)}<span class="cell-subtitle">${dateText(data.contract_date)}</span></td><td>${esc(data.invoice_number || "—")}</td><td>${dateText(data.payment_due_date)}${data.payment_terms ? `<span class="cell-subtitle">${esc(data.payment_terms)}</span>` : ""}</td><td class="number amount">${money(data.avr_amount)}<small>${esc(data.currency)}</small></td><td>${errors ? `<span class="validation-error">${esc(errors)}</span>` : '<span class="validation-ok">✓ Готова к импорту</span>'}</td></tr>`;
  }).join("");
  $("#import-preview").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function previewImport() {
  if (!state.importFile) return;
  const button = $("#import-preview-button");
  button.disabled = true;
  button.textContent = "Проверка…";
  try {
    const preview = await api("/api/import/preview", { method: "POST", body: importFormData() });
    renderImportPreview(preview);
    importMessage(`Файл проверен: ${preview.valid} строк готово, ${preview.invalid} с ошибками.`, preview.invalid ? "warning" : "success");
  } catch (error) {
    importMessage(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Предпросмотр";
  }
}

async function commitImport() {
  if (!requireOperator() || !state.importFile || !state.importPreview || state.importPreview.already_imported) return;
  const preview = state.importPreview;
  if (!confirm(`Импортировать ${preview.valid} корректных строк?${preview.invalid ? ` ${preview.invalid} строк с ошибками будут пропущены.` : ""}`)) return;
  const button = $("#import-commit-button");
  button.disabled = true;
  button.textContent = "Импорт…";
  try {
    const result = await api("/api/import/commit", { method: "POST", body: importFormData() });
    clearImport();
    importMessage(`Импорт завершён: добавлено ${result.imported}, пропущено с ошибками ${result.rejected}.`, "success");
    toast(`Импортировано ${result.imported} записей`);
    await Promise.all([loadMeta(), loadDashboard(true), loadContracts(true)]);
    state.report = null;
  } catch (error) {
    importMessage(error.message, "error");
    button.disabled = false;
  } finally {
    button.textContent = "Импортировать";
  }
}

function backupMessage(text, type = "") {
  const element = $("#backup-message");
  element.textContent = text;
  element.className = `message ${type}`;
  element.hidden = !text;
}

function renderBackupSettings(settings) {
  const form = $("#backup-settings-form");
  form.elements.enabled.checked = !!settings.enabled;
  form.elements.time.value = settings.time || "03:00";
  form.elements.retention.value = settings.retention || 10;
  form.elements.directory.value = settings.directory || "";
  const status = [];
  status.push(`<div><strong>Расписание:</strong> ${settings.enabled ? `включено, ежедневно в ${esc(settings.time)}` : "выключено"}</div>`);
  if (settings.next_run_at) status.push(`<div><strong>Следующий запуск:</strong> ${dateTimeText(settings.next_run_at)}</div>`);
  if (settings.last_success_at) status.push(`<div><strong>Последняя успешная копия:</strong> ${dateTimeText(settings.last_success_at)}</div>`);
  if (settings.last_file) status.push(`<div><strong>Файл:</strong> ${esc(settings.last_file)}</div>`);
  if (settings.last_error) status.push(`<div class="status-error"><strong>Ошибка последнего запуска:</strong> ${esc(settings.last_error)}</div>`);
  if (!settings.last_success_at && !settings.last_error) status.push("<div>Автоматическая копия ещё не создавалась.</div>");
  $("#backup-schedule-status").innerHTML = status.join("");
}

async function loadBackupSettings() {
  try {
    renderBackupSettings(await api("/api/backup-settings"));
  } catch (error) {
    backupMessage(error.message, "error");
  }
}

async function saveBackupSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#save-backup-settings");
  button.disabled = true;
  try {
    const settings = await api("/api/backup-settings", {
      method: "PUT",
      body: {
        enabled: form.elements.enabled.checked,
        time: form.elements.time.value,
        retention: Number(form.elements.retention.value),
        directory: form.elements.directory.value.trim(),
      },
    });
    renderBackupSettings(settings);
    backupMessage("Настройки резервного копирования сохранены.", "success");
    toast("Расписание сохранено");
    loadBackups(true);
  } catch (error) {
    backupMessage(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function backupRow(item) {
  return `<tr><td><strong class="cell-title">${esc(item.name)}</strong></td><td>${esc(item.directory)}</td><td>${dateTimeText(item.created_at)}</td><td class="number">${bytesText(item.size)}</td><td><div class="row-actions"><a class="button secondary small" href="/api/backups/download?id=${encodeURIComponent(item.id)}" download>Скачать</a><button class="button secondary small" data-action="restore-backup" data-id="${esc(item.id)}">Восстановить</button></div></td></tr>`;
}

async function loadBackups(silent = false) {
  try {
    const data = await api("/api/backups");
    state.backups = new Map(data.items.map((item) => [item.id, item]));
    $("#backups-table").innerHTML = data.items.map(backupRow).join("");
    $("#backups-empty").hidden = data.items.length > 0;
    $("#backups-table").closest(".table-wrap").hidden = !data.items.length;
  } catch (error) {
    if (!silent) backupMessage(error.message, "error");
  }
}

async function createBackup() {
  const buttons = $$('[data-action="create-backup"]');
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const result = await api("/api/backups/create", { method: "POST", body: {} });
    backupMessage(`Копия создана: ${result.location}`, "success");
    toast("Резервная копия создана");
    await loadBackups(true);
  } catch (error) {
    backupMessage(error.message, "error");
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function openRestore(source) {
  state.pendingRestore = source;
  const form = $("#restore-form");
  form.reset();
  $("#restore-source-name").textContent = source.name;
  $("#restore-message").hidden = true;
  $("#restore-confirm-button").disabled = true;
  $("#restore-dialog").showModal();
  setTimeout(() => form.elements.confirmation.focus(), 50);
}

function closeRestore() {
  if (!state.restoring) $("#restore-dialog").close();
}

async function restoreDatabase(event) {
  event.preventDefault();
  if (!state.pendingRestore || state.restoring) return;
  const form = event.currentTarget;
  const confirmation = form.elements.confirmation.value.trim();
  if (confirmation.toUpperCase() !== "ВОССТАНОВИТЬ") return;
  const source = state.pendingRestore;
  const button = $("#restore-confirm-button");
  const message = $("#restore-message");
  state.restoring = true;
  button.disabled = true;
  button.textContent = "Проверка и восстановление…";
  message.hidden = true;
  try {
    let options;
    if (source.file) {
      const body = new FormData();
      body.append("file", source.file, source.file.name);
      body.append("confirmation", confirmation);
      options = { method: "POST", body };
    } else {
      options = { method: "POST", body: { backup_id: source.backupId, confirmation } };
    }
    const result = await api(source.file ? "/api/backups/restore-upload" : "/api/backups/restore", options);
    $("#restore-dialog").close();
    state.pendingRestore = null;
    $("#restore-file").value = "";
    $("#restore-upload-button").disabled = true;
    backupMessage(`База восстановлена из ${result.restored_from}: ${result.contracts} записей. Страховочная копия прежней базы: ${result.safety_backup.location}`, "success");
    toast(`База восстановлена: ${result.contracts} записей`);
    state.report = null;
    await Promise.all([loadMeta(), loadDashboard(true), loadContracts(true), loadBackupSettings(), loadBackups(true)]);
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    state.restoring = false;
    button.textContent = "Восстановить базу";
    button.disabled = form.elements.confirmation.value.trim().toUpperCase() !== "ВОССТАНОВИТЬ";
  }
}

async function refreshAll(showMessage = true) {
  await Promise.all([loadHealth(true), loadMeta(), loadDashboard(true), loadContracts(true)]);
  if (state.page === "backups") await Promise.all([loadBackupSettings(), loadBackups(true)]);
  if (showMessage) toast("Данные обновлены");
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page)));
  $("#admin-button").addEventListener("click", openAdmin);
  $("#developer-button").addEventListener("click", () => $("#developer-dialog").showModal());
  $("#admin-login-form").addEventListener("submit", loginAdmin);
  $("#contract-form").addEventListener("submit", saveContract);
  $("#contract-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    state.contractsPage = 1;
    loadContracts();
  });
  $("#contract-filters").elements.q.addEventListener("input", debounce(() => { state.contractsPage = 1; loadContracts(true); }));
  $$('select', $("#contract-filters")).forEach((select) => select.addEventListener("change", () => { state.contractsPage = 1; loadContracts(true); }));
  $("#report-filters").addEventListener("submit", (event) => { event.preventDefault(); generateReport(); });
  $("#backup-settings-form").addEventListener("submit", saveBackupSettings);
  $("#restore-form").addEventListener("submit", restoreDatabase);
  $("#restore-form").elements.confirmation.addEventListener("input", (event) => {
    if (!state.restoring) $("#restore-confirm-button").disabled = event.target.value.trim().toUpperCase() !== "ВОССТАНОВИТЬ";
  });
  $("#restore-file").addEventListener("change", (event) => {
    $("#restore-upload-button").disabled = !event.target.files[0];
  });
  $$(".report-tab").forEach((button) => button.addEventListener("click", () => setReportType(button.dataset.report, "")));
  $$("[data-export]").forEach((button) => button.addEventListener("click", () => downloadReport(button.dataset.export)));
  $("#contracts-prev").addEventListener("click", () => { if (state.contractsPage > 1) { state.contractsPage--; loadContracts(); } });
  $("#contracts-next").addEventListener("click", () => { if (state.contractsPage < state.contractsPages) { state.contractsPage++; loadContracts(); } });
  $("#operator-button").addEventListener("click", () => {
    $("#operator-form").elements.operator.value = state.operator;
    $("#operator-dialog").showModal();
  });
  $("#operator-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const name = event.currentTarget.elements.operator.value.trim();
    if (!name) return;
    state.operator = name;
    localStorage.setItem("reestr.operator", name);
    updateOperator();
    $("#operator-dialog").close();
    toast(`Пользователь: ${name}`);
  });
  $("#import-file").addEventListener("change", (event) => selectImportFile(event.target.files[0]));
  const dropzone = $("#import-dropzone");
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("dragover"); }));
  dropzone.addEventListener("drop", (event) => selectImportFile(event.dataTransfer.files[0]));

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const actions = {
      "close-admin": () => $("#admin-dialog").close(),
      "admin-logout": logoutAdmin,
      "open-backup-admin": () => { $("#admin-dialog").close(); showPage("backups"); },
      "close-developer": () => $("#developer-dialog").close(),
      "new-contract": () => { if (requireOperator()) openContract(); },
      "close-contract": () => $("#contract-dialog").close(),
      "delete-contract": deleteContract,
      "close-conflict": () => $("#conflict-dialog").close(),
      "reload-conflict": () => { $("#conflict-dialog").close(); if (state.conflict) openContract(state.conflict); },
      "refresh": () => refreshAll(),
      "refresh-contracts": () => loadContracts(),
      "reset-contract-filters": () => { $("#contract-filters").reset(); state.contractsPage = 1; loadContracts(); },
      "show-overdue": () => { showPage("reports"); setReportType("overdue", "overdue_unpaid"); },
      "show-payments": () => { showPage("reports"); setReportType("payments", "unpaid"); },
      "print-report": printReport,
      "clear-import": clearImport,
      "preview-import": previewImport,
      "commit-import": commitImport,
      "create-backup": createBackup,
      "refresh-backups": () => { loadBackupSettings(); loadBackups(); },
      "choose-restore-upload": () => {
        const file = $("#restore-file").files[0];
        if (file) openRestore({ file, name: file.name });
      },
      "close-restore": closeRestore,
    };
    if (target.dataset.action === "restore-backup") {
      const item = state.backups.get(target.dataset.id);
      if (item) openRestore({ backupId: item.id, name: item.name });
    } else if (target.dataset.action === "edit-contract") {
      const item = state.contracts.get(Number(target.dataset.id));
      if (item && requireOperator()) openContract(item);
    } else if (actions[target.dataset.action]) actions[target.dataset.action]();
  });
}

async function init() {
  updateOperator();
  bindEvents();
  await loadAdminSession();
  await Promise.all([loadHealth(true), loadMeta(), loadDashboard(true), loadContracts(true)]);
  if (!state.operator) setTimeout(() => $("#operator-dialog").showModal(), 250);
  setInterval(() => {
    if (document.hidden || $("#contract-dialog").open || $("#restore-dialog").open || $("#import-preview").hidden === false) return;
    loadHealth(true);
    if (state.page === "dashboard") loadDashboard(true);
    if (state.page === "contracts") loadContracts(true);
  }, 45000);
}

document.addEventListener("DOMContentLoaded", init);
