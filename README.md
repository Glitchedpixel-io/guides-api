# guides-api

[![Tests](https://github.com/Glitchedpixel-io/guides-api/actions/workflows/tests.yml/badge.svg)](https://github.com/Glitchedpixel-io/guides-api/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Authoring and PDF rendering for illustrated how-to guides.

Guide content lives in Postgres and is created, read, and edited over HTTP. A revision
renders to a printable procedure sheet in a fixed engineering-drawing house style. Authors
can upload a hand-drawn sketch for a step and have it redrawn as house-style vector line
art.

> **Badges.** Coverage and Deploy badges are deliberately absent. Coverage is enforced
> (`--cov-fail-under=85`) but nothing uploads to Codecov yet, and there is no `deploy.yml`.
> Per [`readme-badges.md`](https://github.com/Glitchedpixel-io/claude-code/blob/main/docs/standards/readme-badges.md),
> a badge is a claim about CI — add each one when the thing it claims becomes true.

---

## What it produces

A US-Letter procedure sheet flattened from the Claude Design canvas *Blueprint instruction
template*: a double-ruled frame with corner registration marks, a masthead carrying the
document number and revision, three optional lettered panels (**A** bill of materials,
**B** required tools, **C** safety warnings, hatched), a symbols legend, then the steps —
each a boxed `STEP n` badge, a graph-paper drawing plate with numbered callout bubbles and
leader lines, and instructions beside a callout key. Every page carries a scale bar and a
title block with `PAGE n OF m`. A final record page holds a results table, the revision
history, a ruled notes field, a support QR, and a sign-off block.

Steps flow: a step too long for the remaining column moves to the next page rather than
being clipped, and the page count follows.

## Model

| Concept | Meaning |
|---|---|
| **Guide** | Stable identity — slug, document number, title. A change of title is a new guide. |
| **Revision** | The versioned content root. Everything printed hangs off it. |
| **Step** | One ordered instruction with a drawing plate. Order is a database constraint. |
| **Callout** | A numbered bubble over a plate. Stored as rows, not baked into the drawing. |
| **Asset** | A stored file — sketch, redrawn SVG, photo, or rendered PDF. |
| **Render** | A produced PDF, recorded against its revision *and* its template version. |

**Published content is frozen.** A revision is editable only while it is a draft; issuing a
change means issuing a new revision. A printed procedure sheet has to stay reproducible from
the database, and editing an issued revision would quietly make a document someone is
holding unverifiable.

## Sketch redraw

Claude has vision input but does not generate images — it writes the SVG as text. That is
the right output for a drawing plate: crisp at print resolution, diffable, and re-styleable
without another model call.

```
POST /api/steps/{id}/sketch     upload a sketch, get a job (202)
GET  /api/sketch-jobs/{id}      poll it
POST /api/sketch-jobs/{id}/approve   promote the drawing onto the step
```

Two properties worth knowing:

- **Nothing reaches a sheet unreviewed.** A finished job stores its drawing but does not
  attach it; promotion is an explicit call. The original sketch is never deleted, so a
  redraw is always repeatable and reversible.
- **The SVG is sanitised before it is stored**, against an allow-list of elements and
  attributes. Model output is embedded into a rendered document; treating it as trusted
  markup is how a drawing becomes an incident.

The house-style prompt is a versioned file (`app/sketch/prompts/`) and its version is
recorded on every job, so we know which drawings predate a style change.

## Running it

Requires Python 3.13, Postgres, and WeasyPrint's native libraries:

```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
                        libcairo2 libgdk-pixbuf-2.0-0
uv sync --dev
cp .env.example .env.development     # then edit
uv run alembic upgrade head
uv run uvicorn app.main:api --reload
```

OpenAPI is at `/docs`. `/health` reports the running version *and* the template version —
two instances on different template versions produce visibly different sheets from
identical data, and that is otherwise invisible.

## Tests

```bash
uv run pytest tests/                      # everything; needs Postgres
uv run pytest tests/ -m "not integration" --no-cov   # the fast tier
```

Three tiers per [`standards/testing.md`](https://github.com/Glitchedpixel-io/claude-code/blob/main/docs/standards/testing.md):
`unit/` (no I/O), `api/` (HTTP surface with faked services), `integration/` (real Postgres,
real WeasyPrint). The coverage floor is **85** and is set against the full run — pass
`--no-cov` when running a subset.

The integration tier builds its schema by running Alembic, not `create_all()`. A migration
that fails to reproduce the models is exactly the bug worth catching, and `create_all`
would hide it.

**No test calls the real Anthropic API.** The redraw client is exercised against a faked
SDK. CI that spends money and fails on a provider hiccup gets muted, and a muted test is
worse than no test.
