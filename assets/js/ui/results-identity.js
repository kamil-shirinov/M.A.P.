/* Which record is on screen, and what it is a record OF.

   The screen shows ONE measurement at a time. Two records for the clean band
   ship in this export — the same 175 items scored from a committed tree and from
   a dirty one — and the identity block's job is to make the reader's answer to
   "which numbers am I looking at" unambiguous before they look at any of them:
   the digest, the commit, the date, the vintage and the freeze, all on one line.

   THE ARITHMETIC IS SHOWN. `n` is not the number of runs and not the number of
   corpus items: it is what was left after the refusals, and the subtraction is
   printed so that 175 cannot be mistaken for a population.

   WHAT COMES FROM WHERE. `n`, the vintage, the freeze and the digest are in the
   2.2 KB manifest and are true before either 133.5 KB record has landed. The
   commit, the item counts and the arithmetic are in the record and wait for it.
   Splitting them that way is what lets the header be correct while reading,
   rather than skeleton-grey and then correct. */

import { resolveCommit } from "../lib/commits.js";
import { DERIVED, MEASURED, chromeText, derive, figure, renderFigure } from "../lib/figure.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/* The commit that scored a record, as the published history names it, with the
   record's own ID beside it when the two differ (lib/commits.js). */
function commitStamp(commit) {
  const { shown, recorded } = resolveCommit(commit);
  const wrap = el("span");
  wrap.append(chromeText(shown, "the commit that scored this record, in published history"));
  if (recorded) {
    wrap.append(
      el("span", "res-terms-aside", " recorded as "),
      chromeText(recorded, "the commit the scoring record stores"),
    );
  }
  return wrap;
}

const dot = () => chromeText(" · ", "a separator");

/** A figure that is not here yet. Marked chrome with its reason, not left bare:
    the audit has no heuristics and an ellipsis today is a number tomorrow. */
const pending = () => chromeText("…", "the record carrying this figure is still being read");

export function renderIdentity(root, { meta, record, stats, records, band, onBand }) {
  root.textContent = "";
  const card = el("div", "res-card res-identity");
  card.append(
    headline(meta, record, stats),
    switcher(meta, record, records, band, onBand),
  );
  root.append(card);
  return card;
}

function headline(meta, record, stats) {
  const left = el("div", "res-identity-left");

  const h1 = el("h1", "res-headline");
  h1.append(
    renderFigure(figure(meta.n, MEASURED, "int")),
    el("span", "res-headline-word", "items scored"),
  );
  left.append(h1);

  const scope = el("p", "res-scope");
  scope.append(
    chromeText(`${meta.band} band`, "which band was scored"),
    dot(),
    el("span", null, "development split"),
    dot(),
  );
  if (stats) {
    // Read from the items, not assumed: a record mixing horizons would say so.
    scope.append(
      chromeText(
        stats.horizons.length === 1
          ? `${stats.horizons[0]}-session horizon`
          : `${stats.horizons.join("/")}-session horizons`,
        "the forecast horizon the items were scored over",
      ),
      dot(),
      renderFigure(figure(stats.tickers, DERIVED, "int")),
      el("span", null, " tickers"),
      dot(),
      renderFigure(figure(stats.dates, DERIVED, "int")),
      el("span", null, " dates"),
    );
  } else {
    scope.append(pending(), el("span", null, " horizon"), dot(), pending(), el("span", null, " tickers"), dot(), pending(), el("span", null, " dates"));
  }
  left.append(scope);
  left.append(arithmetic(record));
  return left;
}

/** loaded − refused = n, with `loaded` derived rather than quoted: the record
    carries what was scored and what was refused, and their sum is the population
    that went in. Printing 178 alone would look like a third number. */
function arithmetic(record) {
  const p = el("p", "res-arith");
  if (!record) {
    p.append(pending(), el("span", null, " panel runs, less the refusals"));
    return p;
  }
  const refused = Object.values(record.unscored ?? {}).reduce((a, b) => a + b, 0);
  const loaded = derive(record.n.value + refused, "int", record.n);
  if (!refused) {
    p.append(renderFigure(loaded), el("span", null, ` ${record.band}/${record.split} panel runs, none refused`));
    return p;
  }
  p.append(
    renderFigure(loaded),
    el("span", null, ` ${record.band}/${record.split} panel runs `),
    chromeText("−", "an arithmetic operator"),
    el("span", null, " "),
    renderFigure(figure(refused, MEASURED, "int")),
    el("span", null, " refused "),
    chromeText("=", "an arithmetic operator"),
    el("span", null, " "),
    renderFigure(record.n),
    el("span", null, " — "),
    chromeText(Object.keys(record.unscored).join(", "), "the exception that refused them"),
  );
  return p;
}

/** The band switch, and the record's identity underneath it.

    `n` in the switch comes from the MANIFEST, so both counts are true before
    either record has been read and the control does not change shape when the
    second one lands. */
function switcher(meta, record, records, band, onBand) {
  const right = el("div", "res-identity-right");

  const bar = el("div", "res-bands");
  for (const [name, entry] of records.preferred) {
    const on = name === band;
    const b = el("button", "res-band");
    b.dataset.on = String(on);
    b.setAttribute("type", "button");
    if (on) b.setAttribute("aria-current", "true");
    b.append(el("span", "res-band-name", name), renderFigure(figure(entry.n, MEASURED, "int")));
    b.addEventListener("click", () => onBand(name));
    bar.append(b);
  }
  right.append(bar);

  const line = el("p", "res-record-line");
  line.append(
    // "code", as the manifest calls it (`code.forecast_digest`) and as the
    // company page labels the same eight characters. It read "record" here, which
    // is the export's word for the scoring FILE — a different thing that this
    // screen also shows.
    el("span", "res-k", "code "),
    chromeText(meta.forecast_digest.slice(0, 8), "an abbreviated forecast digest"),
    dot(),
    el("span", "res-k", "commit "),
    record ? commitStamp(record.commit) : pending(),
    dot(),
    el("span", "res-k", "scored "),
    record ? chromeText(record.scored_on, "the day the pass ran") : pending(),
    dot(),
    chromeText(`${meta.vintage} prices`, "the price vintage scored against"),
    dot(),
    chromeText(`freeze ${meta.freeze_version}`, "the frozen corpus the items came from"),
  );
  right.append(line);

  /* The twin. Same items, different code state, not a second result and not half
     of an average. Named here rather than dropped, because a reader who counts
     the files in the export would otherwise find one the screen never mentions.
     Empty for a band that ships once. */
  const note = el("p", "res-twin");
  const twin = records.twins.get(band);
  if (twin) {
    note.append(
      renderFigure(figure(1, DERIVED, "int")),
      el("span", null, ` more ${twin.band} record with no forecast digest: same items, not shown, not averaged`),
    );
  }
  right.append(note);
  return right;
}
