# Grasshopper walkthroughs

Interactive, annotated walkthroughs generated straight from a Grasshopper `.gh` file, plus a safe clean-up tool for the file itself. Everything is plain Python 3 (standard library only); no Rhino, Grasshopper or plug-ins are needed to run it.

**Output:** `DR_Walkthrough.html` is one self-contained file. Open it in any browser, or put it on a website or LMS. It needs no server and no install.

## Folder layout

```
DFLUR5_DR1_T32026_CALIB.gh        original script (never modified)
DFLUR5_DR1_T32026_CALIB_tidy.gh   cleaned copy made by gh_tidy.py
DR_Walkthrough.html               the generated walkthrough
content/
  brief.md          the big picture: purpose, stages, key concepts, workflow  (authored)
  walkthrough.md    deep dives into clusters                                  (authored)
  components.md     notes shown for every component of a given type           (authored)
tools/
  build.py          .gh + content -> DR_Walkthrough.html, and a report of what needs notes
  stages.py         detects the canvas's major areas and the data flowing between them
  gh_tidy.py        safe clean-up of a .gh (layout, spelling, empty groups) -> new file
  gh_verify.py      proves two .gh files compute the same thing
  gh_extract.py     .gh -> JSON model;  gh_io.py / gh_raw.py read and write the .gh format
  viewer/           the page template, CSS and JS
```

## Everyday use: the script changed

```bash
python3 tools/gh_tidy.py NEW_SCRIPT.gh          # optional: writes NEW_SCRIPT_tidy.gh and verifies it
python3 tools/build.py NEW_SCRIPT_tidy.gh       # rebuilds DR_Walkthrough.html
```

`build.py` then prints:

- **reference problems**: notes that point at something renamed or deleted. Fix the name in `content/*.md`.
- **open questions**: lines starting `??` that still need an answer.
- **not yet explained**: named groups and clusters that no note mentions. They can still be explored in the page, but may deserve a note.

The canvas drawings always come from the file, so they are never out of date.

## Making a walkthrough for a new script (the guided process)

1. **Tidy** (optional): `python3 tools/gh_tidy.py script.gh`. Open the `_tidy.gh` in Grasshopper to check it.
2. **Draft the brief**: `python3 tools/stages.py script_tidy.gh --draft` writes `content/brief.draft.md`. It lists the areas it found on the canvas, what flows between them (read from the real wires), and the controls in each. Every `??` line is a question for the author.
3. **Answer the questions together.** This is the step that needs a person. Explain the intent: what the script is for, who uses it, the real-world workflow around it, and the mistakes people make. Claude can fill in what it can infer from the file and mark the rest `??`. Save the result as `content/brief.md`.
4. **Deep dives**: write `content/walkthrough.md` for the clusters worth explaining, using the report from `build.py` as a checklist.
5. **Build** and read it. Iterate on the notes, not the page.

## Notes format (all three files)

```markdown
# Part title                          (a heading in the step list)

## Step title                          (one step)
@doc: DR robotic Motions/DFL weaver   (which canvas: a cluster path; default is the main canvas)
@focus: Lead In, Lead Out              (what to frame: group or component names, or "all")

Text in Markdown. [[Load robot system]] is a link that shows that component.
[[doc:DR Path Planning|look inside]] opens a cluster. [[step:workflow|Workflow]] jumps to a step.

- [Controlled Speed] A list where every item starts with [name] becomes numbered pins on the canvas.
- [Pressure @ DFL FULL TOOL] "@ group" picks the one inside that group when a name is repeated.
- [#548bf3ea|Your drawing] "#id" (from the warnings) picks one exact object; "|label" sets the label shown.

> **Tip:** shows as a blue note.  > **Important:** shows as an orange warning.
?? A question for the author, shown as a "To confirm" box until removed.
```

`brief.md` adds:

- `## Stage: Name` with `@covers: Group A, Group B`. This makes a stage on the map. The arrows between stages are computed from the wires, and the order you write the stages in decides which way loops are drawn.
- `## Concept: Name` for key ideas.
- `@view: map` shows the stage map instead of the canvas.
- Header lines: `name:`, `subtitle:`, `purpose:`, `audience:`, and `rename: Old=New, ...` to give flow labels friendlier names.

## Speed: gh_optimise.py and profiling

```bash
python3 tools/gh_optimise.py DFLUR5_DR1_T32026_CALIB_tidy.gh    # writes DFLUR5_DR1_T32026_CALIB_fast.gh
```

This applies a short list of explicit speed-ups (documented at the top of the script), then compares the two files and prints every difference. The printed list, not the script, is the record of what changed.

The tool builder cluster ("DFL DR2 Tool") is embedded four times, once per tool. Treat the copy inside **Make Custom Tool** on the main canvas as the master: edit that one, save, then push it into the others:

```bash
python3 tools/gh_sync_clusters.py SCRIPT.gh "DFL DR2 Tool"          # writes SCRIPT_synced.gh and verifies it
```

`gh_optimise.py` runs this sync as its last step.

To find out what is actually slow on a student machine, paste `tools/gh_profile_dump.py` into a Python 3 Script component. After a full solve it writes `~/gh_profile.csv` with every component's solve time and data size, slowest first.

## What gh_tidy.py will and will not change

It **will**:

- lay out cluster interiors left to right (and only keeps a new layout when it has fewer wire crossings and overlaps than before);
- delete empty leftover groups;
- fix a list of spelling mistakes in display text (the `TYPOS` table in `gh_tidy.py`);
- name unnamed cluster inputs and outputs after their outside names.

It **never** touches wires, values, settings, scripts, value-list expressions, or panel text that feeds the solution, and it never overwrites its input. It finishes by running `gh_verify.py`, which compares every stored value in both files and fails if anything other than positions and display text differs. Always open the tidied file in Grasshopper and check it before relying on it.
