/* A run in progress: a rosette that engraves itself, one ring per stage.

   EVERY RING IS AN EVENT THE RUN RECORDED. The server reads each stage off the
   run's own `trace.jsonl` as the agent finishes and streams it here; a ring is
   engraved when that event arrives and at no other time. Nothing is timed,
   estimated or interpolated. There is no percentage, because the run does not
   know one — the analyst stage alone is most of the wait and says nothing until
   it is done.

   THE RING IN PROGRESS IS ALIVE, NOT MEASURED. A short bright trace runs slowly
   round it, forever, at one speed. It says "this is the stage being worked on",
   which is true, and nothing about how far through it the run is, which nobody
   knows. With reduced motion it stands still as a dashed ring.

   The clock is elapsed time, beside the usual range the server measured from
   recorded runs. It counts up from when Analyse was pressed; it never counts
   down, because a countdown would be a promise. */

import { chromeText } from "../lib/figure.js";
import { prefersReducedMotion } from "../lib/motion.js";
import { ringPath } from "./rosette.js";

const SVG = "http://www.w3.org/2000/svg";
const STAGES = ["intake", "analyst", "structuralist"];
const WORDS = { intake: "Intake", analyst: "Analyst", structuralist: "Structuralist" };
const DOING = { intake: "reading the filing", analyst: "reasoning through three scenarios", structuralist: "writing them as numbers" };

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const svgNode = (tag, attrs) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs ?? {})) node.setAttribute(k, String(v));
  return node;
};

/* What to expect, as a RANGE. A single median reads as a promise, and the middle
   eighty percent of recorded runs spans six to twelve minutes. The server
   measures both from `elapsed_s` in the ledger and sends them. */
export function expected(event) {
  const mins = (s) => Math.round(s / 60);
  const span = event.usual_range_seconds;
  if (Array.isArray(span) && span.length === 2) {
    return `usually ${mins(span[0])} to ${mins(span[1])} minutes`;
  }
  return `usually about ${mins(event.typical_seconds)} minutes`;
}

