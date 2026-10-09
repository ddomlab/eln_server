// Add-a-bottle page. Runs in the browser and talks to our server with fetch():
//   GET /bottle_form     -> bottle categories, the compounds each needs, the bottle's own fields
//   GET /compounds_list  -> existing compounds (with their hazards) for the dropdown
//   GET /storage_tree    -> rooms and the places inside them
//   POST /storage_units  -> add a new place (the server refuses near-duplicate names)
//   POST /resources      -> create the bottle(s)
//   GET /compounds/pubchem, POST /compounds -> find a missing compound in PubChem and add it
//   POST /print          -> the new bottles' labels as a PDF
// The user's API key travels by itself in the apiKey cookie.

// what the page knows, filled once when it opens
let formInfo = { categories: [], units: [], units_by_state: {} };
let compounds = []; // [{id, name, cas, formula, hazards, peroxide_class}]
let storage = []; // [{id, name, parent_id, full_path}]; rooms have parent_id null
let picked = []; // the compound picked in each slot (null until picked)
let titleTouched = false; // stop filling the name in once the user types their own

const OTHER = "__other__"; // select value meaning "typed in the Other box"
const ADD_PLACE = "__add_place__"; // place value meaning "+ Add a new place…"
// dropdowns that only take their own options: the reminders can only count days, weeks or months
const NO_OTHER = new Set(["Maintenance unit"]);

// ---------- talking to the server ----------

// GET a route and return its JSON; a 401 shows the "not logged in" banner
async function getJSON(url) {
  const response = await fetch(url);
  if (response.status === 401) {
    document.getElementById("login-banner").hidden = false;
    throw new Error("not logged in");
  }
  if (!response.ok) throw new Error(`${url} failed: ${response.status}`);
  return response.json();
}

// POST JSON to a route; returns {status, data} so the caller can react to 201/409/...
async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    document.getElementById("login-banner").hidden = false;
    throw new Error("not logged in");
  }
  return { status: response.status, data: await response.json() };
}

// ---------- category ----------

function currentCategory() {
  const id = parseInt(document.getElementById("category").value, 10);
  return formInfo.categories.find((c) => c.id === id);
}

// an instrument category (kind from /bottle_form): no compounds, storage place or amount
function isInstrument() {
  return currentCategory()?.kind === "instrument";
}

function fillCategories() {
  const select = document.getElementById("category");
  select.innerHTML = "";
  // bottles first, so the page opens on a bottle category (the usual case)
  const bottlesFirst = [...formInfo.categories].sort((a, b) => (a.kind === "instrument") - (b.kind === "instrument"));
  for (const c of bottlesFirst) {
    select.add(new Option(c.title, c.id));
  }
}

// redraw everything that depends on the category
function onCategoryChange() {
  showSectionsForKind();
  drawCompoundPickers();
  drawBottleFields();
  updateTitle();
  updatePreview();
}

// an instrument only needs a name and its template's fields: hide the bottle sections
// (the compounds section hides itself, as an instrument has no compound slots)
function showSectionsForKind() {
  const instrument = isInstrument();
  document.getElementById("where-section").hidden = instrument;
  document.getElementById("amount-section").hidden = instrument;
  document.getElementById("title-hint").hidden = instrument;
  document.getElementById("procedure-field").hidden = !instrument;
  document.getElementById("page-title").textContent = instrument ? "Add an instrument" : "Add a bottle";
  document.getElementById("item-legend").textContent = instrument ? "This instrument" : "This bottle";
}

// ---------- 1. compounds ----------

function compoundLabel(c) {
  // what the dropdown shows; typing part of the name or the CAS filters it
  return `${c.name || "(no name)"} · ${c.cas || "no CAS"} · #${c.id}`;
}

function fillCompoundOptions() {
  const list = document.getElementById("compound-options");
  list.innerHTML = "";
  for (const c of compounds) list.append(new Option(compoundLabel(c)));
}

