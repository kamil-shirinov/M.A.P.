/* Engine-turned rosette — the ground the front door sits on.

   Layered rose-modulated circles whose phase drifts ring to ring, so the
   interference between rings does the drawing rather than any single line.
   Rings are dealt round-robin into three bands; the bands swing a few degrees
   against each other on different periods (see front-door.css), which is what
   makes the moire move while no individual line reads as animated.

   Parametric on purpose: a later variation can mark a state — an uncalibrated
   band, a held-out split — by lifting `accentEvery` and `accentStroke` rather
   than being redrawn. No dependencies, no data, nothing to fetch. */

const SVG = "http://www.w3.org/2000/svg";
const SAMPLES = 260;
const CX = 500;
const CY = 500;
const MAX_R = 470;

const node = (tag, attrs) => {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs ?? {})) n.setAttribute(k, v);
  return n;
};

/** One closed ring: a circle of radius R modulated by two cosines, the second
    at a higher frequency and counter-phased. Returns an SVG path `d`. */
function ringPath(R, phase, { lobes, harmonic, amplitude }) {
  let d = "";
  for (let s = 0; s <= SAMPLES; s++) {
    const th = (s / SAMPLES) * Math.PI * 2;
    const m =
      1 +
      amplitude * Math.cos(lobes * th + phase) +
      amplitude * 0.45 * Math.cos(harmonic * th - phase * 1.7);
    d += (s === 0 ? "M" : "L") +
      (CX + R * m * Math.cos(th)).toFixed(1) + " " +
      (CY + R * m * Math.sin(th)).toFixed(1);
  }
  return d + "Z";
}

const DEFAULTS = {
  ringCount: 15,
  lobes: 7,
  harmonic: 11,
  amplitude: 0.1,
  twist: 2.4,
  innerRadius: 0.22,
  stroke: "#262d38",
  accentStroke: null,   // falls back to `stroke`
  accentEvery: 0,       // 0 = no marked rings
  opacity: 0.7,
  drift: true,
};

/** The figure behind an inner screen: the door's, at half weight and still.

    Same geometry and the SAME STROKE as the door. The shared-system spec gave
    #2c333f against the door's #262d38, but it also says "the same parameters as
    the door", and the two cannot both hold. Matching the door costs nothing
    visible — over `--paper`, #2c333f at .35 resolves to rgb(22,26,32) and
    #262d38 at .35 to rgb(20,24,30), a difference of two levels — and it keeps
    one figure rather than two that are nearly the same.

    `drift: false` because this one never moves. On the door the drift IS the
    thing; behind a table it is a distraction with no off switch. */
export function mountPageRosette(host, options = {}) {
  return mountRosette(host, { opacity: 0.35, drift: false, ...options });
}

/** Builds the rosette and appends it to `host`. Returns the <svg> element. */
export function mountRosette(host, options = {}) {
  const o = { ...DEFAULTS, ...options };
  const count = Math.max(2, Math.round(o.ringCount));
  const inner = Math.min(0.95, Math.max(0.02, o.innerRadius));
  const accent = o.accentStroke ?? o.stroke;

  const svg = node("svg", {
    viewBox: "0 0 1000 1000",
    fill: "none",
    "aria-hidden": "true",
    focusable: "false",
    class: "rosette",
  });

  /* The fade is a mask rather than a radial-gradient background: the rings must
     dissolve at the rim without the page ground showing a disc edge. */
  const defs = node("defs");
  const grad = node("radialGradient", { id: "rosette-fade", cx: "50%", cy: "50%", r: "50%" });
  [[0, 1], [0.52, 0.82], [0.86, 0.22], [1, 0]].forEach(([offset, op]) =>
    grad.append(node("stop", { offset, "stop-color": "#fff", "stop-opacity": op })),
  );
  const mask = node("mask", {
    id: "rosette-mask", maskUnits: "userSpaceOnUse",
    x: 0, y: 0, width: 1000, height: 1000,
  });
  mask.append(node("rect", { x: 0, y: 0, width: 1000, height: 1000, fill: "url(#rosette-fade)" }));
  defs.append(grad, mask);

  const figure = node("g", { mask: "url(#rosette-mask)", opacity: o.opacity });
  const bands = ["a", "b", "c"].map((name) => {
    const g = node("g", { "data-band": o.drift ? name : "static" });
    figure.append(g);
    return g;
  });

  for (let i = 0; i < count; i++) {
    const t = count === 1 ? 1 : i / (count - 1);
    const R = MAX_R * (inner + (1 - inner) * t);
    const marked = o.accentEvery > 0 && i % o.accentEvery === o.accentEvery - 1;
    const path = node("path", {
      d: ringPath(R, o.twist * t * Math.PI * 2, o),
      fill: "none",
      stroke: marked ? accent : o.stroke,
      "stroke-width": marked ? 1.1 : 0.7,
      "stroke-linejoin": "round",
      "vector-effect": "non-scaling-stroke",
    });
    /* Interleaved, not sliced: adjacent rings land in different bands, so the
       pattern between them moves. Sliced bands rotate as three solid discs. */
    bands[o.drift ? i % 3 : 0].append(path);
  }

  svg.append(defs, figure);
  host.append(svg);
  return svg;
}
