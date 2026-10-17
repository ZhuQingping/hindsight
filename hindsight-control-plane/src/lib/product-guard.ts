import { NextResponse } from "next/server";
import { localProductConfig, verifiedProductConfig } from "./product-config-server";

/** Reject a stale tab or mismatched native API before forwarding its request. */
export async function productGuard(request: Request): Promise<NextResponse | null> {
  let code: "PRODUCT_NAME_STALE" | "PRODUCT_CONFIG_MISMATCH" | "PRODUCT_CONFIG_UNAVAILABLE";
  const submittedName = request.headers.get("X-Product-Name");
  if (submittedName && submittedName !== localProductConfig().contextdb_name) {
    code = "PRODUCT_NAME_STALE";
  } else {
    try {
      await verifiedProductConfig();
      return null;
    } catch (error) {
      code =
        error instanceof Error && error.message === "PRODUCT_CONFIG_MISMATCH"
          ? "PRODUCT_CONFIG_MISMATCH"
          : "PRODUCT_CONFIG_UNAVAILABLE";
    }
  }
  const status = code === "PRODUCT_NAME_STALE" ? 409 : 503;
  return NextResponse.json(
    { code, error: code },
    { status, headers: { "Cache-Control": "no-store" } }
  );
}