function drawCompoundPickers() {
  const slots = currentCategory()?.compound_slots || [];
  const box = document.getElementById("compound-pickers");
  box.innerHTML = "";
  picked = slots.map(() => null);
  document.getElementById("what-section").hidden = slots.length === 0;

  slots.forEach((slotName, i) => {
    const field = document.createElement("div");
    field.className = "field";
    field.innerHTML = `
      <label class="required" for="compound-${i}">${slotName}</label>
      <input id="compound-${i}" list="compound-options" autocomplete="off"
             placeholder="Type a name or CAS number" />
      <button type="button" class="link" id="pubchem-toggle-${i}">Not in the list? Search PubChem</button>
      <div class="subform" id="pubchem-${i}" hidden>
        <div class="with-unit">
          <input id="pubchem-query-${i}" type="text" autocomplete="off" placeholder="CAS number (best) or name" />
          <button type="button" id="pubchem-search-${i}">Search</button>
        </div>
        <div id="pubchem-results-${i}"></div>
      </div>
      <div class="compound-card" id="compound-card-${i}" hidden></div>`;
    box.append(field);
    field.querySelector(`#compound-${i}`).addEventListener("input", (e) => onCompoundPicked(i, e.target.value));
    field.querySelector(`#pubchem-toggle-${i}`).addEventListener("click", () => togglePubChem(i));
    field.querySelector(`#pubchem-search-${i}`).addEventListener("click", () => searchPubChem(i));
    field.querySelector(`#pubchem-query-${i}`).addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); searchPubChem(i); }
    });
  });
}

function onCompoundPicked(slot, text) {
  // only an exact dropdown entry counts as picked
  picked[slot] = compounds.find((c) => compoundLabel(c) === text) || null;
  showCompoundCard(slot);
  fillFromCompounds();
  updateTitle();
  updatePreview();
}

function showCompoundCard(slot) {
  const card = document.getElementById(`compound-card-${slot}`);
  const c = picked[slot];
  card.hidden = !c;
  if (!c) return;
  // built with textContent, never innerHTML, since names come from the ELN
  const chip = (text, kind) => Object.assign(document.createElement("span"), { className: `chip ${kind}`, textContent: text });
  const chips = c.hazards.map((h) => chip(h, "hazard"));
  if (c.peroxide_class) chips.push(chip(`Peroxide former: ${c.peroxide_class}`, "peroxide"));
  if (chips.length === 0) chips.push(chip("No hazard data: check the SDS", "none"));
  const name = Object.assign(document.createElement("strong"), { textContent: c.name });
  card.replaceChildren(name, ` · CAS ${c.cas || "—"} · ${c.formula || ""}`, document.createElement("br"), ...chips);
}

// ---------- 1b. a compound that isn't in the list: PubChem ----------

function togglePubChem(slot) {
  const box = document.getElementById(`pubchem-${slot}`);
  box.hidden = !box.hidden;
  if (!box.hidden) {
    // start from what was typed in the compound box, if it looks useful
    const typed = document.getElementById(`compound-${slot}`).value.trim();
    const query = document.getElementById(`pubchem-query-${slot}`);
    if (typed && !query.value) query.value = typed;
    query.focus();
  }
}

const looksLikeCas = (text) => /^\d{2,7}-\d{2}-\d$/.test(text);

// a short message (and optional buttons) in a slot's PubChem box
function pubchemMessage(slot, text, kind = "") {
  const results = document.getElementById(`pubchem-results-${slot}`);
  results.replaceChildren(Object.assign(document.createElement("div"), { className: `message ${kind}`, textContent: text }));
}

// GET /compounds/pubchem: read-only lookup; nothing is saved yet
async function searchPubChem(slot) {
  const query = document.getElementById(`pubchem-query-${slot}`).value.trim();
  if (!query) return pubchemMessage(slot, "Type a CAS number or a name.", "error");
  const cas = looksLikeCas(query) ? query : "";
  pubchemMessage(slot, "Searching PubChem…");
  const response = await fetch(`/compounds/pubchem?${new URLSearchParams(cas ? { cas } : { name: query })}`);
  const data = await response.json();
  if (response.status === 404) return pubchemMessage(slot, `PubChem found nothing for "${query}". Check the CAS number on the bottle, or try again in a minute (PubChem is sometimes busy).`, "error");
  if (!response.ok) return pubchemMessage(slot, data.error || `Search failed (${response.status}). Try again.`, "error");
  showCandidates(slot, data.candidates, cas);
}

