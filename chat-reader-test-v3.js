import { Innertube } from "youtubei.js";

const VIDEO_ID = process.env.YT_VIDEO_ID || "nhCCCwvYGO0";
const WATCH_URL = `https://www.youtube.com/watch?v=${VIDEO_ID}`;

function log(label, value) {
  console.log(`[CHAT TEST V3] ${label}: ${value}`);
}

async function main() {
  log("Video ID", VIDEO_ID);

  // Test basic outbound access independently of the chat library.
  try {
    const response = await fetch(WATCH_URL, {
      headers: {
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
        "accept-language": "en-US,en;q=0.9"
      },
      signal: AbortSignal.timeout(15000)
    });
    const html = await response.text();
    log("Watch page HTTP", response.status);
    log("Watch page bytes", Buffer.byteLength(html));
    log("Page mentions video ID", html.includes(VIDEO_ID));
    log("Page has live-chat markers", /liveChatRenderer|liveChat/|continuation/i.test(html));
    log("Page title snippet", (html.match(/<title[^>]*>(.*?)<\/title>/is)?.[1] || "not found").replace(/\s+/g, " ").slice(0, 180));
  } catch (error) {
    log("Watch page fetch error", error?.stack || error);
  }

  // Independently test YouTube.js video-info and live-chat discovery.
  try {
    log("Initializing youtubei.js", "starting");
    const yt = await Innertube.create({ lang: "en", location: "US" });
    const info = await yt.getInfo(VIDEO_ID);
    log("Video info", "retrieved");
    log("Basic info", JSON.stringify({
      title: info.basic_info?.title || null,
      is_live: info.basic_info?.is_live ?? null,
      is_upcoming: info.basic_info?.is_upcoming ?? null
    }));

    const chat = info.getLiveChat();
    if (!chat) {
      log("Live chat object", "not available for this video");
      process.exitCode = 2;
      return;
    }

    log("Live chat object", "created");
    let gotMessage = false;
    chat.on("chat-update", (update) => {
      const actions = update?.actions || [];
      for (const action of actions) {
        const item = action?.item;
        const message = item?.message?.text || item?.message || "";
        const author = item?.author?.name || "unknown";
        if (message) {
          gotMessage = true;
          log("Sample chat message", `${author}: ${String(message).slice(0, 160)}`);
        }
      }
    });
    chat.on("error", (error) => log("Chat event error", error?.message || error));
    chat.start();
    log("Chat started", "waiting up to 45 seconds for events");

    await new Promise((resolve) => setTimeout(resolve, 45000));
    try { chat.stop(); } catch {}
    log("Chat event received", gotMessage);
    log("Diagnostic", gotMessage ? "SUCCESS: live chat event received" : "Video info/chat setup worked, but no chat message arrived during the test window");
    if (!gotMessage) process.exitCode = 2;
  } catch (error) {
    log("youtubei.js error", error?.stack || error);
    process.exitCode = 1;
  }
}

main().catch((error) => {
  log("Fatal error", error?.stack || error);
  process.exitCode = 1;
});
