const state = {
  catalog: null,
  cases: [],
  selectedId: null,
  sortKey: "technique_label",
  sortDirection: 1,
  query: "",
};

let openCustomSelect = null;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  prompt: $("#prompt-input"),
  characterCount: $("#character-count"),
  profile: $("#profile-select"),
  profileHint: $("#profile-hint"),
  intensity: $("#intensity-select"),
  count: $("#count-select"),
  generate: $("#generate-button"),
  customTechniques: $("#custom-techniques"),
  customChain: $("#custom-chain"),
  techniqueGrid: $("#technique-grid"),
  selectionSummary: $("#selection-summary"),
  rows: $("#case-rows"),
  empty: $("#empty-state"),
  loading: $("#loading-state"),
  search: $("#case-search"),
  countBadge: $("#case-count-badge"),
  resultSubtitle: $("#results-subtitle"),
  runStatus: $("#run-status"),
  runStatusText: $("#run-status-text"),
  inspectionModal: $("#inspection-modal"),
  inspectionContent: $("#inspection-content"),
  helpModal: $("#help-modal"),
};

initializeTheme();
bindEvents();
loadCatalog();

function initializeTheme() {
  const saved = localStorage.getItem("llm-redteam-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = saved || preferred;
}

function bindEvents() {
  $("#theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("llm-redteam-theme", next);
  });
  $("#help-toggle").addEventListener("click", () => elements.helpModal.showModal());
  $("#close-help").addEventListener("click", () => elements.helpModal.close());
  elements.helpModal.addEventListener("click", (event) => {
    if (event.target === elements.helpModal) elements.helpModal.close();
  });
  elements.prompt.addEventListener("input", updateCharacterCount);
  elements.prompt.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      generateCases();
    }
  });
  elements.profile.addEventListener("change", updateProfileUI);
  elements.generate.addEventListener("click", generateCases);
  elements.search.addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLocaleLowerCase();
    renderRows();
  });
  $("#select-all").addEventListener("click", () => setAllTechniques(true));
  $("#clear-all").addEventListener("click", () => setAllTechniques(false));
  $$(".sort-button").forEach((button) => button.addEventListener("click", () => changeSort(button.dataset.sort)));
  $("#copy-raw").addEventListener("click", () => copySelected("text", "Raw case copied"));
  $("#copy-encoded").addEventListener("click", () => copySelected("encoded", "Encoded case copied"));
  $("#close-inspection").addEventListener("click", closeInspection);
  elements.inspectionModal.addEventListener("click", (event) => {
    if (event.target === elements.inspectionModal) closeInspection();
  });
  $("#focus-results").addEventListener("click", toggleResultsFocus);
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key.toLocaleLowerCase() === "m") {
      event.preventDefault();
      toggleResultsFocus();
    } else if (event.key === "Escape" && (elements.inspectionModal.open || elements.helpModal.open)) {
      return;
    } else if (event.key === "Escape" && document.body.classList.contains("results-focus")) {
      toggleResultsFocus(false);
    }
  });
}

async function loadCatalog() {
  try {
    const response = await fetch("/api/catalog", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Unable to load the local catalog");
    state.catalog = await response.json();
    populateProfiles();
    populateTechniques();
    populateChains();
    enhanceSelects();
    populateHelp();
    updateProfileUI();
  } catch (error) {
    toast(error.message, true);
    elements.generate.disabled = true;
  }
}

function enhanceSelects() {
  $$('select:not([data-enhanced="true"])').forEach((select) => {
    select.dataset.enhanced = "true";
    select.classList.add("enhanced-select");

    const wrapper = document.createElement("div");
    wrapper.className = "custom-select";
    select.before(wrapper);
    wrapper.append(select);

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");

    const value = document.createElement("span");
    value.className = "select-value";
    const chevron = document.createElement("span");
    chevron.className = "select-chevron";
    chevron.setAttribute("aria-hidden", "true");
    trigger.append(value, chevron);

    const menu = document.createElement("div");
    menu.className = "select-menu";
    menu.role = "listbox";
    menu.hidden = true;
    const menuId = `${select.id}-menu`;
    menu.id = menuId;
    trigger.setAttribute("aria-controls", menuId);

    for (const option of select.options) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "select-option";
      item.role = "option";
      item.dataset.value = option.value;
      item.textContent = option.textContent;
      item.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        closeCustomSelect();
        trigger.focus();
      });
      item.addEventListener("keydown", (event) => navigateSelectOptions(event, menu, trigger));
      menu.append(item);
    }

    const sync = () => {
      const selected = select.selectedOptions[0];
      value.textContent = selected?.textContent || "Choose";
      trigger.setAttribute("aria-label", `${select.id.replaceAll("-", " ")}: ${value.textContent}`);
      menu.querySelectorAll(".select-option").forEach((item) => {
        const active = item.dataset.value === select.value;
        item.classList.toggle("selected", active);
        item.setAttribute("aria-selected", active ? "true" : "false");
      });
    };
    select.addEventListener("change", sync);
    sync();

    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (openCustomSelect?.wrapper === wrapper) closeCustomSelect();
      else openSelectMenu({ wrapper, trigger, menu });
    });
    trigger.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        if (openCustomSelect?.wrapper !== wrapper) openSelectMenu({ wrapper, trigger, menu });
        const options = [...menu.querySelectorAll(".select-option")];
        const selectedIndex = Math.max(0, options.findIndex((item) => item.classList.contains("selected")));
        const target = event.key === "End" ? options.at(-1) : event.key === "Home" ? options[0] : options[selectedIndex];
        target?.focus();
      }
    });
    wrapper.append(trigger, menu);
  });

  document.addEventListener("pointerdown", (event) => {
    if (openCustomSelect && !openCustomSelect.wrapper.contains(event.target)) closeCustomSelect();
  });
}