// one row per PubChem match, with what the user can do with it
function showCandidates(slot, candidates, cas) {
  const results = document.getElementById(`pubchem-results-${slot}`);
  results.replaceChildren();
  for (const { pubchem, existing, reason, can_restore } of candidates) {
    const row = Object.assign(document.createElement("div"), { className: "candidate" });
    const title = Object.assign(document.createElement("strong"), { textContent: pubchem.name });
    row.append(title, ` · CAS ${pubchem.cas || "—"} · ${pubchem.formula || ""} · PubChem ${pubchem.cid}`);

    const buttons = Object.assign(document.createElement("div"), { className: "buttons" });
    const addButton = (text, onClick, secondary = false) => {
      const b = Object.assign(document.createElement("button"), { type: "button", textContent: text, className: secondary ? "secondary" : "" });
      b.addEventListener("click", onClick);
      buttons.append(b);
    };
    const note = (text) => row.append(Object.assign(document.createElement("div"), { className: "hint", textContent: text }));

    if (existing && !existing.deleted) {
      note(`Already in the ELN as #${existing.id} ${existing.name} (${reason}).`);
      addButton(`Use #${existing.id} ${existing.name}`, () => pickCompoundById(slot, existing.id));
    } else if (existing && can_restore) {
      note(`This compound was deleted earlier as #${existing.id} ${existing.name} (${reason}). It can be brought back with fresh details from PubChem.`);
      addButton(`Restore #${existing.id}`, () => addCompound(slot, pubchem.cid, cas, existing.id));
    } else if (existing) {
      note(`It matches several old, deleted compounds (e.g. #${existing.id}). Ask a lab admin to sort them out.`);
    } else {
      addButton("Add this compound to the ELN", () => addCompound(slot, pubchem.cid, cas));
    }
    row.append(buttons);
    results.append(row);
  }
}

// POST /compounds: create it (or restore the deleted one), then pick it for this bottle
async function addCompound(slot, cid, cas, restoreId = null) {
  pubchemMessage(slot, restoreId ? "Restoring…" : "Adding to the ELN…");
  const body = { cid, cas: cas || null };
  if (restoreId) body.restore = restoreId;
  const { status, data } = await postJSON("/compounds", body);
  if (status === 201 || status === 200) {
    await pickCompoundById(slot, data.id);
    const what = data.restored ? "Restored" : "Added to the ELN";
    const hazards = data.pictograms === null ? " PubChem has no hazard data for it: check the SDS." : "";
    setCompoundNote(slot, `✔ ${what} as #${data.id} ${data.name}.${hazards}`);
  } else if (status === 409) {
    pubchemMessage(slot, `${data.error}: #${data.existing.id} ${data.existing.name}.`, "error");
  } else {
    pubchemMessage(slot, data.error || `Adding failed (${status}).`, "error");
  }
}

// reload the compound list (a new one was added) and pick that compound in this slot
async function pickCompoundById(slot, id) {
  compounds = await getJSON("/compounds_list");
  fillCompoundOptions();
  const compound = compounds.find((c) => c.id === id);
  if (!compound) return;
  const input = document.getElementById(`compound-${slot}`);
  input.value = compoundLabel(compound);
  onCompoundPicked(slot, input.value);
  document.getElementById(`pubchem-${slot}`).hidden = true;
  document.getElementById(`pubchem-results-${slot}`).replaceChildren();
  setCompoundNote(slot, "");
}

// a line under the compound card ("✔ Added to the ELN as #162 …")
function setCompoundNote(slot, text) {
  const card = document.getElementById(`compound-card-${slot}`);
  card.querySelector(".hint")?.remove();
  if (text) card.append(Object.assign(document.createElement("div"), { className: "hint", textContent: text }));
}

// copy the picked compounds' CAS (and the solvent's name) into the bottle's fields,
// unless the user already typed something there
function fillFromCompounds() {
  const [first, second] = picked;
  setIfUntouched("CAS", first?.cas);
  setIfUntouched("Solvent", second?.name);
  setIfUntouched("Solvent CAS", second?.cas);
}

function setIfUntouched(fieldName, value) {
  const input = document.querySelector(`[data-field="${CSS.escape(fieldName)}"]`);
  if (input && !input.dataset.touched) input.value = value || "";
}

// ---------- 2. where it is kept ----------

// every place below a room (or place), at any depth, sorted by path
function placesIn(parentId) {
  const below = [];
  const walk = (id) => {
    for (const unit of storage.filter((u) => u.parent_id === id)) {
      below.push(unit);
      walk(unit.id);
    }
  };
  walk(parentId);
  return below.sort((a, b) => a.full_path.localeCompare(b.full_path));
}

