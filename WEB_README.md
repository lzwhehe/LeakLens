# LeakLens Web

LeakLens Web is the browser-first control panel for the scanner.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8787.

## What The Web App Controls

- GitHub token input for the scanner process
- Version selection with the stable engine as the Web default
- Optional proxy and Pastebin key
- Source toggles for Gist, GitLab, Pastebin, SearchCode, Realtime, and all sources
- Start and stop controls for the scanner subprocess
- Real-time scanner logs
- SQLite-backed statistics, charts, filters, and CSV export

## Deployment Note

Run the full Web app on a machine that can keep a Python process alive, such as a local machine, VPS, Docker host, Railway, Fly.io, or Render. Vercel is only suitable for showing exported results, not for running the long-lived scanner.
