import { Api, TelegramClient } from "telegram";
import { mtprotoConfig } from "./config.js";
import { loadStringSession } from "./session.js";

async function main() {
  const [firstName, lastName = ""] = process.argv.slice(2);

  if (!firstName) {
    throw new Error('Missing first name. Usage: npm run mtproto:set-profile -- "Weakipedia"');
  }

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

    await client.invoke(
      new Api.account.UpdateProfile({
        firstName,
        lastName,
      }),
    );

    const me = await client.getMe();
    const displayName = [me.firstName, me.lastName].filter(Boolean).join(" ");

    console.log("Telegram profile updated.");
    console.log(`Telegram display name: ${displayName || "(not set)"}`);
  } finally {
    await client.disconnect();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
