import { Innertube, YTNodes } from "youtubei.js";

const VIDEO_ID = process.env.YT_VIDEO_ID || "nhCCCwvYGO0";
const log = (label, value) => console.log("[CHAT TEST V5] " + label + ": " + value);

function safeText(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value.toString === "function") return value.toString();
  return String(value);
}

async function main() {
  log("Video ID", VIDEO_ID);
  const yt = await Innertube.create({ lang: "en", location: "US" });
  const info = await yt.getInfo(VIDEO_ID);
  log("Video info", "retrieved");
  log("Basic info keys", Object.keys(info.basic_info || {}).join(",") || "(none)");

  const chat = info.getLiveChat();
  if (!chat) {
    log("Result", "No live-chat object returned");
    process.exitCode = 2;
    return;
  }

  let eventCount = 0;
  let messageCount = 0;

  chat.on("start", () => log("Chat start event", "received"));
  chat.on("metadata-update", (metadata) => {
    log("Metadata update", JSON.stringify({
      keys: metadata && typeof metadata === "object" ? Object.keys(metadata).slice(0, 20) : [],
      sample: safeText(metadata).slice(0, 250)
    }));
  });
  chat.on("error", (error) => log("Chat error", error?.stack || error?.message || String(error)));
  chat.on("chat-update", (action) => {
    eventCount++;
    const type = action?.type || action?.constructor?.type || action?.constructor?.name || "(unknown)";
    log("Action event", "count=" + eventCount + ", type=" + type);
    if (eventCount <= 5) {
      try {
        log("Action keys", Object.keys(action || {}).join(",") || "(none)");
        log("Action sample", JSON.stringify(action, (key, value) => {
          if (key === "endpoint" || key === "command" || key === "tracking_params") return undefined;
          if (typeof value === "string" && value.length > 300) return value.slice(0, 300);
          return value;
        }).slice(0, 1200));
      } catch (e) {
        log("Action sample error", String(e));
      }
    }

    let item = action?.item;
    if (!item && action?.as && YTNodes?.AddChatItemAction) {
      try {
        if (action.is?.(YTNodes.AddChatItemAction)) item = action.as(YTNodes.AddChatItemAction).item;
      } catch {}
    }
    if (item) {
      const author = safeText(item.author?.name || item.author_name || "unknown");
      const message = safeText(item.message || item.text || "");
      if (message) {
        messageCount++;
        log("CHAT MESSAGE", author + ": " + message);
      } else {
        log("Chat item without simple message field", item.type || item.constructor?.name || "(unknown)");
      }
    }
  });

  log("Starting chat", "wait 45 seconds");
  chat.start();
  await new Promise(resolve => setTimeout(resolve, 45000));
  try { chat.stop(); } catch {}
  log("Summary", JSON.stringify({ eventCount, messageCount }));
  log("Result", messageCount > 0 ? "SUCCESS: read message text" : eventCount > 0 ? "Actions arrived but message extraction needs adjustment" : "No chat actions arrived");
  if (messageCount === 0) process.exitCode = 2;
}

main().catch(error => {
  log("Fatal", error?.stack || String(error));
  process.exitCode = 1;
});
