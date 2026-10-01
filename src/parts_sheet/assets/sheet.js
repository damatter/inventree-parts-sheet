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
const photos = new Map();
let sortBy = "IPN";
const fields = [
  "name",
  "description",
  "active",
  "category_id",
  "make_model",
  "material",
  "size",
  "default_location_id",
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
  "default_location_id",
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
function buildColumnControls() {
  document.querySelectorAll("th[data-column]").forEach(th => {
    const key = th.dataset.column;
    const label = th.textContent;
    const sort = el("button", label, {type:"button", className:"columnsort"});
    sort.dataset.label = label;
    sort.dataset.sort = key;
    sort.addEventListener("click", safeRun(async () => {
      if (!guard()) return;
      sortBy = sortBy === key ? `-${key}` : key;
      updateSortButtons();
      page = 1;
      await load();
    }));
    th.replaceChildren(sort);
    const controls = [];
    if (["category", "active", "photo"].includes(key)) {
      const select = el("select", undefined, {id:key});
      option(select, "", "All");
      if (key !== "category") {
        option(select, "true", key === "active" ? "Visible" : "Has photo");
        option(select, "false", key === "active" ? "Hidden" : "No photo");
      }
      if (key === "photo") select.dataset.filter = "photo";
      controls.push(select);
    } else if (key === "price") {
      for (const bound of ["min", "max"]) {
        const input = el("input", undefined, {type:"number", min:"0", step:"any", placeholder:bound === "min" ? "Min" : "Max"});
        input.dataset.filter = `price_${bound}`;
        controls.push(input);
      }
    } else {
      const input = el("input", undefined, {type:"search", placeholder:"Filter…"});
      input.dataset.filter = `filter_${key}`;
      controls.push(input);
    }
    controls.forEach(input => {
      input.setAttribute("aria-label", `Filter ${label}${input.placeholder && key === "price" ? ` ${input.placeholder}` : ""}`);
      th.append(input);
      if (key === "category" || key === "active") return;
      let timer, previous = "";
      input.addEventListener(input.tagName === "SELECT" ? "change" : "input", () => {
        clearTimeout(timer);
        if (!guard()) { input.value = previous; return; }
        previous = input.value;
        timer = setTimeout(safeRun(async () => { if (guard()) {page = 1; await load();} }), 300);
      });
    });
  });
  updateSortButtons();
}
function updateSortButtons() {
  document.querySelectorAll("[data-sort]").forEach(button => {
    const selected = sortBy.replace(/^-/, "") === button.dataset.sort;
    const descending = selected && sortBy.startsWith("-");
    button.textContent = `${button.dataset.label} ${selected ? descending ? "↓" : "↑" : "↕"}`;
    button.title = `Sort ${button.dataset.label} ${selected && !descending ? "descending" : "ascending"}`;
    button.closest("th").setAttribute("aria-sort", selected ? descending ? "descending" : "ascending" : "none");
  });
}
buildColumnControls();

let locationSelected = null;
function locationPicker(value, onChange) {
  let current = value;
  const button = el("button", undefined, {type:"button", className:"locationpicker"});
  function update() {
    const location = config.locations.find(l => l.id === Number(current));
    button.textContent = location?.pathstring || "Choose location…";
    button.title = button.textContent;
    button.disabled = !config.location_view;
  }
  update();
  button.addEventListener("click", () => {
    locationSelected = id => {current = id; update(); onChange(id);};
    $("locationsearch").value = "";
    renderLocations();
    $("locationdialog").showModal();
    $("locationsearch").focus();
  });
  return button;
}
function renderLocations() {
  const words = $("locationsearch").value.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = config.locations.filter(l => words.every(w => l.pathstring.toLowerCase().includes(w)));
  $("locationcount").textContent = `${matches.length} locations${matches.length > 100 ? " — type to narrow the list" : ""}`;
  $("locationresults").replaceChildren();
  matches.slice(0,100).forEach(location => {
    const button = el("button", location.pathstring, {type:"button"});
    button.addEventListener("click", () => {locationSelected(location.id); $("locationdialog").close();});
    $("locationresults").append(button);
  });
}
$("locationsearch").addEventListener("input", renderLocations);
$("clearlocation").addEventListener("click", () => {locationSelected(null); $("locationdialog").close();});

function clearPhoto(key) {
  const photo = photos.get(key);
  if (photo) URL.revokeObjectURL(photo.url);
  photos.delete(key);
}
function queuePhoto(row, file) {
  clearPhoto(row._key);
  photos.set(row._key, {file, partId:row.id, url:URL.createObjectURL(file)});
  if (!dirty.has(row._key)) dirty.set(row._key, {id:row.id, token:row.token, fields:{}, cells:{}});
  changed();
}
let pictureRow;
function openPicture(row) {
  pictureRow = row;
  $("picturetitle").textContent = `${row.ipn || "New part"} · ${row.name}`;
  const url = photos.get(row._key)?.url || row.image;
  $("fullpicture").hidden = !url;
  if (url) $("fullpicture").src = url;
  else $("fullpicture").removeAttribute("src");
  $("fullpicture").alt = row.name;
  $("pictureupload").value = "";
  $("pictureuploadlabel").hidden = !config.permissions.change;
  $("picture").showModal();
}
$("pictureupload").addEventListener("change", () => {
  const file = $("pictureupload").files[0];
  if (!file) return;
  queuePhoto(pictureRow, file);
  $("picture").close();
  render();
  message("Picture selected. Choose Save changes to upload it.");
});
function newPriceCurrency() {
  $("newpricecustomer").setCustomValidity("");
  const customer = config.customers.find(c => c.id === Number($("newpricecustomer").value));
  $("newpricecurrency").textContent = `${customer?.currency || "CAD"} · quantity 1`;
}
$("newpricecustomer").addEventListener("change", newPriceCurrency);
$("newprice").addEventListener("input", () => $("newpricecustomer").setCustomValidity(""));
let customerTarget, customerPayload, customerBusy = false;
function openCustomer(target) {
  if (customerBusy || (target === "sheet" && !guard())) return;
  customerTarget = target;
  customerPayload = null;
  $("customerform").reset();
  $("customername").disabled = false;
  $("customercurrency").disabled = false;
  $("savecustomer").textContent = "Create customer";
  $("customermessage").textContent = "";
  $("customerdialog").showModal();
  $("customername").focus();
}
$("addcustomer").addEventListener("click", () => openCustomer("sheet"));
$("newpartcustomer").addEventListener("click", () => openCustomer("newpart"));
$("customerform").addEventListener("submit", async event => {
  event.preventDefault();
  if (customerBusy) return;
  customerBusy = true;
  $("savecustomer").disabled = true;
  $("customername").disabled = true;
  $("customercurrency").disabled = true;
  customerPayload ||= {key:crypto.randomUUID(), name:$("customername").value.trim(), currency:$("customercurrency").value.toUpperCase()};
  try {
    const customer = await api("customer", customerPayload);
    await refreshConfig();
    if (customerTarget === "newpart") {
      $("newpricecustomer").value = customer.id;
      newPriceCurrency();
    } else {
      $("customer").value = customer.id;
      $("currency").value = customer.currency || "CAD";
      page = 1; await load();
    }
    $("customerdialog").close();
  } catch (error) {
    $("customermessage").textContent = error.message;
    if (error.status && error.status < 500) {
      customerPayload = null;
      $("customername").disabled = false;
      $("customercurrency").disabled = false;
    } else {
      $("savecustomer").textContent = "Retry creating customer";
      $("customermessage").textContent += " Retry this request to avoid duplicates.";
    }
  } finally {
    customerBusy = false;
    $("savecustomer").disabled = false;
  }
});
let deletion;
function openDelete(row) {
  if (!guard()) return;
  deletion = {key:crypto.randomUUID(), id:row.id, token:row.token};
  $("deleteprompt").textContent = `Delete ${row.ipn || "unnumbered part"} · ${row.name}?`;
  $("deletemessage").textContent = row.active ? "Uncheck Visible and save this part first." : "";
  $("confirmdelete").disabled = row.active;
  $("confirmdelete").textContent = "Delete part permanently";
  $("deletedialog").showModal();
}
$("confirmdelete").addEventListener("click", async () => {
  if (busy) return;
  busy = true; changed(); $("confirmdelete").disabled = true;
  try {
    await api("delete", deletion);
    $("deletedialog").close();
    syncPending = true;
    await refreshConfig(); await load();
    message("Part deleted. Existing part numbers are unchanged; the next number has been refreshed.");
  } catch (error) {
    $("deletemessage").textContent = error.message;
    $("confirmdelete").textContent = "Retry deletion";
  } finally {
    busy = false; changed(); $("confirmdelete").disabled = false;
  }
});
function query() {
  const params = new URLSearchParams({
    category: $("category").value,
    active: $("active").value,
    sort: sortBy,
    customer: $("customer").value,
    quantity: $("quantity").value || "1",
    page,
    page_size: $("pagesize").value,
  });
  document.querySelectorAll("[data-filter]").forEach(input => params.set(input.dataset.filter, input.value));
  return params;
}
function changed() {
  const count = new Set([...dirty.keys(), ...photos.keys()]).size;
  $("save").disabled = !count || busy;
  $("discard").disabled = !count || busy || uncertain;
  $("add").disabled = busy || uncertain || loading;
  $("sheet").inert = busy || uncertain || loading;
  document.querySelector(".toolbar").inert = busy || uncertain || loading;
  $("pricebar").inert = busy || uncertain || loading;
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
      customer: row._priceCustomer || Number($("customer").value),
      quantity: row._priceQuantity || $("quantity").value,
      price: value,
      currency: row._priceCurrency || row.price?.currency || $("currency").value,
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
  if (key === "default_location_id") {
    input = locationPicker(row.default_location_id, id => mark(row, key, id));
  } else if (key === "category_id") {
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
    `${{ name: "OEM PN", active: "Visible", ipn: "DiCor Part Number" }[key] || key.replaceAll("_", " ")} for ${row.ipn || "new part"}`,
  );
  input.disabled =
    key === "price"
      ? !config.pricing.edit || row.price?.active === false || !($("customer").value || row._priceCustomer)
      : row.id
        ? !config.permissions.change
        : !config.permissions.add;
  if (key === "default_location_id" && !config.location_view) input.disabled = true;
  if (key !== "default_location_id") input.addEventListener("input", () =>
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
  const showPrices = config.pricing.view && ($("customer").value || rows.some(r => r._priceCustomer));
  document.querySelector(".pricecol").hidden =
    !showPrices;
  rows.forEach((row) => {
    row._key ||= String(row.id);
    const tr = el("tr");
    row._node = tr;
    tr.dataset.key = row._key;
    if (dirty.has(row._key)) tr.classList.add("dirty");
    const number = el("td");
    const numberBox = el("div", undefined, { className: "numberbox" });
    const ipn = inputFor(row, "ipn");
    ipn.value = row.ipn || "";
    ipn.placeholder = row.id ? "Internal number" : "Automatic";
    ipn.title = row.id
      ? `InvenTree internal part number${row.revision ? ` · Revision ${row.revision}` : ""}`
      : `Automatic: ${config.series.find((s) => s.id === Number(row.series))?.next || ""}`;
    numberBox.append(ipn);
    if (row.id) {
      const link = el("a", "↗", {
        href: row.url,
        className: "ipn",
        title: "Open this part in InvenTree",
      });
      link.setAttribute(
        "aria-label",
        `Open ${row.ipn || row.name} in InvenTree`,
      );
      numberBox.append(link);
    }
    number.append(numberBox);
    tr.append(number);
    const photo = el("td", undefined, { className: "photo" });
    const queuedPhoto = photos.get(row._key);
    if (row.thumbnail || queuedPhoto) {
      const button = el("button", undefined, {
        className: "thumbnail",
        title: `Enlarge picture of ${row.name}`,
      });
      button.setAttribute("aria-label", `Enlarge picture of ${row.name}`);
      button.append(
        el("img", undefined, {
          src: queuedPhoto?.url || row.thumbnail,
          alt: row.name,
          loading: "lazy",
          width: 32,
          height: 32,
        }),
      );
      button.addEventListener("click", () => {
        openPicture(row);
      });
      photo.append(button);
    } else {
      const addPhoto = el("button", "+", {className:"thumbnail", title:"Add picture"});
      addPhoto.setAttribute("aria-label", `Add picture for ${row.name}`);
      addPhoto.disabled = !config.permissions.change;
      addPhoto.addEventListener("click", () => openPicture(row));
      photo.append(addPhoto);
    }
    tr.append(photo);
    fields.forEach((key) => {
      if (key === "price" && !showPrices)
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
              : `${row._priceCustomer ? (config.customers.find(c => c.id === row._priceCustomer)?.name || "") + " · " : ""}${row.price?.currency || $("currency").value}`,
            { className: "currency" },
          ),
        );
      }
      tr.append(td);
    });
    const more = el("td");
    more.className = "rowactions";
    if (row.id) {
      const prices = el("button", "Part Pricing", {
        className: "pricingbutton",
      });
      prices.addEventListener("click", () => openPricing(row));
      const button = el("button", "Details");
      button.addEventListener("click", () => details(row));
      more.append(prices, button);
      if (config.permissions.delete) {
        const remove = el("button", "Delete", {className:"deletebutton"});
        remove.addEventListener("click", () => openDelete(row));
        more.append(remove);
      }
    } else {
      const setup = el("button", row.stock ? "Stock / setup" : "Setup");
      setup.addEventListener("click", () => openNewPart(row));
      const remove = el("button", "Remove");
      remove.addEventListener("click", () => removeNew(row));
      more.append(setup, remove);
    }
    tr.append(more);
    $("rows").append(tr);
  });
  changed();
}
function removeNew(row) {
  rows = rows.filter((r) => r !== row);
  dirty.delete(row._key);
  clearPhoto(row._key);
  render();
}
function guard() {
  if (!dirty.size && !photos.size && !busy && !uncertain) return true;
  message("Save or discard your edits before changing this view.", true);
  return false;
}
async function load() {
  const version = ++loadVersion;
  loading = true;
  changed();
  message("Loading catalogue…");
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
  options(
    $("series"),
    config.series.map((s) => ({
      id: s.id,
      label: `${s.label} — next ${s.next || "full"}`,
    })),
  );
  options($("importseries"), config.series);
  options($("category"), config.categories, "All categories");
  options($("importcategory"), config.categories, "Uncategorised");
  options($("newcategory"), config.categories, "Uncategorised");
  options($("customer"), config.customers, "Choose a customer");
  options($("newpricecustomer"), config.customers, "Choose a customer");
  $("newpricing").hidden = !config.pricing.edit;
  $("addcustomer").hidden = !config.customer_add;
  $("newpartcustomer").hidden = !config.customer_add;
  if (!$("customer").value && config.customers.length === 1) {
    $("customer").value = config.customers[0].id;
    $("currency").value = config.customers[0].currency || "CAD";
  }
  options(
    $("importcustomer"),
    config.customers,
    "Keep spreadsheet prices as reference only",
  );
  $("pricecontrols").hidden = !config.pricing.view;
  $("pricingmessage").textContent =
    config.pricing.message +
    (config.pricing.view && !config.customers.length
      ? " Add a customer in InvenTree first."
      : "");
  $("importpricelabel").hidden = !config.pricing.edit;
  $("add").hidden = !config.permissions.add;
  $("import").hidden = !(config.permissions.add && config.permissions.change);
  $("numbering").hidden = !config.admin;
  $("sync").disabled = !config.website_sync || !config.permissions.change;
  $("sync").title = config.website_sync
    ? "Publish the saved catalogue"
    : "Website sync is not configured on this server";
  $("newstock").disabled = !config.stock_add;
  $("newphoto").disabled = !config.permissions.change;
  $("stockhint").textContent = config.stock_add
    ? "The stock item’s barcode will be the OEM part number."
    : "Stock add and location view permissions are required to add opening stock.";
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
    description: "",
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
let editingNew = null;
let newLocation = null;
function openNewPart(row = null) {
  if (busy || uncertain || loading) return;
  editingNew = row;
  $("newtitle").textContent = row ? "Part and opening stock" : "Add a part";
  $("newoem").value = row?.name || "";
  $("newdescription").value = row?.description || "";
  $("newcategory").value = row?.category_id || $("category").value || "";
  $("newvisible").checked = row?.active || false;
  $("newstock").checked = !!row?.stock;
  $("newquantity").value = row?.stock?.quantity || "";
  newLocation = row?.default_location_id || row?.stock?.location || null;
  $("newlocationpicker").replaceChildren(locationPicker(newLocation, id => { newLocation = id; }));
  $("newphoto").value = "";
  $("newphotoname").textContent = photos.get(row?._key)?.file.name || "";
  const draftPrice = dirty.get(row?._key)?.price;
  $("newpricecustomer").value = draftPrice?.customer || $("customer").value || "";
  $("newprice").value = draftPrice?.price ?? "";
  newPriceCurrency();
  $("newipn").value = row?.ipn || "";
  if (row) $("series").value = row.series;
  nextNumber();
  stockFields();
  $("newpart").showModal();
  $("newoem").focus();
}
function stockFields() {
  const enabled = $("newstock").checked && config.stock_add;
  $("stockfields").hidden = !enabled;
  $("newquantity").required = enabled;
}
$("newstock").addEventListener("change", stockFields);
$("newpartform").addEventListener("submit", (event) => {
  event.preventDefault();
  if ($("newprice").value !== "" && !$("newpricecustomer").value) {
    $("newpricecustomer").setCustomValidity("Choose a customer for this price.");
    $("newpricecustomer").reportValidity();
    return;
  }
  if ($("newstock").checked && !newLocation) {
    $("newlocationpicker").querySelector("button").click();
    return;
  }
  const row = editingNew || addRow(false);
  if (!row) return;
  row.series = Number($("series").value);
  for (const [field, value] of Object.entries({
    name: $("newoem").value.trim(),
    description: $("newdescription").value,
    category_id: Number($("newcategory").value) || null,
    active: $("newvisible").checked,
    ipn: $("newipn").value.trim(),
    ...(config.location_view ? {default_location_id: newLocation} : {}),
  }))
    mark(row, field, value);
  const patch = dirty.get(row._key);
  if (config.pricing.edit && $("newprice").value !== "") {
    row._priceCustomer = Number($("newpricecustomer").value);
    row._priceQuantity = "1";
    row._priceCurrency = config.customers.find(c => c.id === row._priceCustomer)?.currency || "CAD";
    row.price = {price:$("newprice").value, currency:row._priceCurrency};
    mark(row, "price", $("newprice").value);
  } else {
    delete patch.price;
    delete row._priceCustomer;
    delete row._priceQuantity;
    delete row._priceCurrency;
    delete row.price;
  }
  if ($("newstock").checked && config.stock_add) {
    row.stock = patch.stock = {
      quantity: $("newquantity").value,
      location: newLocation,
    };
  } else {
    delete row.stock;
    delete patch.stock;
  }
  if ($("newphoto").files[0]) queuePhoto(row, $("newphoto").files[0]);
  $("newpart").close();
  render();
  row._node.scrollIntoView({ block: "nearest" });
  message(
    "Row added. Choose Save changes to create the part" +
      (row.stock ? " and opening stock." : "."),
  );
});
async function save() {
  if ((!dirty.size && !photos.size) || busy) return;
  busy = true;
  if ($("details").open) $("details").close();
  if ($("newpart").open) $("newpart").close();
  if ($("picture").open) $("picture").close();
  changed();
  document
    .querySelectorAll("#rows input,#rows select")
    .forEach((i) => (i.disabled = true));
  try {
    if (dirty.size) {
      pendingKey ||= crypto.randomUUID();
      pendingPayload ||= { key: pendingKey, rows: [...dirty.values()] };
      const keys = [...dirty.keys()];
      const result = await api("save", pendingPayload);
      result.rows.forEach((saved, index) => {
        const photo = photos.get(keys[index]);
        if (photo) photo.partId = saved.id;
        const row = rows.find(r => r._key === keys[index]);
        if (row) {
          const previousPrice = row.price;
          Object.assign(row, saved);
          row.price = saved.price || previousPrice;
        }
      });
      uncertain = false;
      dirty.clear();
      pendingKey = null;
      pendingPayload = null;
    }
    syncPending = true;
    for (const [key, photo] of photos) {
      message(`Uploading ${photo.file.name}… Keep this page open; slow connections may take several minutes.`);
      const data = new FormData();
      data.set("image", photo.file, photo.file.name);
      await request(`/api/part/${photo.partId}/`, data, "PATCH");
      clearPhoto(key);
    }
    await refreshConfig();
    await load();
    message(
      "Changes saved. Parts, prices and any opening stock are now in InvenTree.",
    );
  } catch (error) {
    uncertain = dirty.size > 0 && (!error.status || error.status >= 500);
    message(
      uncertain
        ? "Save outcome unknown. Click Retry save before editing again; the same request will not create duplicate parts."
        : photos.size && !dirty.size
          ? `Parts are saved. Picture upload failed: ${error.message}. Choose Save changes to retry the picture; no extra part will be created.`
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
    const result = await request(`${BASE}api/sync/`, data);
    syncPending = false;
    message(result.message || "Website sync queued.");
  } catch (e) {
    message(`Parts are saved. Website sync: ${e.message}`, true);
  }
}
function onLeave() {
  if (!syncPending || !config?.website_sync || !config.permissions.change)
    return;
  const data = new FormData();
  data.set("csrfmiddlewaretoken", csrf());
  data.set("reason", "page-leave");
  if (navigator.sendBeacon(`${BASE}api/sync/`, data)) syncPending = false;
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
  if (row.cells.oem_number && row.cells.oem_number !== row.name) {
    body.append(el("p", `Imported OEM reference: ${row.cells.oem_number}`));
    if (config.permissions.change) {
      const use = el("button", "Use imported OEM PN");
      use.addEventListener("click", () => {
        if (!row.description) mark(row, "description", row.name);
        mark(row, "name", row.cells.oem_number);
        $("details").close();
        render();
        message(
          "OEM PN updated in the sheet. Save changes to update the InvenTree name.",
        );
      });
      body.append(use);
    }
  }
  $("details").showModal();
}
async function editPriceInSheet(row, customer, quantity) {
  if (!guard()) {
    $("pricingdialog").close();
    return;
  }
  $("customer").value = customer;
  $("quantity").value = quantity;
  const company = config.customers.find((c) => c.id === Number(customer));
  if (company?.currency) $("currency").value = company.currency;
  $("pricingdialog").close();
  await load();
  rows
    .find((r) => r.id === row.id)
    ?._node.querySelector('[data-field="price"]')
    ?.focus();
  message("Enter the customer price in this row, then choose Save changes.");
}
async function openPricing(row) {
  $("pricingtitle").textContent = `Part Pricing · ${row.ipn || row.name}`;
  const body = $("pricingbody");
  body.replaceChildren(el("p", config.pricing.message));
  body.append(
    el("a", "Open full Part Pricing on the InvenTree part", { href: row.url }),
  );
  $("pricingdialog").showModal();
  if (config.pricing.view && config.customers.length) {
    const form = el("form", undefined, { className: "pricepicker" });
    const customerLabel = el("label", "Customer");
    const customer = el("select", undefined, { required: true });
    options(customer, config.customers, "Choose a customer");
    customer.value = $("customer").value;
    const qtyLabel = el("label", "Quantity break");
    const qty = el("input", undefined, {
      type: "number",
      min: "1",
      step: "any",
      value: $("quantity").value,
      required: true,
    });
    customerLabel.append(customer);
    qtyLabel.append(qty);
    form.append(
      customerLabel,
      qtyLabel,
      el("button", config.pricing.edit ? "Edit in sheet" : "View in sheet", {
        type: "submit",
        className: "primary",
      }),
    );
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      safeRun(() => editPriceInSheet(row, customer.value, qty.value))();
    });
    body.append(form);
  }
  if (config.pricing.view || config.pricing.costs) {
    const area = el("div");
    body.append(area);
    area.append(el("h3", "Part Pricing"), el("p", "Loading current prices…"));
    try {
      const data = await request(`/plugin/customer-pricing/part/${row.id}/`);
      area.replaceChildren(el("h3", "Part Pricing"));
      if (config.pricing.view && !data.customer_lists?.length)
        area.append(
          el(
            "p",
            "No customer prices yet. Choose a customer above to add the first price.",
          ),
        );
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
          if (
            config.pricing.view &&
            list.active &&
            config.customers.some((c) => c.id === Number(list.customer))
          ) {
            const cell = el("td");
            const edit = el(
              "button",
              config.pricing.edit ? "Edit in sheet" : "View in sheet",
            );
            edit.addEventListener(
              "click",
              safeRun(() => editPriceInSheet(row, list.customer, t.quantity)),
            );
            cell.append(edit);
            tr.append(cell);
          }
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
          "Other customers and quantity breaks stay unchanged. Materials, margins and all pricing options are available in this part’s Part Pricing tab in InvenTree.",
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
        $("seriesform").elements[k].value = k === "last" ? s.reserved_through : s[k];
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
  openNewPart();
});
$("save").addEventListener("click", save);
$("discard").addEventListener(
  "click",
  safeRun(async () => {
    dirty.clear();
    [...photos.keys()].forEach(clearPhoto);
    pendingKey = null;
    pendingPayload = null;
    await load();
  }),
);
$("reload").addEventListener(
  "click",
  safeRun(async () => {if (guard()) {await refreshConfig(); await load();}}),
);
$("clearfilters").addEventListener("click", safeRun(async () => {
  if (!guard()) return;
  document.querySelectorAll("[data-filter],#category,#active").forEach(input => {input.value = "";});
  page = 1; await load();
}));
for (const id of [
  "category",
  "active",
  "customer",
  "quantity",
  "pagesize",
]) {
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
        if (!$(id).value) {
          document.querySelectorAll('[data-filter^="price_"]').forEach(input => {input.value = "";});
          if (sortBy.replace(/^-/, "") === "price") {sortBy = "IPN"; updateSortButtons();}
        }
      }
      page = 1;
      await load();
      if (id === "pagesize") {
        try {
          localStorage.setItem("parts-sheet-page-size", $(id).value);
        } catch {}
      }
      previous = $(id).value;
    }),
  );
}
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
  if (event.key === "Enter" && event.target.matches("#sheet input[data-field]")) {
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
  if (blocks.length > 200) {
    message("Paste at most 200 rows at once.", true);
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
      if (!input || input.disabled || !["INPUT", "SELECT"].includes(input.tagName)) return;
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
  if (dirty.size || photos.size || busy) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("pagehide", onLeave);
try {
  try {
    const size = localStorage.getItem("parts-sheet-page-size");
    if (["25", "50", "100", "200"].includes(size)) $("pagesize").value = size;
  } catch {}
  await refreshConfig();
  const links = {
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
