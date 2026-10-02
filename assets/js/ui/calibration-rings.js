/* The loading rings: one per agent, calibrating while it works.

   ONE RING PER AGENT, inner to outer in the order they run — intake, analyst,
   structuralist. Each is three wavy circles close together, so it reads as an
   engraved band rather than a line.

   WHILE ITS AGENT WORKS, the ring's circles turn against each other, alternate
   ones in opposite directions: three seconds turning, three seconds held, three
   seconds turning back with every direction reversed, three seconds held, and
   again. A dial being set. The cycle is the same every time; it never speeds up,
   slows down or fills. It says an agent is at work, which is true, and nothing
   about how far through it is, which nobody knows.

   WHEN THE TRACE REPORTS THAT AGENT FINISHED — and at no other time — its
   circles ease into one flat circle that glows, and stay that way. Three glowing
   circles are a finished run.

   Reduced motion: nothing turns, and a ring becomes its glowing circle at once
   when its agent finishes. The loop runs only while a ring is turning or
   settling, and stops by itself when none is. */

import { prefersReducedMotion } from "../lib/motion.js";
import { ringPath } from "./rosette.js";

const SVG = "http://www.w3.org/2000/svg";
const CENTRE = "500 500";

/** Seconds per turn, and per hold. */
export const TURN_SECONDS = 3;
/** How far a circle turns in one: a fifth of a revolution in three seconds. */
export const SWING_DEGREES = 72;
/** How long a finished ring takes to settle into its flat circle. */
export const SETTLE_MS = 1200;

// The three circles of a ring sit this far apart, and turn these ways.
const OFFSETS = [-16, 0, 16];
const DIRECTIONS = [1, -1, 1];
const AMPLITUDE = 0.05;

let glowIds = 0;

const node = (tag, attrs) => {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs ?? {})) n.setAttribute(k, String(v));
  return n;
};

const ease = (x) => (1 - Math.cos(Math.PI * Math.min(1, Math.max(0, x)))) / 2;

/** The turn, in degrees, of a circle whose direction is +1, `seconds` after its
    agent began: out to SWING over three seconds, held for three, back to zero
    over three, held for three, and repeat. Eased at each end of a turn, so a
    circle starts and stops rather than jumping. */
export function swing(seconds) {
  const cycle = TURN_SECONDS * 4;
  const u = ((seconds % cycle) + cycle) % cycle;
  if (u < TURN_SECONDS) return SWING_DEGREES * ease(u / TURN_SECONDS);
  if (u < 2 * TURN_SECONDS) return SWING_DEGREES;
  if (u < 3 * TURN_SECONDS) return SWING_DEGREES * (1 - ease((u - 2 * TURN_SECONDS) / TURN_SECONDS));
  return 0;
}

/** Ring `i`'s geometry: the analyst's ring sits between the other two. */
function geometry(i, count) {
  return {
    R: 170 + i * (260 / Math.max(count - 1, 1)),
    lobes: 7 + i * 2,
    harmonic: 11 + i * 2,
    phase: (k) => (i * 0.9 + k * 0.35) * Math.PI,
  };
}

/** Circle `k` of a ring, `wavy` of the way from its flat circle (0) to its full
    engraved shape (1). At 0 every circle of the ring is the same flat circle. */
export function shape(g, k, wavy) {
  return ringPath(g.R + OFFSETS[k] * wavy, g.phase(k), {
    lobes: g.lobes,
    harmonic: g.harmonic,
    amplitude: AMPLITUDE * wavy,
  });
}

const rotate = (line, degrees) => line.setAttribute("transform", `rotate(${degrees.toFixed(2)} ${CENTRE})`);

export function createRings(stages) {
  const glow = `anl-glow-${++glowIds}`;
  const svg = node("svg", { viewBox: "0 0 1000 1000", class: "anl-rosette", "aria-hidden": "true", focusable: "false" });
  // The glow is the circle's own stroke, blurred behind it: white on the dark
  // theme, ink on the light one, set by `--ring-glow`.
  const defs = node("defs");
  const filter = node("filter", { id: glow, x: "-15%", y: "-15%", width: "130%", height: "130%" });
  const blur = node("feGaussianBlur", { in: "SourceGraphic", stdDeviation: "10", result: "halo" });
  const merge = node("feMerge");
  merge.append(node("feMergeNode", { in: "halo" }), node("feMergeNode", { in: "halo" }), node("feMergeNode", { in: "SourceGraphic" }));
  filter.append(blur, merge);
  defs.append(filter);
  svg.append(defs);

  const rings = new Map();
  stages.forEach((stage, i) => {
    const g = geometry(i, stages.length);
    const group = node("g", { class: "anl-ring" });
    group.dataset.stage = stage;
    group.dataset.state = "waiting";
    const lines = OFFSETS.map((_offset, k) => node("path", { d: shape(g, k, 1), class: "anl-ring-line" }));
    group.append(...lines);
    svg.append(group);
    rings.set(stage, { group, lines, g, motion: "still", since: null, angles: [0, 0, 0], from: [0, 0, 0] });
  });

  let frame = null;

  const flatten = (ring) => {
    ring.lines.forEach((line, k) => {
      line.setAttribute("d", shape(ring.g, k, 0));
      rotate(line, 0);
    });
    ring.motion = "still";
  };

  const paint = (t) => {
    frame = null;
    let busy = false;
    for (const ring of rings.values()) {
      if (ring.motion === "turning") {
        ring.since ??= t;
        const a = swing((t - ring.since) / 1000);
        ring.lines.forEach((line, k) => {
          ring.angles[k] = DIRECTIONS[k] * a;
          rotate(line, ring.angles[k]);
        });
        busy = true;
      } else if (ring.motion === "settling") {
        ring.since ??= t;
        const p = Math.min(1, (t - ring.since) / SETTLE_MS);
        const wavy = 1 - ease(p);
        ring.lines.forEach((line, k) => {
          line.setAttribute("d", shape(ring.g, k, wavy));
          rotate(line, ring.from[k] * wavy);
        });
        if (p >= 1) flatten(ring);
        else busy = true;
      }
    }
    if (busy) schedule();
  };

  const schedule = () => {
    if (frame !== null || typeof requestAnimationFrame !== "function") return;
    frame = requestAnimationFrame(paint);
  };

  return {
    svg,
    /** Mark a stage `running`, `done` or `stopped`, as the run's events say. */
    set(stage, state) {
      const ring = rings.get(stage);
      if (!ring) return;
      ring.group.dataset.state = state;
      const still = prefersReducedMotion();
      if (state === "running") {
        ring.motion = still ? "still" : "turning";
        ring.since = null;
      } else if (state === "done") {
        ring.group.setAttribute("filter", `url(#${glow})`);
        if (still) {
          flatten(ring);
        } else {
          ring.from = [...ring.angles];
          ring.motion = "settling";
          ring.since = null;
        }
      } else {
        // Stopped where it stands: the run failed, and nothing is at work.
        ring.motion = "still";
      }
      if (!still) schedule();
    },
  };
}
