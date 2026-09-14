import { HORIZONS, isCalibrated, calibrationNote } from "../lib/calibration.js";
import { chromeText } from "../lib/figure.js";

export function renderHorizon(host, { horizon, onChange }) {
  host.textContent = "";

  const row = document.createElement("div");
  row.className = "horizon";

  for (const h of HORIZONS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "opt";
    b.setAttribute("aria-pressed", String(h === horizon));
    // The label carries digits and is not a figure, so it is marked as chrome.
    b.append(chromeText(`${h} session${h === 1 ? "" : "s"}`, "horizon option label"));
    if (isCalibrated(h)) {
      const m = document.createElement("span");
      m.className = "mark";
      m.textContent = "✓";
      m.title = "Calibrated horizon";
      b.append(m);
    }
    b.addEventListener("click", () => onChange(h));
    row.append(b);
  }
  host.append(row);

  const note = calibrationNote(horizon);
  const box = document.createElement("p");
  box.className = "calibration-note";
  const strong = document.createElement("strong");
  strong.append(chromeText(note.headline, "calibration headline may contain a session count"));
  box.append(strong, document.createTextNode(" " + note.detail));
  host.append(box);
}