function openSelectMenu(parts) {
  closeCustomSelect();
  openCustomSelect = parts;
  parts.wrapper.classList.add("open");
  parts.trigger.setAttribute("aria-expanded", "true");
  parts.menu.hidden = false;
  const availableBelow = window.innerHeight - parts.trigger.getBoundingClientRect().bottom;
  parts.wrapper.classList.toggle("drop-up", availableBelow < Math.min(parts.menu.scrollHeight, 280) + 12);
}

function closeCustomSelect() {
  if (!openCustomSelect) return;
  openCustomSelect.wrapper.classList.remove("open", "drop-up");
  openCustomSelect.trigger.setAttribute("aria-expanded", "false");
  openCustomSelect.menu.hidden = true;
  openCustomSelect = null;
}

function navigateSelectOptions(event, menu, trigger) {
  const options = [...menu.querySelectorAll(".select-option")];
  const current = options.indexOf(event.currentTarget);
  if (event.key === "Escape") {
    event.preventDefault();
    closeCustomSelect();
    trigger.focus();
  } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? options.length - 1
        : (current + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    options[next]?.focus();
  }
}

function populateProfiles() {
  elements.profile.replaceChildren();
  for (const profile of state.catalog.profiles) {
    const option = document.createElement("option");
    option.value = profile.name;
    option.textContent = profile.label;
    elements.profile.append(option);
  }
  const custom = document.createElement("option");
  custom.value = "custom";
  custom.textContent = "Custom techniques";
  elements.profile.append(custom);
  const chain = document.createElement("option");
  chain.value = "custom_chain";
  chain.textContent = "Custom chain";
  elements.profile.append(chain);
}

function populateHelp() {
  const profileContainer = $("#help-profiles");
  profileContainer.replaceChildren();
  const profiles = [
    ...state.catalog.profiles.map((profile) => ({
      label: profile.label,
      description: profile.description,
      detail: `${profile.techniques.length} techniques · ${profile.min_chain_length === profile.max_chain_length ? profile.max_chain_length : `${profile.min_chain_length}–${profile.max_chain_length}`} transform${profile.max_chain_length === 1 ? "" : "s"} per case`,
    })),
    { label: "Custom Techniques", description: "Run only the techniques you select.", detail: "One transform per case" },
    { label: "Custom Chain", description: "Apply one exact ordered chain to every case.", detail: "Two or three selected transforms" },
  ];
  for (const profile of profiles) profileContainer.append(createHelpCard(profile.label, profile.description, profile.detail));

  const techniqueContainer = $("#help-techniques");
  techniqueContainer.replaceChildren();
  for (const technique of state.catalog.techniques) {
    techniqueContainer.append(createHelpCard(technique.label, technique.description));
  }
}

function createHelpCard(title, description, detail = "") {
  const card = document.createElement("article");
  const heading = document.createElement("strong");
  const copy = document.createElement("span");
  heading.textContent = title;
  copy.textContent = description;
  card.append(heading, copy);
  if (detail) {
    const metadata = document.createElement("small");
    metadata.textContent = detail;
    card.append(metadata);
  }
  return card;
}

function populateTechniques() {
  elements.techniqueGrid.replaceChildren();
  for (const technique of state.catalog.techniques) {
    const label = document.createElement("label");
    label.className = "technique-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = technique.name;
    checkbox.checked = true;
    checkbox.addEventListener("change", updateTechniqueSummary);
    const card = document.createElement("span");
    card.className = "technique-card";
    const check = document.createElement("span");
    check.className = "technique-check";
    check.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = technique.label;
    const description = document.createElement("small");
    description.textContent = technique.description;
    copy.append(title, description);
    card.append(check, copy);
    label.append(checkbox, card);
    elements.techniqueGrid.append(label);
  }
  updateTechniqueSummary();
}