// "Front hood › Flammable cabinet": a place's path without its room
function placeLabel(place) {
  return place.full_path.split(" > ").slice(1).join(" › ");
}

function fillRooms() {
  const select = document.getElementById("room");
  select.innerHTML = "";
  select.add(new Option("— choose —", ""));
  for (const room of storage.filter((u) => u.parent_id === null)) select.add(new Option(room.name, room.id));
}

// the Place dropdown lists only the chosen room's places, then "+ Add a new place…"
function fillPlaces(selectedId = "") {
  const roomId = parseInt(document.getElementById("room").value, 10);
  const select = document.getElementById("place");
  select.innerHTML = "";
  select.add(new Option(roomId ? "— choose —" : "— choose a room first —", ""));
  if (roomId) {
    for (const place of placesIn(roomId)) select.add(new Option(placeLabel(place), place.id));
    select.add(new Option("＋ Add a new place…", ADD_PLACE));
  }
  select.value = String(selectedId);
}

function onRoomChange() {
  fillPlaces();
  hideAddPlace();
  setPlaceNote("");
  updatePreview();
}

function onPlaceChange() {
  setPlaceNote("");
  if (document.getElementById("place").value === ADD_PLACE) showAddPlace();
  else hideAddPlace();
  updatePreview();
}

function setPlaceNote(text) {
  document.getElementById("place-note").textContent = text;
}

// ---------- 2b. + Add a new place ----------

function showAddPlace() {
  const roomId = parseInt(document.getElementById("room").value, 10);
  const room = storage.find((u) => u.id === roomId);
  // the new place can go in the room itself or inside one of its places
  const parent = document.getElementById("new-place-parent");
  parent.innerHTML = "";
  parent.add(new Option(`${room.name} (the room itself)`, room.id));
  for (const place of placesIn(roomId)) parent.add(new Option(placeLabel(place), place.id));
  document.getElementById("new-place-name").value = "";
  showAddPlaceMessage(null);
  document.getElementById("add-place").hidden = false;
  document.getElementById("new-place-name").focus();
}

function hideAddPlace() {
  document.getElementById("add-place").hidden = true;
}

// a message inside the add-place box, optionally with buttons [{text, onClick, secondary}]
function showAddPlaceMessage(text, kind = "", buttons = []) {
  const box = document.getElementById("add-place-message");
  box.hidden = !text;
  box.className = `message ${kind}`;
  box.replaceChildren(text || "");
  if (buttons.length) {
    const row = Object.assign(document.createElement("div"), { className: "buttons" });
    row.style.marginTop = "0.5em";
    for (const b of buttons) {
      const button = Object.assign(document.createElement("button"), {
        type: "button", textContent: b.text, className: b.secondary ? "secondary" : "",
      });
      button.addEventListener("click", b.onClick);
      row.append(button);
    }
    box.append(row);
  }
}

// pick a place in the Place dropdown (after adding it, or when it already existed)
function choosePlace(place, note) {
  hideAddPlace();
  fillPlaces(place.id);
  setPlaceNote(note);
  updatePreview();
}

// ask the server to add the place; confirm=true means "add it even though a similar name exists"
async function addPlace(confirm = false) {
  const name = document.getElementById("new-place-name").value.trim();
  const parentId = parseInt(document.getElementById("new-place-parent").value, 10);
  if (!name) {
    showAddPlaceMessage("Type a name for the new place.", "error");
    return;
  }
  const { status, data } = await postJSON("/storage_units", { name, parent_id: parentId, confirm });

  if (status === 201) {
    storage.push(data);
    choosePlace(data, `✔ Added ${placeLabel(data)}`);
  } else if (status === 409 && data.exact) {
    // the same name is already there: just use that place
    choosePlace(data.existing, `This place already exists, so it's selected: ${placeLabel(data.existing)}`);
  } else if (status === 409) {
    showAddPlaceMessage(`Did you mean "${placeLabel(data.existing)}"?`, "", [
      { text: `Use "${data.existing.name}"`, onClick: () => choosePlace(data.existing, "") },
      { text: `Add "${name}" anyway`, onClick: () => addPlace(true), secondary: true },
    ]);
  } else if (status === 403) {
    showAddPlaceMessage("eLabFTW doesn't let you add storage places. Ask a lab admin to add it.", "error");
  } else {
    showAddPlaceMessage(data.error || `Adding the place failed (${status}).`, "error");
  }
}

// ---------- 3. how much ----------

