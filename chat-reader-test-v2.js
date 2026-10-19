const { LiveChat, RateLimitError } = require("youtube-chat-next");

// Separate diagnostic: discovers the current live broadcast by channel ID.
// Does not modify the existing KAXMOK music-stream files.
const channelId = (process.env.YT_CHANNEL_ID || "").trim();

if (!channelId) {
  console.error("Set YT_CHANNEL_ID to the YouTube channel ID.");
  process.exit(1);
}

const chat = new LiveChat({ channelId }, 10000, "live");

chat.on("start", (id) => console.log("[CHAT TEST V2] Connected:", id));
chat.on("chat", (item) => {
  const message = (item.message || [])
    .map((part) => ("text" in part ? part.text : part.emojiText || ""))
    .join("");
  console.log(`[CHAT] ${item.author?.name || "viewer"}: ${message}`);
});
chat.on("end", (reason) => console.log("[CHAT TEST V2] Ended:", reason || "no reason supplied"));
chat.on("error", (err) => {
  console.error("[CHAT TEST V2] Reader error:", err instanceof RateLimitError ? "YouTube rate-limited this connection" : (err?.message || err));
});

(async () => {
  try {
    const started = await chat.start();
    if (!started) {
      console.error("[CHAT TEST V2] Could not find/start a live chat for this channel.");
      process.exitCode = 1;
    }
  } catch (err) {
    console.error("[CHAT TEST V2] Startup failed:", err?.message || err);
    process.exitCode = 1;
  }
})();

process.on("SIGINT", () => {
  chat.stop("Stopped by user");
  process.exit(0);
});
