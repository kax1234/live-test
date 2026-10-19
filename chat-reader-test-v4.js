import { Innertube } from "youtubei.js";

const VIDEO_ID = process.env.YT_VIDEO_ID || "nhCCCwvYGO0";
const log = (label, value) => console.log("[CHAT TEST V4] " + label + ": " + value);

async function main() {
  log("Video ID", VIDEO_ID);

  try {
    const response = await fetch("https://www.youtube.com/watch?v=" + VIDEO_ID, {
      headers: { "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36" },
      signal: AbortSignal.timeout(15000)
    });
    const html = await response.text();
    log("Watch page HTTP", response.status);
    log("Watch page bytes", Buffer.byteLength(html));
    log("Has live chat renderer marker", html.includes("liveChatRenderer"));
    log("Has live chat continuation marker", html.includes("continuation"));
  } catch (e) {
    log("Watch page fetch error", e?.stack || String(e));
  }

  try {
    const yt = await Innertube.create({ lang: "en", location: "US" });
    const info = await yt.getInfo(VIDEO_ID);
    log("Video info retrieved", true);
    log("Basic info keys", Object.keys(info.basic_info || {}).join(",") || "(none)");
    log("Basic title", info.basic_info?.title || "(missing)");
    log("Basic is_live", String(info.basic_info?.is_live ?? "(missing)"));

    const chat = info.getLiveChat();
    if (!chat) {
      log("Live chat", "not available");
      process.exitCode = 2;
      return;
    }

    let eventCount = 0;
    chat.on("chat-update", (update) => {
      eventCount++;
      const actions = update?.actions || [];
      log("Chat update event", "count=" + eventCount + ", actions=" + actions.length);
      for (const action of actions.slice(0, 3)) {
        log("Action type", action?.type || action?.constructor?.name || "(unknown)");
      }
    });
    chat.on("error", (e) => log("Chat error event", e?.stack || e?.message || String(e)));
    log("Starting chat", "45-second diagnostic");
    chat.start();
    await new Promise(resolve => setTimeout(resolve, 45000));
    try { chat.stop(); } catch {}
    log("Chat update events received", eventCount);
    log("Result", eventCount ? "Chat updates received; inspect action types above" : "No chat updates; see parser/runtime warnings above");
    if (!eventCount) process.exitCode = 2;
  } catch (e) {
    log("youtubei.js error", e?.stack || String(e));
    process.exitCode = 1;
  }
}

main().catch(e => { log("Fatal", e?.stack || String(e)); process.exitCode = 1; });
