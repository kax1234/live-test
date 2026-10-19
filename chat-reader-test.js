const { LiveChat, RateLimitError } = require("youtube-chat-next");

// Standalone diagnostic only: this does not change the existing music stream.
const liveId = (process.env.YT_VIDEO_ID || "").trim();

if (!liveId) {
  console.error("Set YT_VIDEO_ID to the ID of a currently live KAXMOK video.");
  process.exit(1);
}

const chat = new LiveChat({ liveId }, 10000, "live");

chat.on("start", (id) => {
  console.log("[CHAT TEST] Connected to live video:", id);
});

chat.on("chat", (item) => {
  const message = (item.message || [])
    .map((part) => ("text" in part ? part.text : part.emojiText || ""))
    .join("");
  console.log(`[CHAT] ${item.author?.name || "viewer"}: ${message}`);
});

chat.on("end", (reason) => {
  console.log("[CHAT TEST] Ended:", reason || "no reason supplied");
});

chat.on("error", (err) => {
  if (err instanceof RateLimitError) {
    console.error("[CHAT TEST] YouTube rate-limited this connection; stop and retry later.");
  } else {
    console.error("[CHAT TEST] Reader error:", err?.message || err);
  }
});

(async () => {
  try {
    const started = await chat.start();
    if (!started) {
      console.error("[CHAT TEST] Could not start. Confirm the video is currently live and public.");
      process.exitCode = 1;
    }
  } catch (err) {
    console.error("[CHAT TEST] Startup failed:", err?.message || err);
    process.exitCode = 1;
  }
})();

process.on("SIGINT", () => {
  chat.stop("Stopped by user");
  process.exit(0);
});
