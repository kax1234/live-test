# KAXMOK private music remote dashboard

This is a private, separate control plane for the existing GitHub Actions stream runner. It adds **Pause** and **Resume** buttons without changing the stream's publishing pipeline. It is not live until you deploy the Worker and configure the two GitHub repository secrets.

## 1. Deploy the relay (Cloudflare Workers free tier)

1. Create a Cloudflare Worker named `kaxmok-music-remote`.
2. Paste the contents of `cloudflare/music-remote-worker.js` into its editor and deploy it.
3. In **Workers & Pages → your Worker → Settings → Bindings**, add a **KV namespace** binding named exactly `STATE`. Create a new namespace, e.g. `KAXMOK_MUSIC_REMOTE`.
4. In **Settings → Variables and Secrets**, add these as **Secrets** (not plain text variables):
   - `ADMIN_TOKEN`: a long, unique random password used only by the dashboard.
   - `RUNNER_TOKEN`: a different long, unique random password used only by the GitHub Actions runner.
5. Deploy again after binding/secrets are configured. Open the Worker URL; the private dashboard will ask for `ADMIN_TOKEN`.

Do not put either token in this repository, the dashboard HTML, screenshots, or chat. The dashboard keeps its token only in the current browser tab's session storage.

## 2. Connect the existing runner

In GitHub: **kax1234/live-test → Settings → Secrets and variables → Actions → New repository secret**, add:

- `CONTROL_API_URL`: the base Worker URL, e.g. `https://kaxmok-music-remote.<your-subdomain>.workers.dev` (no trailing slash).
- `CONTROL_RUNNER_TOKEN`: the exact same value as the Worker `RUNNER_TOKEN` secret.

The workflow already passes these secrets to `chat_stream.py`; the runner polls the Worker every two seconds. The Worker reports the runner as connected when it has checked in during the last 15 seconds.

## 3. Start a fresh runner

GitHub Actions → **KAXMOK Live Songs** → **Run workflow**. The running job does not automatically receive new repository secret values, so start a fresh run after adding the secrets. Do not run two stream jobs at once: both would publish to the same YouTube stream key.

Open the Worker URL in your browser. When it says **Runner connected**, Pause and Resume enqueue commands; the runner applies them on its next poll. Pausing sends silence to the existing audio pipeline, so the RTMP publisher and video remain connected. Resume restarts the current track from the beginning (the runner's current implementation).

## Security and behavior

- The dashboard's `ADMIN_TOKEN` and runner's `RUNNER_TOKEN` are separate.
- Worker API responses use `no-store`; only authenticated callers can read status or queue commands.
- If the runner is stopped, controls queue but cannot take effect until a runner is active.
- KV is eventually consistent; the runner acknowledges a command after applying it. Test with a short pause/resume before relying on it.
- No secrets or live stream key are included in the repository.