function populateChains() {
  for (let step = 1; step <= 3; step += 1) {
    const select = $(`#chain-step-${step}`);
    const initialText = step === 3 ? "No third step" : "Choose technique";
    select.replaceChildren(new Option(initialText, ""));
    for (const technique of state.catalog.techniques) {
      select.append(new Option(technique.label, technique.name));
    }
  }
}

function updateProfileUI() {
  const value = elements.profile.value;
  const isCustom = value === "custom";
  const isChain = value === "custom_chain";
  elements.customTechniques.classList.toggle("visible", isCustom);
  elements.customChain.classList.toggle("visible", isChain);
  if (isCustom) {
    elements.customTechniques.open = true;
    elements.profileHint.textContent = "Generate single transforms from your selected technique set.";
  } else if (isChain) {
    elements.customChain.open = true;
    elements.profileHint.textContent = "Apply one exact ordered chain to every generated case.";
  } else {
    const profile = state.catalog?.profiles.find((item) => item.name === value);
    const range = profile && profile.min_chain_length !== profile.max_chain_length
      ? `${profile.min_chain_length}–${profile.max_chain_length} step chains`
      : profile?.min_chain_length > 1
        ? `${profile.min_chain_length} step chains`
        : "Single transformations";
    elements.profileHint.textContent = profile ? `${range} · ${profile.techniques.length} techniques.` : "Built-in profile.";
  }
}

function updateCharacterCount() {
  const count = [...elements.prompt.value].length;
  elements.characterCount.textContent = `${count.toLocaleString()} ${count === 1 ? "character" : "characters"}`;
}

function setAllTechniques(checked) {
  $$("#technique-grid input").forEach((input) => { input.checked = checked; });
  updateTechniqueSummary();
}

function updateTechniqueSummary() {
  const count = $$("#technique-grid input:checked").length;
  elements.selectionSummary.textContent = `${count} selected`;
}

function requestPayload() {
  const profile = elements.profile.value;
  const payload = {
    prompt: elements.prompt.value,
    profile,
    intensity: elements.intensity.value,
    count: Number(elements.count.value),
  };
  if (profile === "custom") {
    payload.techniques = $$("#technique-grid input:checked").map((input) => input.value);
  }
  if (profile === "custom_chain") {
    payload.chain = [$("#chain-step-1").value, $("#chain-step-2").value, $("#chain-step-3").value].filter(Boolean);
  }
  return payload;
}

async function generateCases() {
  if (!elements.prompt.value) {
    elements.prompt.focus();
    toast("Enter a source prompt first", true);
    return;
  }
  setLoading(true);
  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(requestPayload()),
    });
    const body = await readResponse(response);
    if (!response.ok) throw new Error(body.error || body.detail || "Generation failed");
    state.cases = body.cases;
    state.sortKey = "technique_label";
    state.sortDirection = 1;
    state.query = "";
    state.selectedId = null;
    elements.search.value = "";
    elements.search.disabled = !state.cases.length;
    elements.resultSubtitle.textContent = `${body.summary.cases} unique cases from ${body.summary.attempted} attempts.`;
    elements.runStatus.hidden = false;
    elements.runStatusText.textContent = `Audit · ${body.run_id}`;
    elements.runStatus.title = body.audit_path;
    updateSortIndicators();
    renderRows();
    renderInspection();
    $("#results-heading").scrollIntoView({ behavior: "smooth", block: "start" });
    toast(`Generated ${body.summary.cases} cases`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setLoading(false);
  }
}

async function readResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  return { error: await response.text() };
}

function setLoading(loading) {
  elements.generate.disabled = loading;
  elements.generate.classList.toggle("loading", loading);
  $(".button-label").textContent = loading ? "Generating…" : "Generate cases";
  elements.loading.hidden = !loading;
  if (loading) elements.empty.hidden = true;
  else if (!state.cases.length) elements.empty.hidden = false;
}

function changeSort(key) {
  if (state.sortKey === key) state.sortDirection *= -1;
  else {
    state.sortKey = key;
    state.sortDirection = 1;
  }
  updateSortIndicators();
  renderRows();
}

function updateSortIndicators() {
  $$(".sort-button").forEach((button) => {
    const active = button.dataset.sort === state.sortKey;
    button.classList.toggle("active", active);
    button.querySelector("span").textContent = active ? (state.sortDirection === 1 ? "↑" : "↓") : "";
  });
}

function visibleCases() {
  const filtered = state.query
    ? state.cases.filter((item) => [item.short_id, item.technique_label, item.escaped].some((value) => value.toLocaleLowerCase().includes(state.query)))
    : [...state.cases];
  return filtered.sort((left, right) => {
    const a = String(left[state.sortKey]);
    const b = String(right[state.sortKey]);
    return a.localeCompare(b, undefined, { sensitivity: "base" }) * state.sortDirection;
  });
}

