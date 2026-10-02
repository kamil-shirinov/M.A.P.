import { figure, renderFigure, chromeText } from "../lib/figure.js";

export function renderAudit(host, { models, trace, runId, provenance }) {
  host.textContent = "";
  const wrap = document.createElement("div");
  wrap.className = "audit";

  for (const m of models) {
    const row = document.createElement("div");
    row.className = "model";

    const role = document.createElement("span");
    role.className = "role";
    role.textContent = m.role;

    const name = document.createElement("span");
    name.className = "name";
    // Model names contain digits (llama-3.2-3b) and are identifiers, not figures.
    name.append(chromeText(m.name, "model identifier"));

    const ms = document.createElement("span");
    ms.className = "ms";
    ms.append(renderFigure(figure(m.runtime_ms, provenance, "ms")));

    row.append(role, name, ms);
    wrap.append(row);
  }

  const link = document.createElement("p");
  link.className = "trace";
  const a = document.createElement("a");
  a.href = trace.href;
  a.append(chromeText(`Full trace — ${trace.events} events`, "trace event count"));
  link.append(a);
  wrap.append(link);

  const rid = document.createElement("p");
  rid.className = "trace";
  rid.append(chromeText("run " + runId, "run identifier"));
  wrap.append(rid);

  host.append(wrap);
}
