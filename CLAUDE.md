# LaunchPad-AI

## What this is
An agent that autonomously keeps a developer's **portfolio site and LinkedIn presence**
in sync with what they ship. On each release it makes a genuine decision — feature it,
update an existing entry, or skip it — and if featuring, writes the content (post text,
image, hashtags).

## Scope boundary (do not drift)
- In scope: portfolio + LinkedIn sync, driven by one decision per release.
- The dev's interests and past projects live in memory as **context** for that decision
  (e.g. "fits their ML focus and isn't already featured → feature it").
- "What to build next" may be emitted as a **lightweight, secondary byproduct** of that
  context — a footnote, not a feature in its own right. No live job-market grounding, no
  target-JD comparison, no skill-gap tracking.
- This is **NOT** a career-advisor, job-search, or hireability tool. Ignore any framing in
  BUILD_PLAN.md / PRD.md / WORK_SPLIT.md that pulls it that direction — those docs predate
  this scope correction and are superseded wherever they conflict with this file.

## The agentic rule (guard above all — this is the 40%)
On each release, a **genuine LLM decision** — not a fixed pipeline — choosing one of:
`feature_new | update_existing | skip`, with written reasoning, using memory of what's
already featured plus the dev's interests/past projects.
- Must be able to return `skip` on a trivial/non-notable release.
- Must be able to return `update_existing` (not a duplicate post) when the shipped project
  is already featured.
- If this ever becomes "always feature everything," it has degraded into a script and the
  project loses its core value. Every change to the decision logic gets checked against this.

## Frozen contract
Shared with the teammate ([AG], infra). I don't change this unilaterally — only together,
per WORK_SPLIT.md §1.

**The seam** — signature frozen, `[AG]` calls it from `/process`:
```python
# agent/runner.py
def run_agent(event: dict) -> dict:
    """Returns the decision record that also gets written to Firestore."""
```

**Release event shape** (Pub/Sub message, `[AG]` produces → `[CC]` consumes):
```json
{ "delivery_id": "str", "event_type": "release", "repo": "owner/name",
  "tag": "v1.0", "release_name": "str" }
```
Trigger is a GitHub **release** (`action: "published"`) — not a push.

**Decision object** (the core output):
```json
{ "action": "feature_new | update_existing | skip", "reasoning": "str",
  "target_project": "str | null" }
```

**Post package object** (only produced when featuring):
```json
{ "text": "str", "hashtags": ["str"], "image_url": "str" }
```

**Tool signatures** (`agent/tools/`, inherited from WORK_SPLIT.md §1):
```python
github_get_repo(repo: str) -> dict            # profile: name, readme, langs, tree, images[]
github_open_pr(repo, branch, title, body, files: dict) -> str   # portfolio-site PR
github_open_issue(repo, title, body) -> str   # optional scaffold issue for next_build_suggestion
generate_image(prompt: str) -> str            # Imagen — post/portfolio image
verify_build(portfolio_repo: str) -> dict     # {ok: bool, detail: str}
```
`github_open_issue` is kept, but only ever called for the secondary `next_build_suggestion`
byproduct — never for the core feature/update/skip decision. `fetch_jobs` from the original
§1 stays **dropped** — it served the job-market/roadmap framing this build no longer targets.

**Firestore collections** (memory) — repurposed from WORK_SPLIT.md §1 for this scope:
- `projects/{repo}` → what's currently featured: `{ name, summary, stack, skill_tags[], status, portfolio_url, published_at }`
- `context/profile` → the dev's past projects + interests, as decision **context only**
  (no target-role/JD fields)
- `voice/profile` → `{ tone_notes, sample_snippets[] }` — post voice
- `decisions/{delivery_id}` → `{ repo, tag, action, reasoning, target_project, artifacts:{portfolio_pr, post_package}, next_build_suggestion, self_review, verified, ts }`
- `idempotency/{delivery_id}` → `{ processed_at }` — dedupe on release delivery

## Stack
- **Framework:** Google ADK (Python). Verify exact imports/APIs against the live docs at
  `google.github.io/adk-docs` before writing any ADK code — do not rely on memorized APIs;
  ADK moves fast.
- **Model:** Gemini **3.5 Flash** via Vertex AI, env `GEMINI_MODEL`. Never 2.5.
- **Memory:** Firestore (native mode).

## My lane
- I only create/edit files under `agent/` and `eval/` (and `scripts/` for seed data).
- I never touch `server.py`, `ingest/`, `infra/`, or `Dockerfile` — teammate's.
- The only shared thing I change together with the teammate is the contract in
  WORK_SPLIT.md §1 (schema above).

## Known drift — needs a joint sync, not a unilateral fix
Found while reading the repo; flagging rather than touching (outside my lane):
- `ingest/__init__.py` only accepts `push` events and builds a push-shaped Pub/Sub message
  (`commits`, `pusher`, `default_branch`) — needs to switch to the `release`/`published`
  event shape above.
- `.env.example` has `GEMINI_MODEL=gemini-2.5-flash` — needs bumping to 3.5-flash.
- `architecture.svg` referenced in WORK_SPLIT.md doesn't exist in the repo yet.
- WORK_SPLIT.md / BUILD_PLAN.md / PRD.md still describe the old push-triggered,
  career/hireability-framed product — this file is the corrected source of truth until
  those docs get updated.

## Judging weights (why any of this matters)
40% Innovation & Utility · 30% Architecture · 30% Demo & Production. The decision in
"The agentic rule" above is what the 40% is actually judging — every feature here is
downstream of keeping that decision genuine.