function renderRows() {
  const cases = visibleCases();
  elements.rows.replaceChildren();
  for (const item of cases) {
    const row = document.createElement("tr");
    row.tabIndex = 0;
    row.dataset.id = item.id;
    row.classList.toggle("selected", item.id === state.selectedId);
    row.setAttribute("aria-selected", item.id === state.selectedId ? "true" : "false");
    row.addEventListener("click", () => selectCase(item.id));
    row.addEventListener("keydown", (event) => {
      if (event.target.closest("button")) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectCase(item.id);
      }
    });
    for (const value of [item.technique_label, item.escaped]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      cell.title = value;
      row.append(cell);
    }
    const actionCell = document.createElement("td");
    actionCell.className = "row-action-cell";
    actionCell.append(
      createRowCopyButton(item, "Copy raw", "text", "raw text"),
      createRowCopyButton(item, "Copy encoded", "encoded", "encoded text"),
    );
    row.append(actionCell);
    elements.rows.append(row);
  }
  elements.empty.hidden = state.cases.length > 0;
  $("#filter-empty-state").hidden = !(state.cases.length > 0 && cases.length === 0);
  elements.countBadge.textContent = state.query ? `${cases.length} of ${state.cases.length}` : `${state.cases.length} ${state.cases.length === 1 ? "case" : "cases"}`;
}

function createRowCopyButton(item, label, field, description) {
  const button = document.createElement("button");
  button.className = "row-copy-button";
  button.type = "button";
  button.textContent = label;
  button.title = `${label} for ${item.short_id}`;
  button.setAttribute("aria-label", `${label} for ${item.short_id}`);
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    try {
      await copyText(item[field]);
      toast(`${item.short_id} ${description} copied`);
    } catch (error) {
      toast(`Clipboard unavailable: ${error.message}`, true);
    }
  });
  return button;
}

function selectCase(id) {
  state.selectedId = id;
  $$("#case-rows tr").forEach((row) => {
    const selected = row.dataset.id === id;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-selected", selected ? "true" : "false");
  });
  renderInspection();
  if (!elements.inspectionModal.open) elements.inspectionModal.showModal();
}

function closeInspection() {
  if (elements.inspectionModal.open) elements.inspectionModal.close();
}

function selectedCase() {
  return state.cases.find((item) => item.id === state.selectedId);
}

function renderInspection() {
  const item = selectedCase();
  if (!item) return;
  $("#inspection-heading").textContent = item.short_id;
  $("#technique-badge").textContent = item.technique_label;
  $("#rendered-value").textContent = item.text;
  $("#encoded-value").textContent = item.encoded;
  $("#changed-positions").textContent = item.changed_positions.length ? item.changed_positions.join(", ") : "None";
  $("#variant-value").textContent = item.parameters.variant || summarizeSteps(item.parameters.steps) || "—";
  const list = $("#code-point-list");
  list.replaceChildren();
  if (!item.code_points.length) {
    const empty = document.createElement("p");
    empty.className = "no-code-points";
    empty.textContent = "No non-ASCII or invisible code points.";
    list.append(empty);
  } else {
    for (const point of item.code_points) {
      const row = document.createElement("div");
      row.className = "code-point-row";
      for (const value of [point.value, point.name, point.category]) {
        const cell = document.createElement("span");
        cell.textContent = value;
        row.append(cell);
      }
      list.append(row);
    }
  }
  $(".inspection-scroll").scrollTo({ top: 0 });
}

function summarizeSteps(steps) {
  if (!Array.isArray(steps)) return "";
  const variants = steps.map((step) => step.variant).filter(Boolean);
  return variants.join(" → ");
}

async function copySelected(field, message) {
  const item = selectedCase();
  if (!item) return;
  try {
    await copyText(item[field]);
    toast(message);
  } catch (error) {
    toast(`Clipboard unavailable: ${error.message}`, true);
  }
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.className = "clipboard-fallback";
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("Browser denied clipboard access");
}

function toast(message, error = false) {
  const item = document.createElement("div");
  item.className = `toast${error ? " error" : ""}`;
  item.textContent = message;
  $("#toast-region").append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function toggleResultsFocus(force) {
  const enabled = typeof force === "boolean"
    ? force
    : !document.body.classList.contains("results-focus");
  document.body.classList.toggle("results-focus", enabled);
  const button = $("#focus-results");
  button.querySelector("span").textContent = enabled ? "Exit focus" : "Focus";
  button.title = enabled ? "Exit focus (Ctrl+M or Esc)" : "Focus results (Ctrl+M)";
}
