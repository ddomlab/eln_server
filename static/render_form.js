const BASE_URL = ""; // adjust as needed
// select value meaning "the user typed their own value in the Other box"
const OTHER_SENTINEL = "__other__";
const formEl = document.getElementById("generated-form");
let currentFields = [];
let elnWebUrl = ""; // the lab's eLabFTW web UI, served by /eln_config
let resourceCategories = []; // [{id, title}] from /categories (the team's own list)

function setCookie(name, value) {
  const expires = "Fri, 31 Dec 9999 23:59:59 GMT";
  document.cookie = `${name}=${encodeURIComponent(
    value
  )}; expires=${expires}; path=/`;
}

function getCookie(name) {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(name + "="));
  return match && decodeURIComponent(match.split("=")[1]);
}

function getFinalOutput() {
  const formData = new FormData(formEl);
  const extra_fields = {};
  currentFields.forEach(([key, field]) => {
    const copy = structuredClone(field);
    let value = formData.get(key) || "";
    if (value === OTHER_SENTINEL) {
      value = (formData.get(`${key}__other`) || "").trim();
    }
    copy.value = value;
    extra_fields[key] = copy;
  });
  return {
    title: formData.get("title") || "",
    body: formData.get("body") || "",
    category: parseInt(formData.get("category"), 10) || null,
    extra_fields,
  };
}

function getOptionAdditions() {
  // Fields where "Other" is selected with "Add to options?" checked:
  // [{field, option}] to send to /add_option so the template learns them.
  const formData = new FormData(formEl);
  const additions = [];
  currentFields.forEach(([key, field]) => {
    if (field.type !== "select") return;
    if (formData.get(key) !== OTHER_SENTINEL) return;
    if (!formData.get(`${key}__addopt`)) return;
    const option = (formData.get(`${key}__other`) || "").trim();
    if (option) additions.push({ field: key, option });
  });
  return additions;
}

function fetchTemplate(category) {
  const url = category
    ? `${BASE_URL}/template?category=${category}`
    : `${BASE_URL}/template`;
  return fetch(url).then((res) => {
    if (!res.ok) throw new Error(`Fetch failed: ${res.status}`);
    return res.json();
  });
}

