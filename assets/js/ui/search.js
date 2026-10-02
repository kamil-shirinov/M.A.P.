const MAX_RESULTS = 40;

export function mountSearch(host, { universe, onSelect, initial }) {
  host.innerHTML = "";
  const input = document.createElement("input");
  input.type = "search";
  input.placeholder = "Search ticker or company";
  input.setAttribute("aria-label", "Search ticker or company");
  input.autocomplete = "off";
  input.value = initial || "";

  const list = document.createElement("ul");
  list.className = "search-results";
  list.setAttribute("role", "listbox");

  let matches = [];
  let cursor = -1;

  function close() { matches = []; cursor = -1; list.innerHTML = ""; }

  function draw() {
    list.innerHTML = "";
    matches.forEach((row, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === cursor));

      const sym = document.createElement("span");
      sym.className = "sym" + (row.synthetic ? " synthetic" : "");
      sym.textContent = row.symbol;

      const nm = document.createElement("span");
      nm.className = "nm";
      nm.textContent = row.name;

      const ex = document.createElement("span");
      ex.className = "ex";
      ex.textContent = row.exchange;

      li.append(sym, nm, ex);
      li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(row); });
      list.append(li);
    });
  }

  function pick(row) {
    input.value = row.symbol;
    close();
    onSelect(row);
  }

  function search(q) {
    const term = q.trim().toUpperCase();
    if (!term) return close();
    const starts = [], contains = [];
    for (const row of universe) {
      if (row.symbol.startsWith(term)) starts.push(row);
      else if (row.symbol.includes(term) || row.name.toUpperCase().includes(term)) contains.push(row);
      if (starts.length >= MAX_RESULTS) break;
    }
    matches = [...starts, ...contains].slice(0, MAX_RESULTS);
    cursor = matches.length ? 0 : -1;
    draw();
  }

  input.addEventListener("input", () => search(input.value));
  input.addEventListener("focus", () => search(input.value));
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (e) => {
    if (!matches.length) return;
    if (e.key === "ArrowDown") { cursor = (cursor + 1) % matches.length; draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { cursor = (cursor - 1 + matches.length) % matches.length; draw(); e.preventDefault(); }
    else if (e.key === "Enter" && cursor >= 0) { pick(matches[cursor]); e.preventDefault(); }
    else if (e.key === "Escape") close();
  });

  host.append(input, list);
  return { focus: () => input.focus() };
}
