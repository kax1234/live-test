import { Innertube, YTNodes } from "youtubei.js";

const videoId = process.argv[2] || process.env.YT_VIDEO_ID;
const log = (...args) => console.error("[CHAT NODE]", ...args);

function textOf(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  // Preserve YouTube's run structure so custom channel/member emojis can be drawn
  // as images by the Python overlay instead of being silently discarded.
  if (Array.isArray(value.runs)) {
    return value.runs.map((run) => {
      if (typeof run?.text === "string") return run.text;
      const emoji = run?.emoji || run?.attachment?.emoji;
      const thumbs = emoji?.image?.thumbnails || emoji?.thumbnails || [];
      const url = thumbs.length ? thumbs[thumbs.length - 1]?.url : "";
      if (url && /^https:\/\//i.test(url)) return ` ⟦YTEMOJI:${url}⟧ `;
      const shortcut = emoji?.shortcuts?.[0] || emoji?.emoji_id || "";
      return shortcut ? String(shortcut) : "";
    }).join("");
  }
  if (typeof value.text === "string") return value.text;
  if (Array.isArray(value.content)) return value.content.map(textOf).join("");
  return "";
}

async function main() {
  if (!videoId) throw new Error("Missing video ID");
  log("Connecting to live chat for", videoId);
  const yt = await Innertube.create({ lang: "en", location: "US" });
  const info = await yt.getInfo(videoId);
  const chat = info.getLiveChat();
  if (!chat) throw new Error("youtubei.js did not return a live-chat object");

  chat.on("chat-update", (action) => {
    try {
      let item = action?.item;
      if (!item && action?.as && YTNodes?.AddChatItemAction) {
        try {
          if (action.is?.(YTNodes.AddChatItemAction)) item = action.as(YTNodes.AddChatItemAction).item;
        } catch {}
      }
      if (!item) return;
      const author = textOf(item.author?.name || item.author_name) || "viewer";
      const message = textOf(item.message || item.text);
      if (!message) return;
      const avatar = item.author?.thumbnails?.[0]?.url
        || item.author?.thumbnail?.[0]?.url
        || item.author?.image?.[0]?.url
        || null;
      process.stdout.write(JSON.stringify({ type: "message", author, message, avatar_url: avatar }) + "\n");
    } catch (error) {
      log("Could not parse chat action:", error?.stack || String(error));
    }
  });
  chat.on("error", (error) => {
    process.stdout.write(JSON.stringify({ type: "error", message: error?.message || String(error) }) + "\n");
  });
  chat.on("start", () => log("Live chat started"));
  chat.start();
  log("Live-chat listener is running");
  const shutdown = () => { try { chat.stop(); } catch {} process.exit(0); };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((error) => {
  log("Fatal:", error?.stack || String(error));
  process.stdout.write(JSON.stringify({ type: "error", message: error?.message || String(error) }) + "\n");
  process.exitCode = 1;
});
