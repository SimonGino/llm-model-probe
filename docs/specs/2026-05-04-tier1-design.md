# Tier 1 — Tags + Search + Model Sort

**Date**: 2026-05-04
**Status**: approved (verbal)
**Builds on**: `docs/specs/2026-05-01-design.md`, `2026-05-01-ui-design.md`, `2026-05-02-probe-redesign-design.md`

## Goal

Make the tool comfortable to use beyond ~10 endpoints by adding the three
organization affordances that hurt first as the registry grows:

1. **Tags** on endpoints (free-form, multi-valued) — for grouping by source
   ("供应商A", "trial", "team-foo").
2. **Endpoint search** (table-level filter) — substring match across name,
   note, and tags.
3. **Drawer model search + sort** — find a model among 200+, with results
   sections sorted meaningfully (Available by latency, Failed by error
   type, Untested alphabetical).

This is the smallest set that makes the leap from "demo / personal tool"
to "I can manage 30+ endpoints without losing my mind". History, encrypted
keys, auth, scheduling, etc. are deferred.

## Non-Goals

- Editing tags via CLI (UI only). `--tag` on `probe add` is the only CLI
  surface for tags in this round.
- Tag autocomplete from existing tags (drop-in nice-to-have, but the
  free-text input + the table filter dropdown together cover the workflow).
- Tag colors / icons. Plain text chips.
- Per-model probe history. (Tier 2.)
- Cross-endpoint model matrix. (Tier 2.)
- Encrypted at rest, auth, scheduled probing, capability probing. (Tier 3.)

## Data Model

Single additive change: a `tags_json` column on `endpoints`.

```sql
ALTER TABLE endpoints
    ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]';
```

SQLite has no `IF NOT EXISTS` for column adds, so `EndpointStore.init_schema`
runs an idempotent migration:

```python
def _migrate_tags(self, c: sqlite3.Connection) -> None:
    cols = {row["name"] for row in c.execute("PRAGMA table_info(endpoints)")}
    if "tags_json" not in cols:
        c.execute(
            "ALTER TABLE endpoints "
            "ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
        )
```

Called once after `executescript(SCHEMA)` and before the existing models
backfill. Existing rows get `[]` automatically.

The `Endpoint` dataclass gains `tags: list[str] = field(default_factory=list)`,
written/read via `json.dumps` / `json.loads` exactly like `models`.

## API Changes

### `EndpointCreate` (input)

```python
class EndpointCreate(BaseModel):
    # ... existing ...
    tags: list[str] = []
```

Empty list is fine. The `create_endpoint` route persists `tags` to the new
column.

### `EndpointSummary` and `EndpointDetail` (output)

```python
class EndpointSummary(BaseModel):
    # ... existing ...
    tags: list[str]
```

Both summary and detail responses include `tags` so the table can render
them without an extra detail fetch.

### New: `PUT /api/endpoints/{name_or_id}/tags`

```python
class TagsUpdate(BaseModel):
    tags: list[str]

@app.put("/api/endpoints/{name_or_id}/tags",
         response_model=EndpointSummary)
def set_tags(name_or_id: str, body: TagsUpdate) -> EndpointSummary:
    ...
```

Replaces the full tag list. Trims whitespace per element; drops empty
strings; deduplicates while preserving first-seen order. Returns the
updated `EndpointSummary` so callers can refresh their cache.

404 if endpoint not found.

## CLI Changes

Single addition on `probe add`:

```python
tags: Optional[str] = typer.Option(
    None, "--tag",
    help="Comma-separated tags, e.g. 'bob,trial'",
),
```

Parsed identically to `--models`: split on comma, trim, drop empties.
Persisted via the same path as the API.

No new CLI subcommand for tag editing; UI handles that flow.

## Frontend Changes

### `EndpointTable` — search + tag filter + tag column

Layout above the table (new):

```
┌──────────────────────────────────────────────────┐
│ [Search name/note/tag...]  [Tag ▾]               │
└──────────────────────────────────────────────────┘
ID  Name  SDK  Mode  Status  Tested  Tags  Note  Actions
```

- **Search input** (free text): case-insensitive substring match across
  `name`, `note`, and any tag.
