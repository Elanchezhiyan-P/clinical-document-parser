# Clinical Document Parser

Built by **Elanchezhiyan P** ([codebyelan.in](https://codebyelan.in)).

**Live demo:** [medparser.codebyelan.in](https://medparser.codebyelan.in)
*(demo only — please don't upload real patient data; use one of the
sample files in `samples/` instead)*

A standalone Flask web app (separate from the Healthie sync tool elsewhere
in this repo). Upload a clinical document, and it auto-detects the format
and lays out everything it contains in a plain-language, non-technical
view — no prior knowledge of the file format required.

**Privacy:** nothing you upload is stored, logged, or written to disk.
Each file is parsed entirely in memory for the single request that renders
it, then discarded. The only thing remembered across visits is a cookie
holding the *filename* and *when* you last viewed something (used for the
"welcome back" banner) — never the file's contents.

## Supported formats

- **C-CDA** (HL7 Clinical Document Architecture XML) — every `<section>`
  in the document, including ones this codebase has never seen before,
  walked generically by structure rather than a hardcoded list of known
  sections.
- **HL7 v2.x** (pipe-delimited messages, `MSH|...`) — every segment and
  field, with human-readable labels for common segments (MSH, PID, PV1,
  OBR, OBX, ORC, DG1, AL1, RXA, RXE, IN1, GT1, NK1, EVN) and generic
  numbered labels for anything else, so unknown segments/fields still show.
- **FHIR** (JSON or XML, a single resource or a Bundle) — every resource,
  fully expanded, with a best-effort one-line summary for common resource
  types (Patient, Observation, Condition, MedicationRequest, etc.) plus the
  complete raw field tree underneath.

Nothing here writes to Healthie or any other external system — this is a
read-only viewer. No uploaded file is stored server-side beyond the request
that renders it.

## Features (C-CDA viewer)

The C-CDA result page is the most developed view:

- **Portal-style cards** — one card per section, color-coded with an icon,
  a plain-language title, and a count of items inside.
- **Drag to reorder** — grab a card by its header, or a row in the Table of
  Contents, and drop it anywhere else in the stack; both stay in sync.
- **Resize cards** — drag any edge (or the corner) of a card to make it
  bigger or smaller; layout is remembered per file (see below).
- **Table of Contents drawer** — docked to the right edge of the screen,
  toggle it open/closed with the "Contents" tab; shows briefly on first
  load, then stays out of the way until you open it again.
- **Search** — filters cards to matches and highlights every hit inline.
- **Timeline** — pulls every dated row out of every table (visits, labs,
  referrals, etc.) into one chronological list, newest first.
- **Print / Save as PDF** — a dedicated print stylesheet flattens the
  layout into a clean, single-column, fully-expanded document.
- **Remembered layout** — card order, hidden cards, and any resizing
  persist per file in the browser's local storage, so reopening the same
  file keeps your arrangement.
- **Resizable table columns** — drag a column header's edge to reclaim
  width from one column and give it to another.
- Informational (not diagnostic) heuristic flags: a referral row whose
  target date has passed, a lab result outside its printed reference
  range, or a medication name that textually overlaps a listed allergy.
  These are plain text/number matches, not a clinical safety check.

The FHIR and HL7 v2.x result pages currently have search and print/export,
but not the full drag/resize/timeline treatment.

## Setup

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5057** and upload a file (or try one of the
samples in `samples/`). Uploads are capped at 4 MB (matching what the
Vercel deployment's own platform limit allows).

Optional environment variables:

| Variable     | Purpose                                                             | Default                    |
| ------------ | -------------------------------------------------------------------- | --------------------------- |
| `SECRET_KEY` | Signs cookies/flash messages. Set a fixed value in production so signed cookies survive a redeploy. | random, regenerated per process |
| `DEBUG`      | Set to `1` to run the local dev server with Flask's debugger. Never set this in a public deployment. | off |

## Deploying

Live at [medparser.codebyelan.in](https://medparser.codebyelan.in) on
Vercel, which auto-detects the top-level `app.py` / `app` object as a
Python (Flask) app with no extra config needed. If you deploy your own
copy, set `SECRET_KEY` in the platform's environment variables.

## Project structure

```
app.py                  Flask routes: "/" (upload form) and "/upload"
parsers/
  detect.py              Sniffs raw bytes and picks a format -- no file
                          extension or user-supplied hint required
  ccda_parser.py          C-CDA (HL7 CDA) XML parser
  hl7v2_parser.py         HL7 v2.x pipe-delimited message parser
  fhir_parser.py          FHIR JSON/XML parser
templates/
  index.html              Upload landing page
  result_ccda.html         C-CDA result view (the portal UI described above)
  result_hl7v2.html        HL7 v2.x result view
  result_fhir.html         FHIR result view
  icons.html               Shared per-section icon/color/emoji lookup
static/style.css         All styling (Tailwind is loaded for utility
                          classes only; the design system itself lives here)
samples/                 A few sample files to try the app with
```

## Design notes

- `ccda_parser.py` walks every `<section>` and, inside each `<entry>`,
  every `act`/`observation`/`substanceAdministration`/`organizer`/
  `procedure`/`supply`/`encounter` node, regardless of which C-CDA
  template it belongs to. This is deliberately different from the
  section-by-section parser in `../ccda2healthie/` (which only extracts
  the handful of sections Healthie has an API for) — this one's job is
  completeness, not integration.
- `hl7v2_parser.py` and `fhir_parser.py` are similarly generic: an
  unrecognized segment or an FHIR field this code doesn't have a special
  case for is still rendered, just without a friendly label.
- No build step — Tailwind is loaded from a CDN with `preflight` disabled
  so it only supplies utility classes on top of the hand-written design
  system in `static/style.css`, never resetting it.
