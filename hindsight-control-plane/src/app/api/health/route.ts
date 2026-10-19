import { controlPlaneEnv } from "@/lib/control-plane-env";
import { localProductName } from "@/lib/product-config-server";
import { NextResponse } from "next/server";
import { createClient, createConfig, sdk } from "@vectorize-io/hindsight-client";
import { getDataplaneHeaders } from "@/lib/hindsight-client";

const HEALTH_CHECK_TIMEOUT_MS = 3000;

export async function GET() {
  const status: {
    status: string;
    service: string;
    dataplane?: {
      status: string;
      error?: string;
    };
  } = {
    status: "ok",
    service: `${localProductName()}-control-plane`,
  };

  // Check dataplane connectivity with a short timeout
  const dataplaneUrl = controlPlaneEnv("DATAPLANE_API_URL") || "http://localhost:8888";
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);

    const healthClient = createClient(
      createConfig({
        baseUrl: dataplaneUrl,
        signal: controller.signal,
        headers: getDataplaneHeaders(),
      })
    );

    try {
      // A reachability probe, not a listing: ask for the smallest page the
      // endpoint will serve instead of pulling the default 100 banks.
      const result = await sdk.listBanks({ client: healthClient, query: { limit: 1 } });
      if (result.error !== undefined || result.data === undefined)
        throw new Error("Backend unavailable");
      status.dataplane = {
        status: "connected",
      };
    } finally {
      clearTimeout(timeoutId);
    }
  } catch (error) {
    console.error("Backend health probe failed", error);
    let errorMessage = "Backend unavailable";
    if (error instanceof Error && error.name === "AbortError") {
      errorMessage = `Request timed out after ${HEALTH_CHECK_TIMEOUT_MS}ms`;
    }
    status.dataplane = {
      status: "disconnected",
      error: errorMessage,
    };
  }

  return NextResponse.json(status, { status: 200 });
}
