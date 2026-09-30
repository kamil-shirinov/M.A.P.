/* The ground: an engraved guilloche that slowly shifts, behind every page.

   It used to be SVG, fifteen fixed rings in three groups that each swung a few
   degrees on a slow CSS rotation. Rigid groups turning cannot morph — the lines
   themselves never changed shape — and at a few degrees a minute the figure read
   as still. So it is drawn afresh each frame on a canvas instead, from the same
   rose-modulated rings, with three slow things happening at once:

     morph   each ring's phase drifts at its own rate, so the interference
             between neighbouring rings — which is what draws the pattern —
             keeps moving, the way a banknote's guilloche shifts as it tilts
     breathe the modulation depth rises and falls a little, out of step
             ring to ring
     turn    the whole figure rotates, about a degree every two seconds

   All of it is slow enough that no single line reads as moving while the
   pattern visibly does. It is decoration: it never takes layout (the canvas
   fills a box that is already out of flow), it stops when it is off screen or
   the tab is hidden, and with reduced motion it draws one still frame and asks
   for no more. Where there is no canvas it falls back to the SVG figure. */

import { prefersReducedMotion } from "../lib/motion.js";
import { mountRosette } from "./rosette.js";

const SAMPLES = 240;
const RINGS = 15;
const MAX_R = 470;
const INNER = 0.22;
const LOBES = 7;
const HARMONIC = 11;
const AMPLITUDE = 0.1;
const TWIST = 2.4;
// Radians per second. Chosen so a lobe at the rim travels a few pixels a
// second: visible within a breath, never quick.
const DRIFT = 0.07;
const TURN = 0.009;
const BREATHE = 0.11;

/** The radius of ring `i` at angle `th` and time `t`, as a multiple of its base.

    Exported so the motion can be tested without a canvas: it is the whole of
    what changes from frame to frame. */
export function modulation(i, th, t) {
  const k = i / (RINGS - 1);
  const phase = TWIST * k * Math.PI * 2 + DRIFT * t * (1 + 0.35 * k);
  const depth = AMPLITUDE * (1 + 0.18 * Math.sin(BREATHE * t + i * 0.4));
  return 1 + depth * Math.cos(LOBES * th + phase) + depth * 0.45 * Math.cos(HARMONIC * th - phase * 1.7);
}

function ink(host) {
  try {
    const value = getComputedStyle(host).getPropertyValue("--rosette-ink").trim();
    return value || "#262d38";
  } catch {
    return "#262d38";
  }
}

/** Mount the ground into `host`. `weight` is the figure's opacity. Returns a
    handle whose `stop()` ends the loop (used by tests and never by pages). */
export function mountGround(host, { weight = 0.5 } = {}) {
  const canvas = document.createElement("canvas");
  const ctx = typeof canvas.getContext === "function" ? canvas.getContext("2d") : null;
  if (!ctx) {
    // No canvas: the SVG figure, which drifts on its CSS rotation.
    return { canvas: null, svg: mountRosette(host, { opacity: weight }), stop() {} };
  }
  canvas.className = "ground-canvas";
  canvas.setAttribute("aria-hidden", "true");
  host.append(canvas);

  const cos = new Float64Array(SAMPLES + 1);
  const sin = new Float64Array(SAMPLES + 1);
  for (let s = 0; s <= SAMPLES; s++) {
    const th = (s / SAMPLES) * Math.PI * 2;
    cos[s] = Math.cos(th);
    sin[s] = Math.sin(th);
  }

  let size = 0;
  let stroke = ink(host);
  const fit = () => {
    const box = host.getBoundingClientRect?.();
    // Capped at 1.5: the lines are a faint texture, and a 2x backing store is
    // nearly twice the pixels to redraw every frame for no visible gain.
    const ratio = Math.min(1.5, globalThis.devicePixelRatio || 1);
    const next = Math.max(1, Math.round((box?.width || 1000) * ratio));
    if (next !== size) {
      size = next;
      canvas.width = size;
      canvas.height = size;
      // Read here rather than per frame: a computed-style read each frame would
      // ask for style work sixty times a second to learn nothing new.
      stroke = ink(host);
    }
  };

  const draw = (t) => {
    const scale = size / 1000;
    const c = size / 2;
    const turn = TURN * t;
    ctx.clearRect(0, 0, size, size);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = Math.max(0.7, 0.7 * scale * 1.4);
    ctx.lineJoin = "round";
    ctx.globalAlpha = weight;
    const rc = Math.cos(turn);
    const rs = Math.sin(turn);
    for (let i = 0; i < RINGS; i++) {
      const R = MAX_R * (INNER + (1 - INNER) * (i / (RINGS - 1))) * scale;
      ctx.beginPath();
      for (let s = 0; s <= SAMPLES; s++) {
        const th = (s / SAMPLES) * Math.PI * 2;
        const r = R * modulation(i, th, t);
        const x = r * cos[s];
        const y = r * sin[s];
        const px = c + x * rc - y * rs;
        const py = c + x * rs + y * rc;
        if (s === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // The fade at the rim is a CSS mask on the canvas (system.css), applied by
    // the compositor. Painting it here meant a full-canvas gradient fill every
    // frame, which was most of the cost and held a headless browser to 20 fps.
  };

  // Begin part-way into the drift, so the first frame is not a rest position.
  const OFFSET = 37;
  let frame = null;
  let visible = true;
  let start = null;
  const loop = (now) => {
    frame = null;
    if (start === null) start = now;
    fit();
    draw(OFFSET + (now - start) / 1000);
    schedule();
  };
  const schedule = () => {
    if (frame !== null || !visible || prefersReducedMotion()) return;
    if (typeof requestAnimationFrame !== "function") return;
    frame = requestAnimationFrame(loop);
  };
  const halt = () => {
    if (frame !== null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(frame);
    frame = null;
  };

  fit();
  draw(OFFSET);
  schedule();

  // Off screen, nothing is drawn: the figure sits at the top of long pages.
  if (typeof IntersectionObserver === "function") {
    new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) schedule();
      else halt();
    }).observe(host);
  }
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(() => { fit(); if (frame === null) draw(OFFSET); }).observe(host);
  }
  // A visitor who turns reduced motion on mid-visit gets a still figure at once;
  // turning it off starts the drift again.
  try {
    matchMedia("(prefers-reduced-motion: reduce)").addEventListener?.("change", () => {
      if (prefersReducedMotion()) halt();
      else schedule();
    });
  } catch { /* no matchMedia: prefersReducedMotion already treats that as asked */ }

  return { canvas, svg: null, stop: halt };
}
