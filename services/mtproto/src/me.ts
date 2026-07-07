import { TelegramClient } from "telegram";
import { mtprotoConfig } from "./config.js";
import { loadStringSession } from "./session.js";

async function main() {
  const client = new TelegramClient(
    loadStringSession(),
    mtprotoConfig.apiId,
    mtprotoConfig.apiHash,
    {
      connectionRetries: 5,
    },
  );

  try {
    await client.connect();

    if (!(await client.isUserAuthorized())) {
      throw new Error("Saved Telegram session is not authorized. Run npm run mtproto:login again.");
    }

    const me = await client.getMe();
    const displayName = [me.firstName, me.lastName].filter(Boolean).join(" ");

    console.log("MTProto session verified.");
    console.log(`Telegram user id: ${me.id?.toString()}`);
    console.log(`Telegram display name: ${displayName || "(not set)"}`);
    console.log(`Telegram username: ${me.username ? `@${me.username}` : "(not set)"}`);
  } finally {
    await client.disconnect();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
