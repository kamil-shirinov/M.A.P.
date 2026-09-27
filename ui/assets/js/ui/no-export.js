/* The one No-export panel, for all four screens.

   `ui/assets/export/` is gitignored and generated, so this is what every clone
   of the repository sees until someone runs `map export`. It is the one absence
   the export cannot state for itself — there is no manifest to read it from —
   so the interface states it.

   ONE PANEL, because there were three. The company page drew this box; the
   search screen drew its own copy of it; results printed the reason into its
   status line; and the runs screen drew NOTHING, so it rendered its ordinary
   header against an empty journal and reported

     Runs · 0 RUNS · across the four document-source files, not yet read

   A zero where the truth is "there is no export" is exactly the reading this
   project refuses everywhere else: an absence is stated, never shown as a count.
   Nothing had been read, so nothing could be zero.

   The stamps go too. They are vintages of an export that does not exist, and a
   footer reading `export null · prices null` is the same error in miniature. */

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** Replace a screen's content with the panel, and blank its vintage stamps.

    `absence` is what `getExportState().why` returns: an absence carrying the
    reason and the command that fixes it. `hosts` names the elements to clear,
    because a screen that keeps stamping a manifest it does not have is claiming
    an export exists. */
export function renderNoExport(main, absence, { footer, vintage } = {}) {
  main.textContent = "";

  const box = el("div", "cmp-empty");
  // Every digit in the reason is a path or a command, not a measurement.
  box.dataset.chrome = "no export is present; nothing on screen is a figure";
  box.append(el("h1", null, "No export"));
  box.append(el("p", null, absence?.why ?? "No export has been generated."));
  if (absence?.remedy) box.append(el("pre", null, absence.remedy));
  main.append(box);

  if (footer) footer.textContent = "";
  if (vintage) vintage.textContent = "";
  return box;
}
