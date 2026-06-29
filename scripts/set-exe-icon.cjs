/**
 * Set the Windows EXE icon on the built TermScope binary.
 *
 * Why this exists: `tauri build`'s build-script icon embedding caches the old
 * icon resource on this project (changing icons/icon.ico alone doesn't re-embed),
 * so the produced exe can ship the stale Tauri-placeholder icon. rcedit rewrites
 * just the PE icon resource on the final exe — the embedded frontend is untouched.
 *
 * Usage:  node scripts/set-exe-icon.cjs [exePath] [icoPath]
 * Defaults to the release exe + assets/termscope.ico.
 */
const path = require("path");

const mod = require("rcedit");
const rcedit = typeof mod === "function" ? mod : mod.rcedit || mod.default;

const root = path.resolve(__dirname, "..");
const exe =
  process.argv[2] ||
  path.join(root, "src-tauri", "target", "release", "termscope.exe");
const ico = process.argv[3] || path.join(root, "assets", "termscope.ico");

rcedit(exe, { icon: ico })
  .then(() => console.log(`icon set: ${ico} -> ${exe}`))
  .catch((e) => {
    console.error("set-exe-icon failed:", e);
    process.exit(1);
  });
