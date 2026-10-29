import { controlPlaneEnv } from "@/lib/control-plane-env";
/**
 * Next.js instrumentation file - runs exactly once at server startup.
 * https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation
 */
export async function register() {
  const { localProductConfig } = await import("@/lib/product-config-server");
  localProductConfig();
  if (controlPlaneEnv("CONTEXTDB_ENABLED") === "true") {
    const { waitForContextDBAdmin } = await import("@/lib/contextdb");
    await waitForContextDBAdmin();
  }
  const dataplaneUrl = controlPlaneEnv("DATAPLANE_API_URL") || "http://localhost:8888";
  const apiKey = controlPlaneEnv("DATAPLANE_API_KEY") || "";

  console.log(`[Control Plane] Connecting to dataplane at: ${dataplaneUrl}`);
  if (apiKey) {
    console.log("[Control Plane] Using API key authentication");
  } else {
    console.log("[Control Plane] No API key configured (public access)");
  }
}