// the State the user chose ("Liquid", "Solid", "Gas"), or "" if none yet
function currentState() {
  return document.querySelector('[data-field="State"]')?.value || "";
}

// units for the chosen State first, then eLabFTW's other units (for unusual cases)
function fillUnits() {
  const select = document.getElementById("unit");
  const previous = select.value;
  const suggested = formInfo.units_by_state[currentState()] || [];
  select.innerHTML = "";
  select.add(new Option("unit", ""));
  for (const unit of suggested) select.add(new Option(unit, unit));
  const others = formInfo.units.filter((u) => !suggested.includes(u));
  if (suggested.length) {
    const divider = new Option("— other units —", "");
    divider.disabled = true;
    select.add(divider);
  }
  for (const unit of others) select.add(new Option(unit, unit));
  // keep the unit if it suits the State (or no State is chosen); else the State's usual one
  const usual = { Liquid: "mL", Solid: "g", Gas: "bar" }[currentState()] || "";
  const keep = previous && (suggested.length === 0 || suggested.includes(previous));
  select.value = keep ? previous : usual;
}

// ---------- the bottle's name ----------

function updateTitle() {
  if (titleTouched) return;
  const [first, second] = picked;
  let title = first?.name || "";
  if (first && second) title = `${first.name} in ${second.name}`;
  document.getElementById("title").value = title;
}

// ---------- the bottle's own fields (from the template) ----------

function drawBottleFields() {
  const box = document.getElementById("bottle-fields");
  const stateSlot = document.getElementById("state-slot");
  box.innerHTML = "";
  stateSlot.innerHTML = "";
  for (const f of currentCategory()?.fields || []) {
    // State decides the units, so it sits in "3. How much" next to the amount
    (f.name === "State" ? stateSlot : box).append(fieldElement(f));
  }
  fillUnits();
}

// one form field for a template field: select, date, number (with unit) or text
function fieldElement(f) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  const id = `field-${f.name.replace(/\W+/g, "-")}`;
  wrapper.innerHTML = `<label for="${id}" class="${f.required ? "required" : ""}"></label>`;
  wrapper.querySelector("label").textContent = f.name;

  let input;
  if (f.type === "select") {
    input = document.createElement("select");
    input.add(new Option("— choose —", ""));
    for (const option of f.options || []) input.add(new Option(option, option));
    if (!NO_OTHER.has(f.name)) input.add(new Option("Other…", OTHER));
  } else {
    input = document.createElement("input");
    input.type = { date: "date", number: "number" }[f.type] || "text";
    if (f.type === "number") input.step = "any";
  }
  input.id = id;
  input.dataset.field = f.name;
  input.addEventListener("input", () => { input.dataset.touched = "1"; updatePreview(); });

  if (f.type === "number" && f.unit) {
    const row = document.createElement("div");
    row.className = "with-unit";
    row.append(input, Object.assign(document.createElement("span"), { textContent: f.unit }));
    wrapper.append(row);
  } else {
    wrapper.append(input);
  }

  if (f.type === "select") {
    // "Other…" shows a box to type a value that isn't in the list
    const other = Object.assign(document.createElement("input"), {
      type: "text", placeholder: `Type the ${f.name.toLowerCase()}`, hidden: true,
    });
    other.dataset.otherFor = f.name;
    other.addEventListener("input", updatePreview);
    input.addEventListener("change", () => { other.hidden = input.value !== OTHER; updatePreview(); });
    wrapper.append(other);
  }
  if (f.description) {
    wrapper.append(Object.assign(document.createElement("div"), { className: "description", textContent: f.description }));
  }
  return wrapper;
}

// the value of every bottle field the user filled in: {name: value}
function bottleFieldValues() {
  const values = {};
  for (const input of document.querySelectorAll("#bottle-form [data-field]")) {
    let value = input.value.trim();
    if (value === OTHER) {
      value = document.querySelector(`[data-other-for="${CSS.escape(input.dataset.field)}"]`).value.trim();
    }
    if (value === "") continue;
    values[input.dataset.field] = input.type === "number" ? Number(value) : value;
  }
  return values;
}

// ---------- what Create will send ----------