/** Elapsed time as a reader says it: 0:07, 4:12, 11:03. */
export function clock(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** One ring per stage, inner first, each drawn as three close guilloche lines so
    it reads as engraved rather than as a circle. */
function rosette(stages) {
  const svg = svgNode("svg", { viewBox: "0 0 1000 1000", class: "anl-rosette", "aria-hidden": "true", focusable: "false" });
  const rings = new Map();
  stages.forEach((stage, i) => {
    const R = 170 + i * (260 / Math.max(stages.length - 1, 1));
    const group = svgNode("g", { class: "anl-ring" });
    group.dataset.stage = stage;
    group.dataset.state = "waiting";
    const lines = [-16, 0, 16].map((offset, k) =>
      svgNode("path", {
        d: ringPath(R + offset, (i * 0.9 + k * 0.35) * Math.PI, { lobes: 7 + i * 2, harmonic: 11 + i * 2, amplitude: 0.05 }),
        class: "anl-ring-line",
      }),
    );
    // The trace rides the middle line. It exists from the start and is shown
    // only while its ring is the one in progress.
    const trace = svgNode("path", { d: lines[1].getAttribute?.("d") ?? "", class: "anl-ring-trace" });
    group.append(...lines, trace);
    svg.append(group);
    rings.set(stage, { group, lines, trace });
  });
  return { svg, rings };
}

/** Give a path its own length as a custom property, so the engraving and the
    trace are sized to it. Decoration: a path that cannot measure itself — not
    yet rendered, or no layout at all — simply keeps its plain stroke. */
function measure(path) {
  try {
    const length = typeof path.getTotalLength === "function" ? path.getTotalLength() : 0;
    if (length) path.style.setProperty("--len", String(length));
    return length;
  } catch {
    return 0;
  }
}

export function createProgress(host, { ticker }) {
  host.textContent = "";
  const box = el("div", "anl-progress");
  const side = el("div", "anl-progress-side");
  const head = el("p", "anl-progress-head");
  head.append(chromeText(`Asking for ${ticker}…`, "what the page is doing"));
  const list = el("ol", "anl-stages");
  const time = el("p", "anl-clock");
  const notes = el("div", "anl-notes");
  side.append(head, list, time, notes);
  // The rosette's place, held from the start so nothing moves when it arrives.
  const art = el("div", "anl-progress-art");
  box.append(art, side);
  host.append(box);

  const started = Date.now();
  let stages = STAGES;
  let figure = null;
  let range = "";
  let ticking = null;
  const done = new Set();
  let current = null;

  const note = (text, why) => {
    const line = el("p", "anl-note");
    line.append(chromeText(text, why));
    notes.append(line);
  };

  const paintClock = (final = false) => {
    time.textContent = "";
    time.append(chromeText(
      `${final ? "took " : ""}${clock(Date.now() - started)}${final ? "" : " elapsed"}${range ? ` · ${range}` : ""}`,
      "time since Analyse was pressed, beside the usual range of recorded runs",
    ));
  };

  const paintList = () => {
    list.textContent = "";
    for (const stage of stages) {
      const state = done.has(stage) ? "done" : stage === current ? "running" : "waiting";
      const item = el("li", "anl-stage");
      item.dataset.state = state;
      item.append(chromeText(WORDS[stage] ?? stage, "a stage of the run"));
      const status = el("span", "anl-stage-state",
        state === "done" ? " — done" : state === "running" ? ` — ${DOING[stage] ?? "in progress"}` : "");
      item.append(status);
      list.append(item);
    }
  };

  const setRing = (stage, state) => {
    const ring = figure?.rings.get(stage);
    if (!ring) return;
    ring.group.dataset.state = state;
    if (state === "running") measure(ring.trace);
    if (state === "done") {
      // Engraved once, when the run says so; with reduced motion, simply drawn.
      for (const line of ring.lines) {
        if (!prefersReducedMotion() && measure(line)) line.classList?.add("engrave");
      }
    }
  };

  const advance = () => {
    current = stages.find((s) => !done.has(s)) ?? null;
    if (current) setRing(current, "running");
    paintList();
  };

  paintClock();
  ticking = typeof setInterval === "function" ? setInterval(() => paintClock(), 1000) : null;
  // Outside a browser the interval must not keep a process alive on its own.
  ticking?.unref?.();
  const stop = () => {
    if (ticking !== null) clearInterval(ticking);
    ticking = null;
  };

  return {
    update(event) {
      if (event.event === "started") {
        stages = Array.isArray(event.stages) && event.stages.length ? event.stages : STAGES;
        figure = rosette(stages);
        art.append(figure.svg);
        range = expected(event);
        head.textContent = "";
        head.append(chromeText(`Running ${event.ticker} over ${event.horizon_days} sessions.`, "the run's subject"));
        if (event.replay) {
          /* Said on the page, not only in the terminal. A development server
             replaying a recorded run must not be mistaken for a run. */
          const pace = Number(event.replay.speed) === 1
            ? "at its recorded pace"
            : `${event.replay.speed}× faster than it ran`;
          note(
            `Replaying recorded run ${String(event.replay.run_id).slice(0, 8)} — its own trace, ${pace}. ` +
              "Nothing is being computed.",
            "this server replays a recorded run",
          );
        }
        advance();
        paintClock();
      } else if (event.event === "filing") {
        if (event.filed) {
          note(`Reading the earnings 8-K filed ${event.filed} (${event.accession}).`, "which filing the run reads");
        }
      } else if (event.event === "progress") {
        setRing(event.stage, "done");
        done.add(event.stage);
        if (event.detail === "cached") note(`${WORDS[event.stage] ?? event.stage}: answered from the cache.`, "a stage read from the cache");
        advance();
      } else if (event.event === "failed") {
        stop();
        if (current) setRing(current, "stopped");
        current = null;
        paintList();
        note(`The run did not finish: ${event.why}`, "why the run stopped");
        paintClock(true);
      } else if (event.event === "result") {
        stop();
        for (const stage of stages) if (!done.has(stage)) { setRing(stage, "done"); done.add(stage); }
        current = null;
        paintList();
        paintClock(true);
      }
    },
    finish() {
      stop();
    },
  };
}
