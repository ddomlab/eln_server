const BASE_URL = ""; // adjust as needed
const formEl = document.getElementById("generated-form");
let currentFields = [];

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
    copy.value = formData.get(key) || "";
    extra_fields[key] = copy;
  });
  return {
    title: formData.get("title") || "",
    body: formData.get("body") || "",
    category: parseInt(formData.get("category"), 10) || null,
    extra_fields,
  };
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
      "No API key found. Please paste an API key to continue. To generate your own, navigate to https://eln.ddomlab.org/ucp.php?tab=3"
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
  ["Instrument", "Chemical Compound", "Polymer", "Solution"].forEach(
    (opt, i) => {
      const o = document.createElement("option");
      o.value = i + 1;
      o.textContent = opt;
      categorySelect.append(o);
    }
  );
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
    if (field.type === "select") {
      input = document.createElement("select");
      (field.options || []).forEach((opt) => {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        input.append(o);
      });
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
    input.value = field.value || "";
    if (field.required) input.required = true;

    if (field.type !== "date") wrapper.append(input);

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
    // alert(JSON.stringify(getFinalOutput(), null, 2));
  };
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
    alert(JSON.stringify(getFinalOutput(), null, 2));
    const payload = getFinalOutput();

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
        location.reload();
      })
      .catch((err) => {
        console.error("Submission error:", err);
        alert("Error submitting form.");
      });
  };
}

// Initial load
fetchTemplate()
  .then(buildFormFromJson)
  .catch((e) => alert(e.message));