function buildRequest() {
  if (isInstrument()) {
    return {
      category: currentCategory().id,
      title: document.getElementById("title").value.trim(),
      fields: bottleFieldValues(),
      procedure: document.getElementById("procedure").value,
    };
  }
  return {
    category: currentCategory()?.id ?? null,
    title: document.getElementById("title").value.trim(),
    compounds: picked.filter(Boolean).map((c) => c.id),
    storage: {
      place_id: parseInt(document.getElementById("place").value, 10) || null,
      amount: amountValue(),
      unit: document.getElementById("unit").value,
    },
    count: parseInt(document.getElementById("count").value, 10) || 1,
    fields: bottleFieldValues(),
  };
}

// the amount as a number, or null if the box is empty
function amountValue() {
  const text = document.getElementById("amount").value.trim();
  return text === "" ? null : Number(text);
}

function updatePreview() {
  document.getElementById("preview").textContent = JSON.stringify(buildRequest(), null, 2);
}

// ---------- Create ----------

// what's missing before we can send, as [{element, text}]; nothing is sent until it's empty
function missingAnswers(request) {
  const missing = [];
  const need = (ok, element, text) => { if (!ok) missing.push({ element, text }); };
  const slots = currentCategory()?.compound_slots || [];
  slots.forEach((slotName, i) => need(picked[i], document.getElementById(`compound-${i}`),
    `${slotName}: pick it from the list`));
  if (!isInstrument()) {
    need(request.storage.place_id, document.getElementById("room").value ? document.getElementById("place")
      : document.getElementById("room"), "Where it is kept: choose a room and a place");
    need(request.storage.amount !== null && request.storage.amount >= 0, document.getElementById("amount"),
      "Amount: a number, 0 or more");
    need(request.storage.unit, document.getElementById("unit"), "Unit");
    need(request.count >= 1 && request.count <= 20, document.getElementById("count"), "Number of bottles: 1 to 20");
  }
  need(request.title, document.getElementById("title"), "Name");
  // the template marks some fields as required (Lot number, Received...)
  for (const f of currentCategory()?.fields || []) {
    if (f.required && !(f.name in request.fields)) {
      need(false, document.querySelector(`[data-field="${CSS.escape(f.name)}"]`), f.name);
    }
  }
  return missing;
}

