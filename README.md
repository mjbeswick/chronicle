# Chronicle

Chronicle is a calm Textual TUI for journaling and todo tracking.

It stores:

- journal entries as `data/journal/*.md` with sidecar metadata JSON
- todos as `data/todos/*.json` with append-only history

The journal view is a dated timeline that mixes manual notes with automatic todo activity such as created, completed, reopened, and due-date changes.

## Run

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

## Install as `chronicle`

The cleanest option is `pipx`:

```bash
brew install pipx
pipx install git+https://github.com/mjbeswick/chronicle.git
chronicle
```

For a local editable install on macOS with Homebrew Python:

```bash
/opt/homebrew/bin/python3 -m pip install --user --break-system-packages -e .
chronicle
```

If `chronicle` is installed but not found, add your user scripts directory to `PATH`:

```bash
echo 'export PATH="$(/opt/homebrew/bin/python3 -m site --user-base)/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## Controls

- `j` / `t` switch between Journal and Todos
- `n` create a new entry or todo
- `v` view the selected item
- `e` edit the selected item
- `d` delete the selected item with confirmation
- `space` toggle the selected todo
- `?` open help
- `q` quit

## Data layout

```text
data/
  journal/
    2026-04-21_morning-reflection.md
    2026-04-21_morning-reflection.json
  todos/
    todo_ab12cd34ef56.json
```

Chronicle does not sync data itself. Use git, Resilio, Syncthing, cloud storage, or another file-sync tool around the `data/` directory if you want syncing.

## Data location

An installed Chronicle stores data in your user app-data directory by default:

- macOS: `~/Library/Application Support/chronicle/data`

To override that location, set `CHRONICLE_HOME` before launching:

```bash
CHRONICLE_HOME=~/my-chronicle chronicle
```
