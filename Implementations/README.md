# Implementations

Per-step implementation plans, one file per session step: `step{NN}_implementation.md`.

**Workflow:**
1. In a fresh session, drop in `prompt.md`. It reads the project state, finds the next unfinished
   step in `docs/sessions/`, and writes a detailed plan here (e.g. `step02_implementation.md`).
2. In the *next* session, drop in that `step{NN}_implementation.md` to actually build the step,
   following its steps, tests, final checks, and Definition of done.

These plans are generated artifacts — the roadmap in `docs/sessions/` stays the source of truth for
*what* each step is; the files here are the worked-out *how* for one step at a time.
