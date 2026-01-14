# Downloads Organizer

Organizes files in your Downloads folder into subfolders by file type. It will also watch for new downloads.

## Requirements

- Python 3.11+ (recommended) or Python 3.8+ with `tomli`
- Optional: `watchdog` for efficient file watching (falls back to polling if missing)

## Setup

```bash
cd /Users/ekko/Developer/codex_projects/downloads_organiser
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python organiser.py
```

The script looks for `config.toml` in the current directory by default. Customize the mappings and settings there.

## LaunchAgent (macOS)

This repo includes a simple LaunchAgent you can install to start the watcher on login.

1) Edit `com.ekko.downloads-organiser.plist` to match your paths (and your venv Python if you use one).
2) Install and load it:

```bash
cp /Users/ekko/Developer/codex_projects/downloads_organiser/com.ekko.downloads-organiser.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.ekko.downloads-organiser.plist
```

To stop it later:

```bash
launchctl unload -w ~/Library/LaunchAgents/com.ekko.downloads-organiser.plist
```

## Configuration

Edit `config.toml` to change the Downloads folder, file-type mappings, and behavior flags. For example:

```toml
downloads_dir = \"~/Downloads\"
other_folder = \"Other\"

[mappings]
Images = [\"jpg\", \"png\"]
```

## Notes

- Only files directly inside the Downloads folder are moved.
- Files with extensions like `.download` or `.crdownload` are skipped.
- If a filename already exists in the destination, a numeric suffix is added.
