export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = { "Access-Control-Allow-Origin": url.origin, "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type,Authorization", "Cache-Control": "no-store" };
    if (request.method === "OPTIONS") return new Response(null, {headers:cors});
    const auth = request.headers.get("Authorization") || "";
    const panelOK = auth === "Bearer " + env.PANEL_PASSWORD;
    const runnerOK = auth === "Bearer " + env.RUNNER_TOKEN;
    const json = (data, status=200) => new Response(JSON.stringify(data), {status,headers:{...cors,"Content-Type":"application/json"}});
    if (url.pathname === "/api/status") {
      if (!panelOK && !runnerOK) return json({error:"unauthorized"},401);
      return json({ok:true, command: await env.KAXMOK_CONTROL.get("command","json"), status: await env.KAXMOK_CONTROL.get("status","json")});
    }
    if (url.pathname === "/api/command" && request.method === "POST") {
      if (!panelOK) return json({error:"unauthorized"},401);
      const body = await request.json();
      const allowed = new Set(["next","previous","pause","resume","volume","choose"]);
      if (!allowed.has(body.action)) return json({error:"invalid action"},400);
      if (body.action === "volume" && (!Number.isFinite(body.value) || body.value<0 || body.value>100)) return json({error:"volume must be 0-100"},400);
      if (body.action === "choose" && (typeof body.song !== "string" || !/^[\w .()\-]+\.mp3$/i.test(body.song))) return json({error:"invalid song"},400);
      const command = {id:crypto.randomUUID(), action:body.action, value:body.value, song:body.song, created:Date.now()};
      await env.KAXMOK_CONTROL.put("command",JSON.stringify(command),{expirationTtl:120});
      return json({ok:true,command});
    }
    if (url.pathname === "/api/poll" && request.method === "POST") {
      if (!runnerOK) return json({error:"unauthorized"},401);
      const body = await request.json();
      const command = await env.KAXMOK_CONTROL.get("command","json");
      if (body.ack && command && body.ack === command.id) await env.KAXMOK_CONTROL.delete("command");
      if (body.status) await env.KAXMOK_CONTROL.put("status",JSON.stringify(body.status),{expirationTtl:90});
      return json({command: command && command.created > Date.now()-120000 ? command : null});
    }
    if (url.pathname === "/" || url.pathname === "/panel") {
      return new Response(await env.KAXMOK_CONTROL.get("panel.html") || "Upload control/panel.html into KV as key panel.html, or use the repository HTML file.",{headers:{"Content-Type":"text/html;charset=UTF-8"}});
    }
    return json({error:"not found"},404);
  }
};