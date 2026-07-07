import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

dotenv.config();

const serviceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(serviceRoot, "../..");

function resolveFromServiceRoot(value: string) {
  return resolve(serviceRoot, value);
}

function readCredentialFile(filePath: string) {
  if (!existsSync(filePath)) {
    return {};
  }

  const text = readFileSync(filePath, "utf8");
  const apiId = text.match(/(?:App\s*)?api_id\s*[:=]\s*(\d+)/i)?.[1];
  const apiHash = text.match(/(?:App\s*)?api_hash\s*[:=]\s*([a-f0-9]+)/i)?.[1];

  return { apiId, apiHash };
}

const credentialFile = process.env.TELEGRAM_CREDENTIALS_FILE
  ? resolveFromServiceRoot(process.env.TELEGRAM_CREDENTIALS_FILE)
  : resolve(repoRoot, "telegram/TELEGRAM_APP.txt");

const fileCredentials = readCredentialFile(credentialFile);

const apiIdValue = process.env.TELEGRAM_API_ID ?? fileCredentials.apiId;
const apiHash = process.env.TELEGRAM_API_HASH ?? fileCredentials.apiHash;

if (!apiIdValue || !apiHash) {
  throw new Error(
    "Missing Telegram credentials. Set TELEGRAM_API_ID and TELEGRAM_API_HASH or provide telegram/TELEGRAM_APP.txt.",
  );
}

const apiId = Number.parseInt(apiIdValue, 10);

if (!Number.isInteger(apiId)) {
  throw new Error("TELEGRAM_API_ID must be an integer.");
}

export const mtprotoConfig = {
  apiId,
  apiHash,
  sessionFile: process.env.TELEGRAM_SESSION_FILE
    ? resolveFromServiceRoot(process.env.TELEGRAM_SESSION_FILE)
    : resolve(repoRoot, "telegram/sessions/weakipedia.session"),
};
