# Real KAXMOK song controls (separate branch)

This adds the secure command relay needed for a remote panel. It does not touch production.

## Important architecture
The GitHub-hosted Actions runner cannot accept inbound browser requests. The panel sends authenticated commands to a Cloudflare Worker; the running stream polls the Worker. Worker KV stores the one pending command and last status. The Worker serves the panel HTML from KV key `panel.html`.

## Cloudflare setup (free tier may be sufficient; verify current limits)
1. Create a Cloudflare Worker and deploy `control/worker.js`.
2. Create a Workers KV namespace and bind it as `KAXMOK_CONTROL`.
3. Add Worker secrets `PANEL_PASSWORD` and `RUNNER_TOKEN` (two long, different random strings).
4. Upload `control/panel.html` to KV as key `panel.html`.
5. Add GitHub Actions secrets `CONTROL_API_URL` (Worker URL) and `CONTROL_RUNNER_TOKEN` (same value as Worker RUNNER_TOKEN). Do not use the YouTube stream key for either.
6. The panel asks for PANEL_PASSWORD; it is sent as a Bearer token to Worker APIs. Use HTTPS only. Do not publish the password in HTML.

## Current scope
This relay is the command channel. The streaming runner must poll `/api/poll` using RUNNER_TOKEN and apply commands in the audio playback process. Do not merge or run production until the runner integration is complete and tested on a separate test stream. Never place secrets in browser code or repository files.