// a message above the Create button: text, an optional list, links and buttons
function showCreateMessage({ text, kind = "", items = [], links = [], buttons = [] }) {
  const box = document.getElementById("create-message");
  box.hidden = !text;
  box.className = `message ${kind}`;
  box.replaceChildren(text || "");
  if (items.length || links.length) {
    const list = document.createElement("ul");
    for (const item of items) list.append(Object.assign(document.createElement("li"), { textContent: item }));
    for (const link of links) {
      const li = document.createElement("li");
      li.append(Object.assign(document.createElement("a"), {
        href: link.url, target: "_blank", rel: "noopener", textContent: link.text,
      }));
      if (link.after) li.append(link.after);
      list.append(li);
    }
    box.append(list);
  }
  if (buttons.length) {
    const row = Object.assign(document.createElement("div"), { className: "buttons" });
    row.style.marginTop = "0.6em";
    for (const b of buttons) {
      const button = Object.assign(document.createElement("button"), {
        type: "button", textContent: b.text, className: b.secondary ? "secondary" : "",
      });
      button.addEventListener("click", b.onClick);
      row.append(button);
    }
    box.append(row);
  }
  box.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function onCreate(event, confirmSameLot = false) {
  event?.preventDefault(); // stop the browser's own form submit (it would reload the page)
  document.querySelectorAll(".missing").forEach((el) => el.classList.remove("missing"));

  const request = buildRequest();
  const missing = missingAnswers(request);
  if (missing.length) {
    missing.forEach((m) => m.element?.classList.add("missing"));
    showCreateMessage({ text: "Please fill in:", kind: "error", items: missing.map((m) => m.text) });
    missing[0].element?.focus();
    return;
  }
  if (confirmSameLot) request.confirm_same_lot = true;

  // one click = one request: the button stays disabled until the answer is back
  const button = document.getElementById("create-button");
  button.disabled = true;
  button.textContent = "Creating…";
  try {
    const { status, data } = await postJSON("/resources", request);
    if (status === 201) showCreated(data);
    else if (status === 409) showSameLot(data);
    else showCreateMessage({ text: data.error || `Creating failed (${status}).`, kind: "error" });
  } catch (e) {
    showCreateMessage({ text: `Could not reach the server: ${e.message}`, kind: "error" });
  } finally {
    button.disabled = false;
    button.textContent = "Create";
  }
}

// 409: bottles from this lot are already in the ELN; ask about the label
function showSameLot(data) {
  showCreateMessage({
    text: `${data.error}. ${data.question}`,
    links: data.same_lot.map((b) => ({ url: b.url, text: `#${b.id} ${b.title}` })),
    buttons: [
      { text: "It's another bottle: add it", onClick: () => onCreate(null, true) },
      { text: "Cancel", secondary: true, onClick: () => showCreateMessage({}) },
    ],
  });
}

// 201: the bottle(s) exist. Show their numbers, tags, and any step to finish by hand.
function showCreated(data) {
  document.getElementById("bottle-form").classList.add("done");
  const bottles = data.bottles;
  const links = bottles.map((b) => ({
    url: b.url,
    text: `#${b.id} ${document.getElementById("title").value}`,
    after: (b.tags.length ? ` · ${b.tags.join(", ")}` : "")
      + (b.next_due ? ` · next maintenance due ${b.next_due}` : ""),
  }));
  const problems = [...data.problems, ...bottles.flatMap((b) => b.problems.map((p) => `#${b.id}: ${p}`))];
  const what = isInstrument() ? "instrument" : bottles.length === 1 ? "bottle" : `${bottles.length} bottles`;
  showCreateMessage({
    text: `✔ Created ${what}. Write the number on it, or print its label:`,
    kind: problems.length ? "" : "ok",
    links,
    items: problems.map((p) => `⚠ ${p} (finish this in eLabFTW)`),
    buttons: [
      { text: bottles.length === 1 ? "Print label" : `Print ${bottles.length} labels`,
        onClick: () => printLabels(bottles.map((b) => b.id)) },
      { text: isInstrument() ? "Add another instrument" : "Add another bottle", onClick: () => window.location.reload(), secondary: true },
    ],
  });
}

// POST /print and show the PDF in a new tab, to print on the label printer
async function printLabels(ids) {
  // browsers block tabs opened after a wait, so open it now (empty) and fill it in below
  const tab = window.open("", "_blank");
  try {
    const response = await fetch("/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: ids }),
    });
    if (!response.ok) throw new Error((await response.json()).error || `status ${response.status}`);
    const pdfUrl = URL.createObjectURL(await response.blob());
    if (tab) {
      tab.location = pdfUrl;
    } else {
      // pop-ups are blocked: offer a link instead
      const link = Object.assign(document.createElement("a"), {
        href: pdfUrl, target: "_blank", download: "labels.pdf", textContent: "Open the labels (PDF)",
      });
      const line = Object.assign(document.createElement("div"), { className: "hint" });
      line.append("Your browser blocked the new tab: ", link);
      document.getElementById("create-message").append(line);
    }
  } catch (e) {
    tab?.close();
    alert(`Printing the labels failed: ${e.message}. Print them later from the start page (scan or type the numbers, then "print").`);
  }
}

// ---------- start ----------

async function start() {
  document.getElementById("category").addEventListener("change", onCategoryChange);
  document.getElementById("title").addEventListener("input", () => { titleTouched = true; updatePreview(); });
  document.getElementById("bottle-form").addEventListener("submit", onCreate);
  document.getElementById("room").addEventListener("change", onRoomChange);
  for (const id of ["amount", "unit", "count", "procedure"]) {
    document.getElementById(id).addEventListener("input", updatePreview);
  }
  // choosing a State changes the units on offer
  document.getElementById("state-slot").addEventListener("change", () => { fillUnits(); updatePreview(); });
  document.getElementById("place").addEventListener("change", onPlaceChange);
  document.getElementById("add-place-button").addEventListener("click", () => addPlace(false));
  // Enter in the new place's name adds the place (instead of submitting the whole form)
  document.getElementById("new-place-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); addPlace(false); }
  });
  document.getElementById("add-place-cancel").addEventListener("click", () => {
    hideAddPlace();
    document.getElementById("place").value = "";
    updatePreview();
  });
  try {
    // the three lists load at the same time
    [formInfo, compounds, storage] = await Promise.all([
      getJSON("/bottle_form"), getJSON("/compounds_list"), getJSON("/storage_tree"),
    ]);
  } catch (e) {
    console.error(e);
    return;
  }
  fillCategories();
  fillCompoundOptions();
  fillRooms();
  fillPlaces();
  onCategoryChange();
}

start();
