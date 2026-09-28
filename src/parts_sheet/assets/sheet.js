const $ = (id) => document.getElementById(id);
const BASE = "/plugin/parts-sheet/";
let config,
  rows = [],
  page = 1,
  pages = 1,
  busy = false,
  preview = null,
  pendingKey = null;
let pendingPayload = null,
  syncPending = false;
let uncertain = false,
  loading = false,
  loadVersion = 0;
const dirty = new Map();
const fields = [
  "name",
  "active",
  "category_id",
  "oem_number",
  "make_model",
  "material",
  "size",
  "price",
];
const native = new Set([
  "name",
  "active",
  "category_id",
  "description",
  "assembly",
  "component",
  "purchaseable",
  "salable",
]);
const csrf = () => document.querySelector("[name=csrfmiddlewaretoken]").value;
function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  Object.assign(node, attrs);
  return node;
}
function message(text, error = false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", error);
}
async function request(url, data, method = "POST") {
  const options = {
    method: data === undefined ? "GET" : method,
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  };
  if (data !== undefined) {
    options.headers["X-CSRFToken"] = csrf();
    if (data instanceof FormData) options.body = data;
    else {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(data);
    }
  }
  const response = await fetch(url, options);
  let body;
  try {
    body = await response.json();
  } catch {
    const error = new Error(
      "The server returned an unexpected response. Check your login and retry.",
    );
    error.status = response.redirected ? 401 : 500;
    throw error;
  }
  if (!response.ok) {
    const error = new Error(body.error || body.detail || JSON.stringify(body));
    error.status = response.status;
    throw error;
  }
  return body;
}
const api = (action, data) => request(`${BASE}api/${action}/`, data);
function option(select, value, label) {
  select.append(el("option", label, { value: String(value) }));
}
function options(select, values, empty) {
  const old = select.value;
  select.replaceChildren();
  if (empty !== undefined) option(select, "", empty);
  values.forEach((v) => option(select, v.id, v.name || v.label));
  if ([...select.options].some((o) => o.value === old)) select.value = old;
}
function query() {
  return new URLSearchParams({
    q: $("search").value,
    category: $("category").value,
    active: $("active").value,
    sort: $("sort").value,
    customer: $("customer").value,
    quantity: $("quantity").value || "1",
    page,
  });
}
function changed() {
  const count = dirty.size;
  $("save").disabled = !count || busy;
  $("discard").disabled = !count || busy || uncertain;
  $("add").disabled = busy || uncertain || loading;
  $("sheet").inert = busy || uncertain || loading;
  $("save").textContent = busy
    ? "Saving…"
    : uncertain
      ? "Retry save"
      : count
        ? `Save ${count} changed row${count === 1 ? "" : "s"}`
        : "Save changes";
}
function mark(row, key, value) {
  if (busy) return;
  let patch = dirty.get(row._key) || {
    id: row.id,
    token: row.token,
    fields: {},
    cells: {},
  };
  if (key === "price") {
    patch.price = {
      customer: Number($("customer").value),
      quantity: $("quantity").value,
      price: value,
      currency: row.price?.currency || $("currency").value,
      token: row.price?.token,
    };
    row.price = { ...row.price, price: value };
  } else if (key === "ipn") {
    patch.ipn = value;
    row.ipn = value;
  } else if (native.has(key)) {
    patch.fields[key] = value;
    row[key] = value;
  } else {
    patch.cells[key] = value;
    row.cells[key] = value;
  }
  if (!row.id) patch.series = Number(row.series);
  dirty.set(row._key, patch);
  row._node?.classList.add("dirty");
  pendingKey = null;
  pendingPayload = null;
  changed();
}
function inputFor(row, key) {
  let input;
  if (key === "category_id") {
    input = el("select");
    options(input, config.categories, "Uncategorised");
    input.value = row.category_id || "";
  } else if (key === "active")
    input = el("input", undefined, { type: "checkbox", checked: row.active });
  else
    input = el("input", undefined, {
      type: "text",
      value:
        key === "price"
          ? row.price?.price || ""
          : native.has(key)
            ? row[key] || ""
            : row.cells[key] || "",
    });
  input.dataset.field = key;
  input.setAttribute(
    "aria-label",
    `${key.replaceAll("_", " ")} for ${row.ipn || "new part"}`,
  );
  input.disabled =
    key === "price"
      ? !config.pricing.edit || row.price?.active === false
      : row.id
        ? !config.permissions.change
        : !config.permissions.add;
  input.addEventListener("input", () =>
    mark(
      row,
      key,
      key === "active"
        ? input.checked
        : key === "category_id"
          ? Number(input.value) || null
          : input.value,
    ),
  );
  return input;
}
function render() {
  $("rows").replaceChildren();
  document.querySelector(".pricecol").hidden =
    !$("customer").value || !config.pricing.view;
  rows.forEach((row) => {
    row._key ||= String(row.id);
    const tr = el("tr");
    row._node = tr;
    tr.dataset.key = row._key;
    if (dirty.has(row._key)) tr.classList.add("dirty");
    const number = el("td");
    if (row.id) {
      number.append(
        el("a", row.ipn || "(no number)", { href: row.url, className: "ipn" }),
      );
      if (row.revision)
        number.append(el("span", `Rev ${row.revision}`, { className: "rev" }));
    } else {
      const ipn = el("input", undefined, {
        value: row.ipn || "",
        placeholder: "Automatic",
        type: "text",
      });
      ipn.dataset.field = "ipn";
      ipn.setAttribute("aria-label", "New part number (blank for automatic)");
      ipn.addEventListener("input", () => mark(row, "ipn", ipn.value));
      number.append(
        ipn,
        el(
          "span",
          config.series.find((s) => s.id === Number(row.series))?.label || "",
          { className: "rev" },
        ),
      );
    }
    tr.append(number);
    fields.forEach((key) => {
      if (key === "price" && (!$("customer").value || !config.pricing.view))
        return;
      const td = el("td");
      td.append(inputFor(row, key));
      if (key === "price") {
        td.className = "pricecell";
        td.append(
          el(
            "span",
            row.price?.active === false
              ? "Inactive price list"
              : row.price?.currency || $("currency").value,
            { className: "currency" },
          ),
        );
      }
      tr.append(td);
    });
    const more = el("td");
    const button = el("button", row.id ? "Details" : "Remove");
    button.addEventListener("click", () =>
      row.id ? details(row) : removeNew(row),
    );
    more.append(button);
    tr.append(more);
    $("rows").append(tr);
  });
  changed();
}
function removeNew(row) {
  rows = rows.filter((r) => r !== row);
  dirty.delete(row._key);
  render();
}
function guard() {
  if (!dirty.size) return true;
  message("Save or discard your edits before changing this view.", true);
  return false;
}
async function load() {
  const version = ++loadVersion;
  loading = true;
  changed();
  try {
    const result = await request(`${BASE}api/rows/?${query()}`);
    if (version !== loadVersion) return;
    rows = result.rows;
    page = result.page;
    pages = result.pages;
    render();
    $("count").textContent =
      `${result.total.toLocaleString()} part${result.total === 1 ? "" : "s"}`;
    $("page").textContent = `Page ${page} of ${pages}`;
    $("prev").disabled = page <= 1;
    $("nextpage").disabled = page >= pages;
    message("Ready. Edits are saved when you choose Save changes.");
  } finally {
    if (version === loadVersion) {
      loading = false;
      changed();
    }
  }
}
async function refreshConfig() {
  config = await api("bootstrap");
  options($("series"), config.series);
  options($("importseries"), config.series);
  options($("category"), config.categories, "All categories");
  options($("importcategory"), config.categories, "Uncategorised");
  options($("customer"), config.customers, "Choose a customer");
  options(
    $("importcustomer"),
    config.customers,
    "Keep spreadsheet prices as reference only",
  );
  $("pricebar").hidden = !config.pricing.view;
  $("importpricelabel").hidden = !config.pricing.edit;
  $("add").hidden = !config.permissions.add;
  $("import").hidden = !(config.permissions.add && config.permissions.change);
  $("numbering").hidden = !config.admin;
  $("sync").hidden =
    !config.integrations["part-visibility"] || !config.permissions.change;
  nextNumber();
}
function nextNumber() {
  const s = config.series.find((s) => s.id === Number($("series").value));
  $("next").textContent = s ? `Next: ${s.next || "Series full"}` : "";
}
function addRow(focus = true) {
  const series = $("series").value;
  if (!series) {
    message("Configure a number series first.", true);
    return;
  }
  const row = {
    _key: `new-${crypto.randomUUID()}`,
    name: "",
    ipn: "",
    cells: {},
    active: false,
    category_id: Number($("category").value) || null,
    series,
  };
  rows.push(row);
  dirty.set(row._key, {
    fields: { name: "", active: false, category_id: row.category_id },
    cells: {},
    series: Number(series),
  });
  render();
  if (focus) row._node.querySelector("[data-field=name]").focus();
  return row;
}
async function save() {
  if (!dirty.size || busy) return;
  busy = true;
  if ($("details").open) $("details").close();
  changed();
  document
    .querySelectorAll("#sheet input,#sheet select")
    .forEach((i) => (i.disabled = true));
  try {
    pendingKey ||= crypto.randomUUID();
    pendingPayload ||= { key: pendingKey, rows: [...dirty.values()] };
    await api("save", pendingPayload);
    uncertain = false;
    dirty.clear();
    pendingKey = null;
    pendingPayload = null;
    syncPending = true;
    await refreshConfig();
    await load();
    message("Changes saved. New rows are now InvenTree parts.");
  } catch (error) {
    uncertain = dirty.size > 0 && (!error.status || error.status >= 500);
    message(
      uncertain
        ? "Save outcome unknown. Click Retry save before editing again; the same request will not create duplicate parts."
        : error.message,
      true,
    );
  } finally {
    busy = false;
    render();
  }
}
async function sync() {
  try {
    const data = new FormData();
    data.set("csrfmiddlewaretoken", csrf());
    const result = await request("/plugin/part-visibility/sync/", data);
    syncPending = false;
    message(result.message || "Website sync queued.");
  } catch (e) {
    message(`Parts are saved. Website sync: ${e.message}`, true);
  }
}
function onLeave() {
  if (!syncPending || !config?.integrations["part-visibility"]) return;
  const data = new FormData();
  data.set("csrfmiddlewaretoken", csrf());
  data.set("reason", "page-leave");
  if (navigator.sendBeacon("/plugin/part-visibility/sync/", data))
    syncPending = false;
}
async function details(row) {
  $("detailtitle").textContent = `${row.ipn || "Part"} · ${row.name}`;
  const body = $("detailbody");
  body.replaceChildren();
  const container = el("div", undefined, { className: "fields" });
  const labels = {
    description: "Description",
    required: "Quantity required (reference)",
    drawing: "Drawing note",
    date_priced: "Date priced (reference)",
    notes: "Notes",
    assembly: "Assembly / manufactured",
    component: "Component",
    purchaseable: "Purchasable",
    salable: "Salable",
  };
  for (const [key, label] of Object.entries(labels)) {
    const wrapper = el("label", label);
    let input;
    if (["assembly", "component", "purchaseable", "salable"].includes(key)) {
      input = el("input", undefined, { type: "checkbox", checked: row[key] });
      input.addEventListener("input", () => mark(row, key, input.checked));
    } else {
      input = el("textarea", undefined, {
        value: native.has(key) ? row[key] || "" : row.cells[key] || "",
      });
      input.addEventListener("input", () => mark(row, key, input.value));
    }
    input.disabled = !config.permissions.change;
    wrapper.append(input);
    container.append(wrapper);
  }
  body.append(
    container,
    el("p", "Changes here are included in Save changes on the sheet."),
  );
  const refs = ["oem_usd", "supplier_cad", "sell_cad"].filter(
    (k) => row.cells[k],
  );
  if (refs.length) {
    body.append(el("h3", "Spreadsheet price references"));
    refs.forEach((k) =>
      body.append(
        el(
          "p",
          `${{ oem_usd: "OEM (USD)", supplier_cad: "Local supplier (CAD column)", sell_cad: "DC Sell (CAD)" }[k]}: ${row.cells[k]}`,
        ),
      ),
    );
  }
  body.append(el("a", "Open this part in InvenTree", { href: row.url }));
  $("details").showModal();
  if (config.pricing.view || config.pricing.costs) {
    const area = el("div");
    body.append(area);
    area.append(el("h3", "Part Pricing"), el("p", "Loading current prices…"));
    try {
      const data = await request(`/plugin/customer-pricing/part/${row.id}/`);
      area.replaceChildren(el("h3", "Part Pricing"));
      (data.customer_lists || []).forEach((list) => {
        area.append(
          el(
            "h4",
            `${list.customer_name} · ${list.currency}${list.active ? "" : " · inactive"}`,
          ),
        );
        const table = el("table");
        (list.breaks || []).forEach((t) => {
          const tr = el("tr");
          tr.append(
            el("td", `Qty ${t.quantity}+`),
            el("td", `${t.price} ${list.currency}`),
          );
          table.append(tr);
        });
        area.append(table);
      });
      if (data.material_costs?.length) {
        area.append(el("h4", "Material costs"));
        data.material_costs.forEach((m) =>
          area.append(
            el("p", `${m.name}: ${m.quantity} × ${m.unit_cost} ${m.currency}`),
          ),
        );
      }
      area.append(
        el(
          "p",
          "Choose a customer and quantity break above the sheet to edit prices. For materials, margins and all pricing options, open this part’s Part Pricing tab in InvenTree.",
        ),
      );
    } catch (e) {
      area.replaceChildren(el("p", e.message));
    }
  }
}
async function previewImport() {
  const file = $("file").files[0];
  if (!file) {
    $("importmessage").textContent = "Choose a workbook first.";
    return;
  }
  const data = new FormData();
  data.append("file", file);
  $("preview").disabled = true;
  try {
    preview = await api("preview", data);
    const counts = {};
    preview.rows.forEach(
      (r) => (counts[r.status] = (counts[r.status] || 0) + 1),
    );
    $("importmessage").textContent =
      `${preview.rows.length} rows: ${counts.matched || 0} matched, ${counts.new || 0} new, ${counts.unnumbered || 0} without numbers, ${counts.conflict || 0} conflicts. ${preview.warnings.join(" ")}`;
    const table = el("table");
    preview.rows.forEach((row) => {
      const tr = el("tr");
      const cell = el("td");
      if (row.part_id)
        cell.append(
          el("a", row.ipn, {
            href: `/web/part/${row.part_id}/`,
            target: "_blank",
            rel: "noopener",
          }),
        );
      else cell.textContent = row.ipn || "No number";
      tr.append(
        cell,
        el("td", row.name),
        el("td", row.status),
        el(
          "td",
          row.existing_name ? `Existing: ${row.existing_name}` : row.source,
        ),
      );
      table.append(tr);
    });
    $("previewrows").replaceChildren(table);
    $("importoptions").hidden = false;
    $("confirmimport").disabled = !!counts.conflict;
  } catch (e) {
    preview = null;
    $("importmessage").textContent = e.message;
    $("importoptions").hidden = true;
  } finally {
    $("preview").disabled = false;
  }
}
let importKey = null;
async function confirmImport() {
  if (!preview) return;
  $("confirmimport").disabled = true;
  try {
    importKey ||= crypto.randomUUID();
    const result = await api("import", {
      key: importKey,
      preview: preview.preview,
      category: Number($("importcategory").value) || null,
      active: $("importactive").checked,
      include_unnumbered: $("unnumbered").checked,
      series: Number($("importseries").value),
      customer: Number($("importcustomer").value) || null,
    });
    $("importmessage").textContent =
      `Done: ${result.created} created, ${result.matched} matched, ${result.skipped} skipped. ${result.prices_added} customer prices added; ${result.prices_kept} existing prices kept.`;
    preview = null;
    importKey = null;
    $("importoptions").hidden = true;
    syncPending = true;
    await refreshConfig();
    await load();
  } catch (e) {
    $("importmessage").textContent = e.message;
    importKey = null;
  } finally {
    $("confirmimport").disabled = false;
  }
}
function numbering() {
  const list = $("serieslist");
  list.replaceChildren();
  config.series.forEach((s) => {
    const b = el(
      "button",
      `${s.label} · last ${s.last} · next ${s.next || "full"}`,
    );
    b.addEventListener("click", () => {
      for (const k of ["prefix", "label", "digits", "last"])
        $("seriesform").elements[k].value = s[k];
    });
    list.append(b);
  });
  $("numberdialog").showModal();
}
function safeRun(fn) {
  return () =>
    Promise.resolve()
      .then(fn)
      .catch((e) => message(e.message, true));
}
$("add").addEventListener("click", () => {
  if (!busy) addRow();
});
$("save").addEventListener("click", save);
$("discard").addEventListener(
  "click",
  safeRun(async () => {
    dirty.clear();
    pendingKey = null;
    pendingPayload = null;
    await load();
  }),
);
$("reload").addEventListener(
  "click",
  safeRun(() => guard() && load()),
);
for (const id of ["category", "active", "sort", "customer", "quantity"]) {
  let previous;
  $(id).addEventListener("focus", () => (previous = $(id).value));
  $(id).addEventListener(
    "change",
    safeRun(async () => {
      if (!guard()) {
        $(id).value = previous;
        return;
      }
      if (id === "customer") {
        const c = config.customers.find((c) => c.id === Number($(id).value));
        if (c?.currency) $("currency").value = c.currency;
      }
      page = 1;
      await load();
      previous = $(id).value;
    }),
  );
}
let searchTimer;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(
    safeRun(() => {
      if (guard()) {
        page = 1;
        return load();
      }
    }),
    300,
  );
});
$("series").addEventListener("change", nextNumber);
$("prev").addEventListener(
  "click",
  safeRun(() => {
    if (guard()) {
      page--;
      return load();
    }
  }),
);
$("nextpage").addEventListener(
  "click",
  safeRun(() => {
    if (guard()) {
      page++;
      return load();
    }
  }),
);
$("import").addEventListener("click", () => {
  if (guard()) $("importdialog").showModal();
});
$("preview").addEventListener("click", () => {
  importKey = null;
  previewImport();
});
$("file").addEventListener("change", () => {
  preview = null;
  importKey = null;
  $("importoptions").hidden = true;
  $("previewrows").replaceChildren();
});
$("confirmimport").addEventListener("click", confirmImport);
$("export").addEventListener("click", () => {
  if (guard()) window.location.assign(`${BASE}api/export/?${query()}`);
});
$("sync").addEventListener("click", sync);
$("numbering").addEventListener("click", numbering);
$("seriesform").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("series", Object.fromEntries(new FormData(event.target)));
    await refreshConfig();
    $("seriesmessage").textContent = "Numbering saved.";
    $("numberdialog").close();
  } catch (e) {
    $("seriesmessage").textContent = e.message;
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save();
  }
  if (event.key === "Enter" && event.target.matches("#sheet input")) {
    event.preventDefault();
    const row = rows.find(
      (r) => r._key === event.target.closest("tr").dataset.key,
    );
    const next = rows[rows.indexOf(row) + (event.shiftKey ? -1 : 1)];
    next?._node
      .querySelector(`[data-field="${event.target.dataset.field}"]`)
      ?.focus();
  }
});
$("sheet").addEventListener("paste", (event) => {
  if (busy || !event.target.dataset.field) return;
  const text = event.clipboardData.getData("text/plain");
  if (!/[\t\n]/.test(text)) return;
  event.preventDefault();
  const blocks = text
    .replace(/\r/g, "")
    .replace(/\n$/, "")
    .split("\n")
    .map((r) => r.split("\t"));
  if (blocks.length > 100) {
    message("Paste at most 100 rows at once.", true);
    return;
  }
  const startRow = rows.findIndex(
    (r) => r._key === event.target.closest("tr").dataset.key,
  );
  const columns = [
    "ipn",
    ...fields.filter((f) => f !== "price" || $("customer").value),
  ];
  const startCol = columns.indexOf(event.target.dataset.field);
  blocks.forEach((values, index) => {
    const row =
      rows[startRow + index] || (config.permissions.add ? addRow(false) : null);
    if (!row) return;
    values.forEach((value, col) => {
      const key = columns[startCol + col];
      if (!key) return;
      const input = row._node.querySelector(`[data-field="${key}"]`);
      if (!input || input.disabled) return;
      if (input.type === "checkbox") {
        const v = value.trim().toLowerCase();
        if (!["true", "false", "1", "0", "yes", "no"].includes(v)) return;
        input.checked = ["true", "1", "yes"].includes(v);
      } else {
        input.value = value;
      }
      input.dispatchEvent(new Event("input"));
    });
  });
  render();
});
window.addEventListener("beforeunload", (event) => {
  if (dirty.size) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("pagehide", onLeave);
try {
  await refreshConfig();
  const links = {
    "part-visibility": ["Website Parts", "/plugin/part-visibility/"],
    "inventory-manager": ["Reporting", "/plugin/inventory-manager/"],
  };
  Object.entries(links).forEach(([slug, [name, url]]) => {
    if (config.integrations[slug])
      $("integrations").append(el("a", name, { href: url }));
  });
  await load();
} catch (e) {
  message(e.message, true);
}
