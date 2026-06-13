# Session kickoff — plan the next step

You are starting a fresh session on the **LeadScout** project. Your job in THIS session is **not to
write feature code** — it is to understand where the project stands, find the next unit of work, and
produce a detailed, ready-to-execute implementation plan for it as a markdown file. A later session
will pick up that file and do the actual build.

## Step 1 — Load the full context (read, don't skim)

Read these to reconstruct the project's intent, rules, and current state:

1. `idea.md` — the product source of truth (what we're building and why).
2. `CLAUDE.md` — how we work: non-negotiables, conventions, definition of done.
3. `.claude/rules.md` — always-follow guardrails (cost, scraping, secrets, dedup, legal).
4. `.claude/skills/*.md` — workflow notes (run-pipeline, add-icp, verify-stage).
5. `docs/sessions/README.md` — the session roadmap and **status table** (✅/🔨/⬜).
6. Every `docs/sessions/session-*.md` — so you understand each step's goal and Definition of done.
7. `Implementations/*.md` (if any exist) — plans already written, so you don't duplicate them.
8. The current code under `src/leadscout/` and `tests/` — to verify what is *actually* built vs.
   what the roadmap claims. Trust the code over the docs when they disagree, and note the drift.

Also run a quick reality check on state where cheap to do so (e.g. is there a git history yet, do
tests currently pass, which `Live*Client` stubs are still `NotImplementedError`).

## Step 2 — Identify the next step

From the roadmap status table, pick the **lowest-numbered session that is not ✅ done**. Confirm its
prerequisites are actually met by the current code (not just marked done). If a 🔨 session is only
partly complete, the next step is finishing it. State clearly which step you selected and why.

## Step 3 — Produce the implementation plan (use plan mode)

Enter plan mode and design a concrete, step-by-step implementation plan for that one step only. Do
**not** pull work forward from later sessions. The plan must include:

- **Goal & scope** — one paragraph; what "done" means for this step, in this step's words.
- **Prerequisites** — what must already be true, and confirmation it is.
- **Files to create/modify** — exact paths, with a one-line note on the change to each.
- **Implementation steps** — ordered, specific, each independently verifiable. Reference the real
  function/class names in the codebase (e.g. `LivePlacesClient.search`, `discover.resolve_tiles`).
- **Contracts & types** — which pydantic models / interfaces are touched; keep stage contracts
  stable unless the step explicitly changes them.
- **Tests** — the exact tests to add/keep green, what each asserts, and that they stay **offline**
  (no live API calls in pytest; fixtures only).
- **Final checks (the gate)** — the literal commands to run and pass before calling it done:
  `uv run pytest -q`, `uv run ruff check .`, `uv run mypy`, plus any step-specific run command.
- **Definition of done** — copy/adapt the session file's DoD; nothing is done until it runs and is
  tested. Include the commit message to use.
- **Non-negotiables touched** — call out which guardrails apply (e.g. "LLM only in Stage 4",
  "respect robots.txt", "no secrets committed", "dedup on place_id") and how the plan honors them.
- **Risks / unknowns** — anything to research first (API behavior, model IDs, pricing). Never guess
  API behavior — flag it to look up.

## Step 4 — Save the plan

Write the approved plan to `Implementations/step{NN}_implementation.md`, where `{NN}` is the
zero-padded session number you selected (e.g. Session 03 → `Implementations/step03_implementation.md`).
Create the `Implementations/` folder if it does not exist. If a file for that step already exists,
update it rather than creating a duplicate.

Then output a one-line pointer: which step was planned and the path to the file.

## What NOT to do this session

- Do not implement the feature, edit `src/leadscout/` beyond what's needed to read state, or run
  live APIs.
- Do not change `.env.example` or re-add gitignored files (`.claude/`, `examples/`, `CLAUDE.md`,
  `idea.md`).
- Do not commit anything with a real secret staged. Keep the pre-commit secret check intact.
