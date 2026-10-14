import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, readdir, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import type { NextRequest } from "next/server";

export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24;
const TOKEN_PATTERN = /^(\d+)\.([a-f0-9]{64})\.([a-f0-9]{64})$/;

// This directory is supplied at runtime and must not enter Next build tracing.
// A shared private directory makes logout effective across Next's route/proxy
// processes and restarts. This local single-node adapter is not platform SSO.
function sessionDirectory(): string {
  const directory = process.env.HINDSIGHT_CP_SESSION_DIR;
  if (!directory || !path.isAbsolute(directory)) {
    throw new Error("Session storage must be an absolute private directory");
  }
  return directory;
}

export function publicOrigin(): string | null {
  try {
    const raw = process.env.HINDSIGHT_CP_PUBLIC_ORIGIN;
    if (!raw) return null;
    const url = new URL(raw);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    )
      return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function protectedMode(): boolean {
  return process.env.HINDSIGHT_CP_AUTH_MODE !== "bootstrap";
}

export function authConfigured(): boolean {
  const mode = process.env.HINDSIGHT_CP_AUTH_MODE;
  return (
    (!mode || mode === "local") &&
    Boolean(
      process.env.HINDSIGHT_CP_ACCESS_KEY &&
      publicOrigin() &&
      process.env.HINDSIGHT_CP_SESSION_DIR &&
      path.isAbsolute(process.env.HINDSIGHT_CP_SESSION_DIR)
    )
  );
}

export function trustedMutation(request: NextRequest): boolean {
  // Do not derive trust from client-supplied forwarded headers. Browsers must
  // reach the configured origin, including login and multipart uploads.
  const origin = publicOrigin();
  return Boolean(
    origin &&
    request.headers.get("origin") === origin &&
    request.headers.get("host") === new URL(origin).host
  );
}

function instanceBinding(): string {
  return `${publicOrigin() || "unconfigured"}\n${process.env.NEXT_PUBLIC_BASE_PATH || ""}`;
}

export function sessionCookieName(): string {
  // Cookies do not isolate ports. Bind the name to this UI origin so opening
  // another local instance cannot overwrite an existing experience's session.
  // Stable session namespace, bound to instance identity rather than presentation branding.
  return `agentstratum_${createHash("sha256").update(instanceBinding()).digest("hex").slice(0, 16)}`;
}

function signature(payload: string, accessKey: string): string {
  return createHmac("sha256", accessKey).update(`${instanceBinding()}\n${payload}`).digest("hex");
}

export async function createSessionToken(accessKey: string): Promise<string> {
  const directory = sessionDirectory();
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const now = Math.floor(Date.now() / 1000);
  const files = await readdir(directory);
  // Expired records are reclaimed on login; there is no background timer or
  // process-local registry which could disagree with another Next worker.
  for (const file of files) {
    if (
      /^\d+\.[a-f0-9]{64}$/.test(file) &&
      now - Number(file.split(".")[0]) >= SESSION_MAX_AGE_SECONDS
    ) {
      await unlink(path.join(/* turbopackIgnore: true */ directory, file)).catch(
        (error: NodeJS.ErrnoException) => {
          if (error.code !== "ENOENT") throw error;
        }
      );
    }
  }
  const payload = `${now}.${randomBytes(32).toString("hex")}`;
  await writeFile(path.join(/* turbopackIgnore: true */ directory, payload), "", {
    flag: "wx",
    mode: 0o600,
  });
  return `${payload}.${signature(payload, accessKey)}`;
}

export async function verifySessionToken(
  token: string | undefined,
  accessKey: string
): Promise<boolean> {
  const match = token?.match(TOKEN_PATTERN);
  if (!match) return false;
  const issuedAt = Number(match[1]);
  const age = Math.floor(Date.now() / 1000) - issuedAt;
  if (!Number.isSafeInteger(issuedAt) || age < -60 || age >= SESSION_MAX_AGE_SECONDS) return false;
  const payload = `${match[1]}.${match[2]}`;
  if (
    !timingSafeEqual(
      Buffer.from(signature(payload, accessKey), "hex"),
      Buffer.from(match[3], "hex")
    )
  )
    return false;
  try {
    return (
      await stat(path.join(/* turbopackIgnore: true */ sessionDirectory(), payload))
    ).isFile();
  } catch {
    // Missing, unavailable, or revoked storage must never authorize a request.
    return false;
  }
}

export async function revokeSessionToken(token: string | undefined): Promise<void> {
  const match = token?.match(TOKEN_PATTERN);
  if (!match) return;
  await unlink(
    path.join(/* turbopackIgnore: true */ sessionDirectory(), `${match[1]}.${match[2]}`)
  ).catch((error: NodeJS.ErrnoException) => {
    if (error.code !== "ENOENT") throw error;
  });
}

export function isSecureRequest(_request: NextRequest): boolean {
  return publicOrigin()?.startsWith("https://") ?? false;
}

export function sessionCookieOptions(request: NextRequest) {
  return { httpOnly: true, secure: isSecureRequest(request), sameSite: "lax" as const, path: "/" };
}
