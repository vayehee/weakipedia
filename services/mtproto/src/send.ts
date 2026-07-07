import { TelegramClient } from "telegram";
import { mtprotoConfig } from "./config.js";
import { loadStringSession } from "./session.js";

const DEFAULT_TEST_MESSAGE =
  "Weakipedia MTProto test message. If you received this, outbound Telegram messaging is working.";

async function main() {
  const [recipient, ...messageParts] = process.argv.slice(2);
  const message = messageParts.join(" ").trim() || DEFAULT_TEST_MESSAGE;

  if (!recipient) {
    throw new Error(
      'Missing recipient. Usage: npm run mtproto:send -- "@telegram_username" "Optional message"',
    );
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

    const result = await client.sendMessage(recipient, { message });

    console.log("Telegram message sent.");
    console.log(`Recipient: ${recipient}`);
    console.log(`Message id: ${result.id}`);
  } finally {
    await client.disconnect();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