- **Tag dropdown**: multi-select of all distinct tags across the current
  endpoints list. AND-combined with the search input. Implementation:
  shadcn `<DropdownMenu>` with checkbox items. Empty selection = no tag
  filter.
- **Tags column**: small badge per tag (shadcn `<Badge variant="secondary">`).
  More than 3 tags → show first 3 + `+N`.

The note column gets narrower to make room (`max-w-[160px]` from 200).

State: search string + selected tag set live in `App.tsx` (lifted out so
they survive endpoint refetches), passed as props.

### `EndpointDetailDrawer` — tag editor

Add a row to the detail card area:

```
Tags    [trial ✕] [bob ✕]   [+ add tag input ↵]
```

- Each tag: shadcn `<Badge>` with a small ✕ button.
- Input: small text field; on Enter, append to tag list and PUT to server.
- On ✕ click, remove tag and PUT.

State: `useMutation` wrapping `api.setTags(idOrName, tags)`. On success,
invalidate `["endpoint", id]` and `["endpoints"]` so the table reflects
changes.

### `EndpointDetailDrawer` — model search + section sort

Add a search input above the three sections:

```
Models (239)               [Search models...]
                                                  [Test selected (12)] [Test all]

AVAILABLE (3) ...
FAILED (12) ...
UNTESTED (224) ...
```

Frontend filters all three sections by case-insensitive substring against
`model_id`. Empty input = show all.

**Section ordering** (within section):

| Section | Sort key |
|---|---|
| Available | `latency_ms` ASC (fastest first), nulls last |
| Failed | `error_type` ASC, then `model_id` ASC (group same errors) |
| Untested | `model_id` ASC (alphabetical) |

The "Test selected" / "Test all" buttons act on the **filtered** view if
a search is active (so you can `Test all` for "all gpt-* models"), else on
the full list. Add a small hint label when filter is active:
"`Test all (filtered: 5)`".

### Frontend `api.ts`

Add:

```ts
setTags: (idOrName: string, tags: string[]) =>
  req<EndpointSummary>("PUT",
    `/api/endpoints/${encodeURIComponent(idOrName)}/tags`,
    { tags }),
```

### Frontend `types.ts`

Add `tags: string[]` to both `EndpointSummary` and `EndpointDetail`. Add
`tags?: string[]` to `EndpointCreate`.

## Backend Tests

In `tests/test_api_endpoints.py`:

- `test_create_with_tags_persists` — POST with `tags: ["a","b"]`,
  GET → returns same.
- `test_create_default_tags_empty` — POST without tags → `tags == []`.
- `test_set_tags_replaces` — PUT replaces full list; deduplicates;
  trims whitespace.
- `test_set_tags_unknown_endpoint_404`.
- `test_summary_includes_tags` — list view also has tags.

In `tests/test_store.py`:

- `test_init_schema_adds_tags_column_idempotently` — open old-style DB
  (manually create a table without `tags_json`), call `init_schema`, verify
  the column exists and existing rows now have `[]`.

## Frontend Tests

Per existing convention, no unit tests v1. Manual smoke checklist additions:

1. Add an endpoint with `--tag` (CLI) or via UI dialog → tag chip shows in
   table.
2. Add a tag in the drawer → chip appears in table without manual refresh.
3. Remove a tag in the drawer → chip disappears.
4. Type in the search box → table filters live.
5. Pick a tag from the dropdown → table further narrows.
6. Search "gpt" in drawer → all three sections filter; counts update.
7. Available section is sorted fastest-first.
8. With drawer search active, "Test all" shows `(filtered: N)`.

## Migration / Backwards Compatibility

- Existing DBs gain `tags_json` column with `'[]'` default. No data lost.
- Existing API consumers that don't send `tags` get default `[]`.
- The CLI's `--tag` flag is optional; unaffected if you never use it.
- The new `PUT /tags` endpoint is purely additive.

## Out of Scope (explicit)

- Tag normalization (lowercasing, slugging). Tags are case-sensitive,
  exact strings.
- Tag rename / merge across endpoints (tier 2).
- Saving search state in URL hash (tier 2 if it matters).
- Bulk tag operations (tag N selected endpoints at once).
- Sortable column headers on the table (separate concern).