function buildFormFromJson(jsonData) {
  formEl.innerHTML = "";
  console.log("Rendering schema:", jsonData);
  // API Key
  const apiKey = getCookie("apiKey");
  if (!apiKey) {
    alert(
      "No API key found. Please paste an API key to continue. To generate your own, navigate to " +
        (elnWebUrl
          ? `${elnWebUrl}/ucp.php?tab=3`
          : "the API keys tab of your eLabFTW user settings")
    );
    const wrapper = document.createElement("div");
    wrapper.className = "field";
    const label = document.createElement("label");
    label.htmlFor = "apiKey";
    label.textContent = "API Key";
    const input = document.createElement("input");
    input.type = "text";
    input.id = "apiKey";
    input.name = "apiKey";
    input.required = true;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Save Key";
    btn.className = "save-btn";
    btn.addEventListener("click", () => {
      const key = input.value.trim();
      if (key) {
        setCookie("apiKey", key);
        location.reload();
      } else alert("Enter a valid API key.");
    });
    wrapper.append(label, input, btn);
    formEl.append(wrapper);
  }

  // Category
  const categoryWrapper = document.createElement("div");
  categoryWrapper.className = "field";
  const categoryLabel = document.createElement("label");
  categoryLabel.htmlFor = "category";
  categoryLabel.innerHTML = 'Category <span style="color:red">*</span>';
  const categorySelect = document.createElement("select");
  categorySelect.id = "category";
  categorySelect.name = "category";
  categorySelect.required = true;
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.disabled = true;
  placeholder.selected = true;
  placeholder.hidden = true;
  placeholder.textContent = "Select a category";
  categorySelect.append(placeholder);
  resourceCategories.forEach((cat) => {
    const o = document.createElement("option");
    o.value = cat.id;
    o.textContent = cat.title;
    categorySelect.append(o);
  });
  categorySelect.value = jsonData.category || "";
  categorySelect.addEventListener("change", () => {
    const selected = categorySelect.value;
    const previousData = getFinalOutput();
    fetchTemplate(selected)
      .then((newSchema) => {
        // Inject previous values where keys match
        Object.entries(newSchema.extra_fields || {}).forEach(([key, field]) => {
          if (
            previousData.extra_fields[key] &&
            previousData.extra_fields[key].value
          ) {
            field.value = previousData.extra_fields[key].value;
          }
        });

        // Also preserve title and body if present
        newSchema.title = previousData.title;
        newSchema.body = previousData.body;
        newSchema.category = selected;

        buildFormFromJson(newSchema);
      })
      .catch((e) => alert(e.message));
  });

  categoryWrapper.append(categoryLabel, categorySelect);
  formEl.append(categoryWrapper);

  // CAS Search
  const searchWrapper = document.createElement("div");
  searchWrapper.id = "cas-search-wrapper";
  searchWrapper.className = "field";
  // searchWrapper.style.display = "flex";
  searchWrapper.style.gap = "0.5em";
  // Determine visibility of CAS search
  const catVal = jsonData.category;
  if (catVal && catVal !== "1") {
    searchWrapper.style.display = "flex";
  } else {
    searchWrapper.style.display = "none";
}

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.placeholder = "Search by CAS";
  const searchBtn = document.createElement("button");
  searchBtn.type = "button";
  searchBtn.textContent = "Search";
  searchBtn.className = "search-btn";
  searchBtn.addEventListener("click", () => {
    const cas = searchInput.value.trim();
    if (!cas) return alert("Enter a CAS.");
    fetch(`${BASE_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ CAS: cas, template: getFinalOutput() }),
      credentials: "same-origin",
    })
      .then((r) => r.json())
      .then((data) => {
        if (data && data.extra_fields && !data.error) {
          // preserve currently selected category
          const selected = formEl.querySelector("#category")?.value;
          if (selected) {
            data.category = selected; // override category from response
          }
          buildFormFromJson(data);
        } else if (data.error) {
          alert(`Error: ${data.error}`);
        } 
        else {
          alert("Invalid response");
        }
      })

      .catch((e) => alert(e.message));
  });
  searchWrapper.append(searchInput, searchBtn);
  formEl.append(searchWrapper);

  // Title
  const titleWrapper = document.createElement("div");
  titleWrapper.className = "field";
  const titleLabel = document.createElement("label");
  titleLabel.htmlFor = "title";
  titleLabel.innerHTML = 'Title <span style="color:red">*</span>';
  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.id = "title";
  titleInput.name = "title";
  titleInput.required = true;
  titleInput.value = jsonData.title || ""; // ✅ SET VALUE
  titleWrapper.append(titleLabel, titleInput);
  formEl.append(titleWrapper);

  // Body
  const bodyWrapper = document.createElement("div");
  bodyWrapper.className = "field";
  const bodyLabel = document.createElement("label");
  bodyLabel.htmlFor = "body";
  bodyLabel.innerHTML = "Body";
  const bodyInput = document.createElement("textarea");
  bodyInput.id = "body";
  bodyInput.name = "body";
  bodyInput.rows = 5;
  bodyInput.value = jsonData.body || ""; // ✅ SET VALUE
  bodyWrapper.append(bodyLabel, bodyInput);
  formEl.append(bodyWrapper);

  // Extra fields
  let fields = {};
  if (jsonData.extra_fields) {
    fields = jsonData.extra_fields;
  } else if (jsonData.metadata) {
    try {
      const parsed = JSON.parse(jsonData.metadata);
      if (parsed.extra_fields) {
        fields = parsed.extra_fields;
      }
    } catch (e) {
      console.error("Failed to parse metadata:", e);
    }
  }

  currentFields = Object.entries(fields).sort(
    (a, b) => (a[1].position || 0) - (b[1].position || 0)
  );

  currentFields.forEach(([key, field]) => {
    const wrapper = document.createElement("div");
    wrapper.className = "field";

    const label = document.createElement("label");
    label.htmlFor = key;
    label.innerHTML = field.required
      ? `${key} <span style="color:red">*</span>`
      : key;
    wrapper.append(label);

    let input;
    let otherControls = null; // "Other" text box + "Add to options?" checkbox (selects only)
    let otherNote = null; // shown while "Add to options?" is checked
    let applySelectValue = null; // sets a select's value, routing unknown values to "Other"
    if (field.type === "select") {
      input = document.createElement("select");
      (field.options || []).forEach((opt) => {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        input.append(o);
      });
      const otherOption = document.createElement("option");
      otherOption.value = OTHER_SENTINEL;
      otherOption.textContent = "Other…";
      input.append(otherOption);

      const otherInput = document.createElement("input");
      otherInput.type = "text";
      otherInput.name = `${key}__other`;
      otherInput.placeholder = "Enter other value";
      otherInput.disabled = true;
      // let the flex row shrink the input instead of overflowing the wrapper
      otherInput.style.flex = "1 1 auto";
      otherInput.style.minWidth = "0";
      otherInput.style.width = "auto";

      const addLabel = document.createElement("label");
      addLabel.style.fontWeight = "normal";
      addLabel.style.whiteSpace = "nowrap";
      addLabel.style.display = "flex";
      addLabel.style.alignItems = "center";
      addLabel.style.gap = "0.4em";
      addLabel.style.marginBottom = "0";
      const addCheckbox = document.createElement("input");
      addCheckbox.type = "checkbox";
      addCheckbox.name = `${key}__addopt`;
      addCheckbox.disabled = true;
      // opt out of the page's full-width/padded input styling
      addCheckbox.style.width = "auto";
      addCheckbox.style.boxShadow = "none";
      addCheckbox.style.padding = "0";
      addLabel.append(addCheckbox, document.createTextNode(" Add to options?"));

      otherControls = document.createElement("div");
      otherControls.style.display = "none";
      otherControls.style.gap = "0.5em";
      otherControls.style.alignItems = "center";
      otherControls.style.marginTop = "0.5em";
      otherControls.append(otherInput, addLabel);

      otherNote = document.createElement("div");
      otherNote.className = "description";
      otherNote.style.display = "none";
      otherNote.textContent =
        "Only adds the option for the selected category (e.g. Chemical Compound locations are managed independently from Polymer locations).";

      const syncOtherVisibility = () => {
        const isOther = input.value === OTHER_SENTINEL;
        otherControls.style.display = isOther ? "flex" : "none";
        // disabled inputs stay out of FormData and skip validation
        otherInput.disabled = !isOther;
        addCheckbox.disabled = !isOther;
        otherInput.required = isOther && !!field.required;
        otherNote.style.display = isOther && addCheckbox.checked ? "" : "none";
      };
      addCheckbox.addEventListener("change", syncOtherVisibility);
      input.addEventListener("change", () => {
        syncOtherVisibility();
        if (input.value === OTHER_SENTINEL) otherInput.focus();
      });

      applySelectValue = (value) => {
        input.value = value;
        if (value && input.value !== value) {
          // value isn't one of the options: it came from "Other"
          input.value = OTHER_SENTINEL;
          otherInput.value = value;
        }
        syncOtherVisibility();
      };
    } else if (field.type === "date") {
      input = document.createElement("input");
      input.type = "date";

      const todayBtn = document.createElement("button");
      todayBtn.type = "button";
      todayBtn.textContent = "Today";
      todayBtn.className = "today-btn";
      todayBtn.addEventListener("click", () => {
        input.value = new Date().toISOString().split("T")[0];
      });

      const cnt = document.createElement("div");
      cnt.style.display = "flex";
      cnt.style.gap = "0.5em";
      cnt.append(input, todayBtn);
      wrapper.append(cnt);
    } else {
      input = document.createElement("input");
      input.type = field.type || "text";
      wrapper.append(input);
    }

    input.id = key;
    input.name = key;
    if (applySelectValue) applySelectValue(field.value || "");
    else input.value = field.value || "";
    if (field.required) input.required = true;

    if (field.type !== "date") wrapper.append(input);
    if (otherControls) wrapper.append(otherControls, otherNote);

    if (field.type === "number") {
      input.type = "number";
      input.step = "any"; // allow decimals
    }

    if (Array.isArray(field.units) && field.units.length > 0) {
      const unitSelect = document.createElement("select");
      unitSelect.name = `${key}_unit`;

      field.units.forEach((unitOpt) => {
        const opt = document.createElement("option");
        opt.value = unitOpt;
        opt.textContent = unitOpt;
        unitSelect.append(opt);
      });

      // Preselect the current value (if specified)
      if (field.unit) {
        unitSelect.value = field.unit;
      }

      wrapper.append(unitSelect);
    }

    if (field.description) {
      const d = document.createElement("div");
      d.className = "description";
      d.textContent = field.description;
      wrapper.append(d);
    }

    formEl.append(wrapper);
  });

  // Submit
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Submit";
  formEl.append(submit);
  formEl.onsubmit = (e) => {
    e.preventDefault();

    // Custom conditional requirement: one of Mw or Mn must be filled
    const mwInput = formEl.querySelector('[name="Mw"]');
    const mnInput = formEl.querySelector('[name="Mn"]');

    const mwValue = mwInput ? mwInput.value.trim() : "";
    const mnValue = mnInput ? mnInput.value.trim() : "";

    if (mwInput && mnInput && !mwValue && !mnValue) {
      alert("Either 'Mw' or 'Mn' must be filled.");
      if (mwInput) mwInput.focus();
      return;
    }

    // Continue normal submission
    const payload = getFinalOutput();
    const optionAdditions = getOptionAdditions();

    fetch(`${BASE_URL}/add_resource`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload, null, 2),
      credentials: "same-origin",
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
        return res.json();
      })
      .then((responseData) => {
        console.log("Submission succeeded:", responseData);
        // alert("Form submitted successfully.");
        if (optionAdditions.length === 0) return;
        // The resource exists now; teach the category template the new options
        return Promise.all(
          optionAdditions.map((a) =>
            fetch(`${BASE_URL}/add_option`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ category: payload.category, ...a }),
              credentials: "same-origin",
            }).then((r) => {
              if (!r.ok)
                return r.json().then((d) => {
                  throw new Error(d.error || `Server responded with ${r.status}`);
                });
            })
          )
        ).catch((err) => {
          console.error("Option update error:", err);
          alert(
            `Resource was created, but adding the new option(s) to the template failed: ${err.message}`
          );
        });
      })
      .then(() => location.reload())
      .catch((err) => {
        console.error("Submission error:", err);
        alert("Error submitting form.");
      });
  };
}

// Initial load: learn the instance's web URL and category list first
Promise.all([
  fetch(`${BASE_URL}/eln_config`)
    .then((res) => (res.ok ? res.json() : {}))
    .then((cfg) => {
      elnWebUrl = cfg.eln_web_url || "";
    })
    .catch(() => {}),
  fetch(`${BASE_URL}/categories`)
    .then((res) => (res.ok ? res.json() : []))
    .then((cats) => {
      resourceCategories = Array.isArray(cats) ? cats : [];
    })
    .catch(() => {}),
])
  .then(() => fetchTemplate())
  .then(buildFormFromJson)
  .catch((e) => alert(e.message));
