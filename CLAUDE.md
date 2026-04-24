# Chronicle — Project Notes for Claude

## Data Model — One `Item`, Four Lenses

There is exactly one persisted entity (`models.item.Item`) with optional time coordinates. Journal / Todos / Notes / Calendar are **lenses** — pure filter predicates over the single item store. Do not add entity-specific types; extend `Item` or add new lens predicates instead.

```
Item
  id, title, body, tags, parent_id
  created_at, updated_at
  at:      datetime | None   # anchor moment (past = recorded, future = scheduled)
  due:     date | None       # deadline (day-precision)
  done_at: datetime | None   # marked complete; None = open
```

Lens predicates (on `Item`):

| Lens | Predicate |
|---|---|
| Journal  | `(at and at <= now) or done_at is not None` |
| Todos    | `done_at is None and not (at and at <= now) and not in_notes` |
| Calendar | `at or due` |
| Notes    | `at is None and due is None and done_at is None and body.strip()` |

Items legitimately appear in multiple lenses (a future todo with a due date shows in Todos *and* Calendar). Storage: one JSON file per item in `items/`, via `ItemStore` in `models/storage.py`. App-side adapter `ChronicleStorageAdapter` in `app/storage.py` exposes `list_items`, `create_item`, `update_item`, `delete_item`, `toggle_done`, `update_tags`.

Unified form: `ItemFormScreen` in `app/forms.py` — title, at, due, tags, body, done. `voice_create_for_active_tab` pre-fills the right fields for the active tab.

## Keybinding Scheme

Chronicle follows a strict split between **ctrl+key** (tab switching and app-level navigation) and **plain keys** (view-specific actions). Preserve this when adding bindings.

### Tabs (app-level, ctrl-modified)
- `ctrl+j` — Journal
- `ctrl+t` — Todos
- `ctrl+n` — Notes
- `ctrl+c` — Calendar (single press; also armed quit-trigger — see below)

### Quit
- `q` — quit immediately
- `escape` — quit from main views; closes the modal when one is open (screen bindings win)
- `ctrl+c` twice within `CTRL_C_DOUBLE_WINDOW` (1.5s) — quit from anywhere, including modals. Single `ctrl+c` on main view also switches to Calendar, which is intentional.

### App-level overlays
- `ctrl+l` — cycle Journal layout preset: **Dates | Table / Content** → **Dates | Table** → **Dates | Table | Content** (three columns) → **Table only**. Dispatches to `JournalView.cycle_layout()`; only active when the Journal tab is showing.

### View actions (plain keys; context depends on active tab)
- `n` — new item (journal entry / todo / note)
- `N` — new subtask (todos)
- `v` — view selected
- `e` — edit selected
- `d` — delete selected
- `f` — filter
- `x` — toggle todo done/open
- `#` — edit tags
- `[` / `]` — toggle tree / content panes (journal)
- `?` — help screen

### Calendar (`ctrl+c` tab)
- Arrow keys move a day cursor (`←/→` ±1 day, `↑/↓` ±7 days).
- `shift+←/→` — previous/next year (`h`/`l` also bound for muscle memory).
- `y` — jump-to-year modal. `home` — jump to today.
- `enter` or mouse click on a date — routes:
  - past or today → switch to Journal, filtered to that single day via `FilterSpec(date_from=date_to=…)`.
  - future → open `TodoFormScreen(initial_due_date=…)`; on save, create the todo on that date.
- Cursor styling: `reverse cyan`. If cursor coincides with today, it takes on an accent background to distinguish from the plain-today `reverse` marker.

### Voice input
- **Hold space** on any main view — record → release → transcribe → new-item modal pre-filled with transcript.
- Short space tap is a no-op (intentionally — space is the hold gesture).
- Hold space inside a form field (`VoiceInput` / `VoiceTextArea`) inserts the transcript into that field.
- Pressing any non-space key during recording aborts and discards the WAV.

### Status bar
- When any `ctrl+<key>` is pressed, the status bar flashes a ctrl overview for `CTRL_HINT_WINDOW` (1.8s) then reverts via `_refresh_status`.
- Voice states (`recording`, `transcribing`) override the hint row with coloured banners.

## Implementation Anchors

- Tab + quit bindings: `app/app.py` `ChronicleApp.BINDINGS`.
- Per-tab hint rows: `app/app.py` `_refresh_status`.
- Help text: `app/forms.py` `_help_shortcuts`.
- View-level hold-space handler: `app/voice.py` `ViewVoiceHoldHandler`.
- Voice-create dispatcher: `app/app.py` `voice_create_for_active_tab`.
- Transcription subprocess (Swift binary, `proc.wait` + temp-file stdout, log at `~/Library/Logs/chronicle-voice.log`): `app/voice.py` `transcribe_file`.

## Conventions When Changing Keybindings

1. Keep the ctrl/plain split — don't bind single letters to tab switches, and don't bind plain ctrl-letters to view actions.
2. Any change to tab shortcuts must update the per-tab hint chips in `_refresh_status`, the help text in `_help_shortcuts`, and the ctrl-overview hints in `_show_ctrl_hints`.
3. If you rebind `x`, update both the app-level binding (`toggle_todo`) and the TodosView `BINDINGS` (the priority-true view-level mirror).
