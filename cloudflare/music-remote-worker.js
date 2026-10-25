/**
 * KAXMOK private music remote relay.
 * Bind a KV namespace as STATE and configure ADMIN_TOKEN + RUNNER_TOKEN secrets.
 */
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});
const bearer = (request) => request.headers.get("Authorization") || "";
const authorized = (request, token) => Boolean(token) && bearer(request) === `Bearer ${token}`;
const key = "relay-state";
const initial = { command: null, status: { track: "", paused: false, volume: 80, updatedAt: null }, nextId: 1 };

async function readState(env) {
  return (await env.STATE.get(key, "json")) || structuredClone(initial);
}
async function writeState(env, state) {
  await env.STATE.put(key, JSON.stringify(state));
}
function html() {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>KAXMOK • Music Remote</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#f4f7ff;background:#080c16}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 15% 0%,#13294b 0,transparent 48%),#080c16;display:grid;place-items:center;padding:22px}.wrap{width:min(760px,100%)}.brand{font-size:12px;letter-spacing:.22em;color:#8ebaff;font-weight:800}.panel{margin-top:14px;padding:clamp(20px,5vw,36px);border:1px solid #263650;background:#0c1423eF;border-radius:24px;box-shadow:0 25px 80px #0007}.top{display:flex;justify-content:space-between;gap:12px;align-items:center}h1{font-size:clamp(28px,5vw,42px);margin:8px 0 5px;letter-spacing:-.04em}.sub{color:#9baac2;margin:0}.pill{border:1px solid #324766;border-radius:999px;padding:7px 10px;color:#b7c8e4;font-size:12px;white-space:nowrap}.track{margin:28px 0 18px;padding:20px;border-radius:16px;background:#111e32;border:1px solid #263955}.muted{font-size:12px;color:#8ea2c1;text-transform:uppercase;letter-spacing:.12em}.song{font-size:18px;font-weight:700;overflow-wrap:anywhere;margin-top:8px}.status{margin-top:10px;color:#afc2df;font-size:13px}.controls{display:grid;grid-template-columns:1fr 1fr;gap:12px}.btn{border:1px solid #36547c;background:#142540;color:#f5f8ff;border-radius:14px;padding:17px 12px;font-weight:750;font-size:15px;cursor:pointer}.btn.primary{background:#d9e9ff;color:#0b1930;border-color:#d9e9ff}.btn:disabled{opacity:.5;cursor:wait}.form{margin-top:22px;display:flex;gap:10px}.form input{flex:1;min-width:0;background:#080f1c;color:white;border:1px solid #30425d;border-radius:10px;padding:12px}.small{font-size:12px;color:#8192ac;line-height:1.6;margin-top:18px}.msg{min-height:20px;color:#a9c8f7;font-size:13px;margin-top:12px}@media(max-width:430px){.top{align-items:flex-start;flex-direction:column}.controls{grid-template-columns:1fr 1fr}.btn{padding:15px 8px}}
</style></head><body><main class="wrap"><div class="brand">KAXMOK / PRIVATE CONTROL</div><section class="panel"><div class="top"><div><h1>Music remote</h1><p class="sub">Control the runner without YouTube chat commands.</p></div><span id="conn" class="pill">Not connected</span></div>
<div class="track"><div class="muted">Now playing</div><div id="track" class="song">Waiting for stream runner…</div><div id="state" class="status">Runner status not received yet.</div></div>
<div class="controls"><button class="btn primary" data-action="resume">▶ Resume</button><button class="btn" data-action="pause">Ⅱ Pause</button></div>
<div class="form"><input id="token" type="password" autocomplete="current-password" placeholder="Dashboard access token" aria-label="Dashboard access token"><button class="btn" id="save">Connect</button></div>
<div id="msg" class="msg" role="status"></div><p class="small">Private control: keep your access token secret. Commands are queued until the running GitHub Actions runner polls the relay. The stream runner must be active and configured for remote controls.</p>
</section></main>
<script>
const $=id=>document.getElementById(id);let token=sessionStorage.getItem("kaxmok_remote_token")||"";$("token").value=token;
async function api(path,body){const r=await fetch(path,{method:"POST",headers:{"content-type":"application/json","authorization":"Bearer "+token},body:JSON.stringify(body||{})});const data=await r.json().catch(()=>({error:"Invalid server response"}));if(!r.ok)throw Error(data.error||("Request failed ("+r.status+")"));return data}
async function status(){if(!token)return;$("conn").textContent="Connecting…";try{const d=await api("/api/status");$("conn").textContent=d.runnerOnline?"Runner connected":"Waiting for runner";$("track").textContent=d.status.track||"Track not reported yet";$("state").textContent=(d.status.paused?"Paused":"Playing") + " · Volume "+(d.status.volume??80)+"%"+(d.status.updatedAt?" · updated "+new Date(d.status.updatedAt).toLocaleTimeString():"");}catch(e){$("conn").textContent="Auth / relay error";$("msg").textContent=e.message}}
$("save").addEventListener("click",async()=>{token=$("token").value.trim();sessionStorage.setItem("kaxmok_remote_token",token);$("msg").textContent="";await status()});
document.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",async()=>{if(!token){$("msg").textContent="Enter your dashboard token first.";return}document.querySelectorAll(".btn").forEach(x=>x.disabled=true);try{const d=await api("/api/command",{action:b.dataset.action});$("msg").textContent=d.message||"Command queued.";await status()}catch(e){$("msg").textContent=e.message}finally{document.querySelectorAll(".btn").forEach(x=>x.disabled=false)}}));
if(token)status();setInterval(status,4000);
</script></body></html>`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return new Response(html(), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer" } });
    }
    if (request.method !== "POST") return json({ error: "Not found" }, 404);
    if (!env.STATE) return json({ error: "KV binding STATE is not configured." }, 503);
    if (url.pathname === "/api/poll") {
      if (!authorized(request, env.RUNNER_TOKEN)) return json({ error: "Unauthorized runner" }, 401);
      let body; try { body = await request.json(); } catch { return json({ error: "Invalid JSON" }, 400); }
      const state = await readState(env);
      if (body.status && typeof body.status === "object") {
        state.status = {
          track: String(body.status.track || "").slice(0, 240),
          paused: Boolean(body.status.paused),
          volume: Math.max(0, Math.min(100, Number(body.status.volume ?? 80) || 0)),
          updatedAt: new Date().toISOString(),
        };
      }
      if (body.ack && state.command && String(body.ack) === String(state.command.id)) state.command = null;
      await writeState(env, state);
      return json({ command: state.command });
    }
    if (!authorized(request, env.ADMIN_TOKEN)) return json({ error: "Unauthorized dashboard token" }, 401);
    if (url.pathname === "/api/status") {
      const state = await readState(env);
      const updated = state.status.updatedAt ? Date.parse(state.status.updatedAt) : 0;
      return json({ status: state.status, runnerOnline: Boolean(updated && Date.now() - updated < 15000) });
    }
    if (url.pathname === "/api/command") {
      let body; try { body = await request.json(); } catch { return json({ error: "Invalid JSON" }, 400); }
      if (!["pause", "resume"].includes(body.action)) return json({ error: "Only pause and resume are enabled." }, 400);
      const state = await readState(env);
      const id = String(state.nextId++);
      state.command = { id, action: body.action, createdAt: new Date().toISOString() };
      await writeState(env, state);
      return json({ ok: true, message: body.action === "pause" ? "Pause queued for runner." : "Resume queued for runner." });
    }
    return json({ error: "Not found" }, 404);
  },
};
