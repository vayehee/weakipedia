import { existsSync, readFileSync } from "node:fs";
import { StringSession } from "telegram/sessions/index.js";
import { mtprotoConfig } from "./config.js";

export function loadStringSession() {
  if (!existsSync(mtprotoConfig.sessionFile)) {
    throw new Error(
      `No Telegram session found at ${mtprotoConfig.sessionFile}. Run npm run mtproto:login first.`,
    );
  }

  const session = readFileSync(mtprotoConfig.sessionFile, "utf8").trim();

  if (!session) {
    throw new Error(
      `Telegram session file is empty at ${mtprotoConfig.sessionFile}. Run npm run mtproto:login again.`,
    );
  }

  return new StringSession(session);
}
