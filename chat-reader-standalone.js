import { Innertube } from "youtubei.js";

const VIDEO_ID = (process.env.YT_VIDEO_ID || "nhCCCwvYGO0").trim();
const RUN_SECONDS = Math.max(30, Math.min(600, Number(process.env.RUN_SECONDS || 180)));
const RECONNECT_DELAY_MS = 5000;
const SEEN_LIMIT = 2000;

if (!/^[A-Za-z0-9_-]{11}$/.test(VIDEO_ID)) {
  console.error("[KAXMOK CHAT] Invalid YT_VIDEO_ID; expected an 11-character YouTube video ID.");
  process.exit(2);
}

const seen = new Set();
let stopping = false;
let emitted = 0;

function log(message) {
  console.log(new Date().toISOString() + " [KAXMOK CHAT] " + message);
}
function messageText(message) {
  if (typeof message === "string") return message;
  if (message?.text) return String(message.text);
  if (Array.isArray(message?.runs)) {
    return message.runs.map(run => run.text || run.emoji?.shortcuts?.[0] || "").join("");
  }
  return "";
}
function handleAction(action) {
  if (!action || action.type !== "AddChatItemAction") return;
  const item = action.item;
  if (!item) return;
  const type = item.type || item.constructor?.type || "";
  if (!/LiveChat(TextMessage|PaidMessage|PaidSticker|MembershipItem|ViewerEngagementMessage|PlaceholderItem)/.test(type)) return;

  const id = String(item.id || "");
  if (id && seen.has(id)) return;
  if (id) {
    seen.add(id);
    if (seen.size > SEEN_LIMIT) seen.delete(seen.values().next().value);
  }

  const author = String(item.author?.name || item.author_name || "unknown").replace(/[\r\n\t]/g, " ").slice(0, 100);
  const text = messageText(item.message || item.header || item.text).replace(/[\r\n\t]/g, " ").slice(0, 1000);
  if (!text && !/PaidSticker|MembershipItem/.test(type)) return;
  emitted++;
  // JSON lines are safe to parse downstream; viewer text is data, never executable code.
  console.log(JSON.stringify({
    event: "chat_message",
    video_id: VIDEO_ID,
    type,
    author,
    text,
    message_id: id || null,
    timestamp: item.timestamp || null
  }));
}

async function runOnce() {
  log("Connecting to YouTube chat for video " + VIDEO_ID);
  const yt = await Innertube.create({ lang: "en", location: "US" });
  const info = await yt.getInfo(VIDEO_ID);
  const chat = info.getLiveChat();
  if (!chat) throw new Error("No live-chat object was returned. Confirm the stream is live and chat is enabled.");

  let lastError = null;
  chat.on("chat-update", action => {
    try { handleAction(action); }
    catch (error) { log("Skipped malformed chat action: " + (error?.message || String(error))); }
  });
  chat.on("error", error => {
    lastError = error instanceof Error ? error : new Error(String(error));
    log("Chat error: " + lastError.message);
  });
  chat.on("start", () => log("Chat listener started."));
  chat.on("end", () => log("Chat listener ended."));
  chat.start();

  const endAt = Date.now() + RUN_SECONDS * 1000;
  while (!stopping && Date.now() < endAt) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    if (lastError) {
      try { chat.stop(); } catch {}
      throw lastError;
    }
  }
  try { chat.stop(); } catch {}
  log("Session ended. Messages emitted this session: " + emitted);
}

process.on("SIGTERM", () => { stopping = true; });
process.on("SIGINT", () => { stopping = true; });

async function main() {
  const deadline = Date.now() + RUN_SECONDS * 1000;
  let attempt = 0;
  while (!stopping && Date.now() < deadline) {
    attempt++;
    try {
      await runOnce();
      if (stopping || Date.now() >= deadline) break;
      log("Reader session ended; reconnecting after delay.");
    } catch (error) {
      log("Attempt " + attempt + " failed: " + (error?.message || String(error)));
    }
    if (!stopping && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, Math.min(RECONNECT_DELAY_MS, Math.max(0, deadline - Date.now()))));
    }
  }
  log("Reader stopped cleanly.");
}

main().catch(error => {
  log("Fatal error: " + (error?.stack || String(error)));
  process.exitCode = 1;
});
