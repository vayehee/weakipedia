import { mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { stdin as input, stdout as output } from "node:process";
import readline from "node:readline/promises";
import { TelegramClient } from "telegram";
import { StringSession } from "telegram/sessions/index.js";
import { mtprotoConfig } from "./config.js";

function readSession() {
  if (!existsSync(mtprotoConfig.sessionFile)) {
    return "";
  }

  return readFileSync(mtprotoConfig.sessionFile, "utf8").trim();
}

function saveSession(session: string) {
  mkdirSync(dirname(mtprotoConfig.sessionFile), { recursive: true });
  writeFileSync(mtprotoConfig.sessionFile, session, { encoding: "utf8", mode: 0o600 });
}

async function main() {
  const rl = readline.createInterface({ input, output });
  const session = new StringSession(readSession());
  const client = new TelegramClient(session, mtprotoConfig.apiId, mtprotoConfig.apiHash, {
    connectionRetries: 5,
  });

  try {
    await client.start({
      phoneNumber: async () => rl.question("Telegram phone number: "),
      phoneCode: async () => rl.question("Telegram login code: "),
      password: async () => rl.question("Telegram 2FA password, if prompted: "),
      onError: (error) => {
        console.error(error);
      },
    });

    const me = await client.getMe();
    saveSession(session.save());

    console.log("MTProto login verified.");
    console.log(`Telegram user id: ${me.id?.toString()}`);
    console.log(`Session file: ${mtprotoConfig.sessionFile}`);
  } finally {
    rl.close();
    await client.disconnect();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
