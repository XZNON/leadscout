# Session 07+ — Post-MVP backlog

**Status:** ⬜ not started
**Goal:** parking lot for work explicitly deferred past MVP (idea.md §11, §13). Pull one item into
its own session when MVP (Session 06) is solid. Don't start these early — MVP first.

## Candidate sessions (pick one per session, in roughly this order)

### A. JustDial / IndiaMART adapters (idea.md §7 India coverage)
New source clients feeding the **same** `discover` dedup step; normalize into the `Lead` shape
with the right `source` tag. Places thins out for tier-2/3 shops — these fill the gap. Mind ToS
and scraping etiquette.

### B. State-level tiling (idea.md §7)
Today city→bbox→tiles works; extend to `state` with smarter tile subdivision when a `(tile,
keyword)` exceeds the 60-result cap (the hook is noted in `discover.resolve_tiles`).

### C. Owner-name enrichment (idea.md §12.3)
Best-effort decision-maker name beyond what the homepage gives. LinkedIn is fragile/ToS-sensitive
— decide how hard to try vs. accept business-level contact. Don't build anything that violates ToS.

### D. SQLite for cross-run dedup & state (idea.md §12.4)
Move from flat-file cache + CSV to a lightweight local SQLite DB so dedup and lead state persist
across sessions/runs. Keep CSV/JSONL export.

### E. Opener format variants (idea.md §12.5)
Call-script vs email vs WhatsApp opener templates, selectable per run. Still grounded in detected
signals — no generic templates.

## Hard out-of-scope (do NOT build — idea.md §10/§11)
- Auto-dialing, AI-voice calling, bulk email/WhatsApp blasting — not even a stub.
- CRM integration / sequencing, multi-user SaaS, auth, billing, web UI (unless it earns its place).
