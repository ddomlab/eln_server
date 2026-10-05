// Add-a-bottle page. Runs in the browser and talks to our server with fetch():
//   GET /bottle_form     -> bottle categories, the compounds each needs, the bottle's own fields
//   GET /compounds_list  -> existing compounds (with their hazards) for the dropdown
// The user's API key travels by itself in the apiKey cookie.

// what the page knows, filled once when it opens
let formInfo = { categories: [], units: [], units_by_state: {} };
let compounds = []; // [{id, name, cas, formula, hazards, peroxide_class}]
let picked = []; // the compound picked in each slot (null until picked)
let titleTouched = false; // stop filling the name in once the user types their own

const OTHER = "__other__"; // select value meaning "typed in the Other box"

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
  box.innerHTML = "";
  for (const f of currentCategory()?.fields || []) box.append(fieldElement(f));
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
  for (const input of document.querySelectorAll("#bottle-fields [data-field]")) {
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
    fields: bottleFieldValues(),
    // storage (D4b, D4c) and count (D4c) come next
  };
}

function updatePreview() {
  document.getElementById("preview").textContent = JSON.stringify(buildRequest(), null, 2);
}

// ---------- start ----------

async function start() {
  document.getElementById("category").addEventListener("change", onCategoryChange);
  document.getElementById("title").addEventListener("input", () => { titleTouched = true; updatePreview(); });
  try {
    // both lists load at the same time
    [formInfo, compounds] = await Promise.all([getJSON("/bottle_form"), getJSON("/compounds_list")]);
  } catch (e) {
    console.error(e);
    return;
  }
  fillCategories();
  fillCompoundOptions();
  onCategoryChange();
}

start();
