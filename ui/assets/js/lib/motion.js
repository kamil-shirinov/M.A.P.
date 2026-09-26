/* Entrance motion, and the three guarantees that keep it from hiding anything.

   The entrance styles in system.css are written so that their HIDDEN state is
   the exception, not the default. `.enter-row` on its own does nothing at all;
   the animation only applies under `:root[data-enter]`, and only inside a
   `prefers-reduced-motion: no-preference` query. So:

     no JavaScript     the attribute is never set, the rules never match,
                       everything is at its final value in the first frame
     reduced motion    `arm()` declines to set it, AND the media query removes
                       the rules even if something else set it
     changed mid-visit the media query re-evaluates live and the rules stop
                       matching, so nothing can be caught part-way and stranded

   The third is why the query wraps the rules rather than the script merely
   checking once at boot. A boot-time check cannot react to the setting being
   turned on while the page is open.

   `arm()` is also called inline from each document's <head>, before first paint,
   so an entrance does not flash its end state and then restart. */

const QUERY = "(prefers-reduced-motion: reduce)";

/** True when the visitor has asked for less movement. Safe where matchMedia is
    missing: an environment that cannot answer is treated as having asked. */
export function prefersReducedMotion() {
  if (typeof matchMedia !== "function") return true;
  try {
    return matchMedia(QUERY).matches;
  } catch {
    return true;
  }
}

/** Arm the entrance styles for this page load. Idempotent. */
export function arm(root = document.documentElement) {
  if (prefersReducedMotion()) return false;
  root.dataset.enter = "";
  return true;
}

/* Rows stagger 20ms apart, and stop staggering at 20. Past that the delay is
   longer than anyone waits and a reader scrolling fast meets rows that have not
   started yet — so row 21 onward simply appears. */
const STEP_MS = 20;
const MAX_STAGGERED = 20;

/** Give each element its entrance class and its place in the stagger.

    Delays are set as inline `animation-delay` rather than as nth-child rules
    because the lists are built in JavaScript and their lengths are data. */
export function stagger(elements, className = "enter-row", { step = STEP_MS, cap = MAX_STAGGERED } = {}) {
  [...elements].forEach((el, i) => {
    el.classList?.add(className);
    // Decoration must never be able to break a render. A node without `style`
    // is an environment that cannot animate anyway — the test DOM, a document
    // fragment — and the right response is to skip the delay, not to throw
    // halfway through appending a list of rows.
    if (i < cap && i > 0 && el.style) el.style.animationDelay = `${i * step}ms`;
  });
}

/** A line that draws itself. Returns the length so a caller can chain to it.

    Reads its own length from the path, because a dash offset has to be in user
    units and no constant is right for two different charts. When motion is not
    allowed the path is left exactly as it was — no dasharray, no offset — which
    is a complete line rather than a line waiting to be completed. */
export function draw(path, { duration } = {}) {
  if (prefersReducedMotion()) return 0;
  /* getTotalLength() THROWS on an element that is not rendered — a path still
     detached from the document, or one inside `display: none`. Motion is
     decoration and must never be able to break a chart, so a failure here means
     the line simply stays drawn, which is the correct end state anyway. */
  let length = 0;
  try {
    length = typeof path.getTotalLength === "function" ? path.getTotalLength() : 0;
  } catch {
    return 0;
  }
  if (!length) return 0;
  path.style.setProperty("--draw-length", String(length));
  if (duration) path.style.setProperty("--draw-dur", `${duration}ms`);
  path.classList.add("enter-draw");
  return length;
}
