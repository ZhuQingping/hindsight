import { NextResponse } from "next/server";
import { localProductConfig, verifiedProductConfig } from "@/lib/product-config-server";

export async function GET() {
  try {
    return NextResponse.json(await verifiedProductConfig(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { ...localProductConfig(), error: "PRODUCT_CONFIG_MISMATCH_OR_UNAVAILABLE" },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
