/* Every text node containing a digit must sit inside [data-prov] (a figure) or
   [data-chrome] (positively marked as not a figure). There are NO heuristics
   here on purpose: "skip things shaped like a date" is how a real value
   formatted as 2026.07 passes unnoticed. If it has digits, it is marked or it
   is a violation. */

const DIGIT = /\d/;

export function auditUnmarkedNumbers(root = document.body) {
  const violations = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!DIGIT.test(node.nodeValue)) continue;
    if (!node.parentElement) continue;
    if (node.parentElement.closest("[data-prov], [data-chrome], [data-audit-exempt]")) continue;
    violations.push({ text: node.nodeValue.trim(), element: node.parentElement });
  }
  return violations;
}

/** Run after every render. Marks offenders in the page and shouts in console,
    so forgetting becomes a visible failure on the next paint. */
export function enforce(root = document.body) {
  document.querySelectorAll(".prov-violation").forEach((el) => el.classList.remove("prov-violation"));
  document.querySelector(".audit-alarm")?.remove();

  const violations = auditUnmarkedNumbers(root);
  if (!violations.length) return violations;

  violations.forEach((v) => v.element.classList.add("prov-violation"));
  const alarm = document.createElement("div");
  alarm.className = "audit-alarm";
  alarm.dataset.auditExempt = "the alarm reports the count of violations";
  alarm.textContent =
    `${violations.length} unmarked number(s) on screen — mark as a figure or as chrome`;
  document.body.appendChild(alarm);
  console.error("[provenance] unmarked numbers:", violations);
  return violations;
}

/** Page-level rule: if ANY figure on the page is fabricated, the banner and the
    chart watermark both show. Per-figure marking handles the figure; the page
    needs its own state, because the realistic crop is one region, not the page. */
export function applyPageProvenance(root = document.body) {
  const anyFabricated = !!root.querySelector('[data-prov="fabricated"]');
  document.body.dataset.pageProv = anyFabricated ? "fabricated" : "measured";
  return anyFabricated;
}
