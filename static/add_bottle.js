// Add-a-bottle page. Runs in the browser and talks to our server with fetch():
//   GET /bottle_form     -> bottle categories, the compounds each needs, the bottle's own fields
//   GET /compounds_list  -> existing compounds (with their hazards) for the dropdown
//   GET /storage_tree    -> rooms and the places inside them
//   POST /storage_units  -> add a new place (the server refuses near-duplicate names)
// The user's API key travels by itself in the apiKey cookie.

// what the page knows, filled once when it opens
let formInfo = { categories: [], units: [], units_by_state: {} };
let compounds = []; // [{id, name, cas, formula, hazards, peroxide_class}]
let storage = []; // [{id, name, parent_id, full_path}]; rooms have parent_id null
let picked = []; // the compound picked in each slot (null until picked)
let titleTouched = false; // stop filling the name in once the user types their own

const OTHER = "__other__"; // select value meaning "typed in the Other box"
const ADD_PLACE = "__add_place__"; // place value meaning "+ Add a new place…"

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

function fillCategories() {
  const select = document.getElementById("category");
  select.innerHTML = "";
  for (const c of formInfo.categories) {
    select.add(new Option(c.title, c.id));
  }
}

// redraw everything that depends on the category
function onCategoryChange() {
  drawCompoundPickers();
  drawBottleFields();
  updateTitle();
  updatePreview();
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
      <div class="hint">Not in the list? Searching PubChem comes next (D4e).</div>
      <div class="compound-card" id="compound-card-${i}" hidden></div>`;
    box.append(field);
    field.querySelector("input").addEventListener("input", (e) => onCompoundPicked(i, e.target.value));
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
    input.add(new Option("Other…", OTHER));
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

// ---------- start ----------

async function start() {
  document.getElementById("category").addEventListener("change", onCategoryChange);
  document.getElementById("title").addEventListener("input", () => { titleTouched = true; updatePreview(); });
  document.getElementById("room").addEventListener("change", onRoomChange);
  for (const id of ["amount", "unit", "count"]) {
    document.getElementById(id).addEventListener("input", updatePreview);
  }
  // choosing a State changes the units on offer
  document.getElementById("state-slot").addEventListener("change", () => { fillUnits(); updatePreview(); });
  document.getElementById("place").addEventListener("change", onPlaceChange);
  document.getElementById("add-place-button").addEventListener("click", () => addPlace(false));
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
