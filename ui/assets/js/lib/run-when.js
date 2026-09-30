/* When a run was made, and which price it opened from: two dates that are not
   always the same day.

   A run made on 30 September before the New York close opens from the 29th's
   close. A page that printed only the anchor said "2026-09-29", which reads as
   the day the run happened and is the day before. So the anchor stays exactly as
   recorded, and the time the run was made goes beside it, in the viewer's own
   time zone: "made 30 Sep, 19:29 · from the 29 Sep close".

   `made_at` is the first event in the run's trace, in UTC, carried by the
   export. It can be missing — some runs left no trace — and then this says so
   rather than borrowing a time from anywhere else. */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* The calendar parts of an instant in a time zone. `timeZone` undefined is the
   viewer's own. Numeric parts only, with the month named here: an en-GB short
   month is "Sept" under some ICU versions and "Sep" under others. */
function partsIn(instant, timeZone) {
  const format = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const p = Object.fromEntries(format.formatToParts(instant).map((x) => [x.type, x.value]));
  return { year: Number(p.year), month: Number(p.month), day: Number(p.day), time: `${p.hour}:${p.minute}` };
}

// An absence from the export is an object, never a string, so this is enough.
const known = (value) => typeof value === "string" && value !== "";

/** "30 Sep, 19:29" in the viewer's zone, with the year only when it is not this
    year's; null when there is no time to show. */
export function madeText(madeAt, { timeZone, now = new Date() } = {}) {
  if (!known(madeAt)) return null;
  const instant = new Date(madeAt);
  if (Number.isNaN(instant.getTime())) return null;
  const p = partsIn(instant, timeZone);
  const year = p.year === partsIn(now, timeZone).year ? "" : ` ${p.year}`;
  return `${p.day} ${MONTHS[p.month - 1]}${year}, ${p.time}`;
}

/** Which price the run opened from, worded by what the journal decided it was.
    The anchor is a session's date and has no time zone, so it is read as written. */
export function anchorText(anchorDate, priceKind, { year } = {}) {
  const [y, m, d] = String(anchorDate).split("-").map(Number);
  const day = `${d} ${MONTHS[m - 1]}${year !== undefined && y !== year ? ` ${y}` : ""}`;
  if (priceKind === "close") return `from the ${day} close`;
  if (priceKind === "intraday") return `from a ${day} price taken during that session, not a close`;
  return `from ${day}`;
}

/** The whole clause: "made 30 Sep, 19:29 · from the 29 Sep close". */
export function runWhen(run, { timeZone, now = new Date() } = {}) {
  const made = madeText(run.made_at, { timeZone, now });
  const year = known(run.made_at) && made
    ? partsIn(new Date(run.made_at), timeZone).year
    : partsIn(now, timeZone).year;
  const anchor = anchorText(run.anchor_date, run.price_kind, { year });
  return made ? `made ${made} · ${anchor}` : `${anchor} · when it was made was not recorded`;
}
