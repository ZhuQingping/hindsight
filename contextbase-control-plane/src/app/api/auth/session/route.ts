import { NextResponse } from "next/server";
import { protectedMode } from "@/lib/auth/session";

/** Local UI access metadata stays available when the dataplane is unavailable. */
export async function GET() {
  return NextResponse.json(
    { required: protectedMode() },
    { headers: { "Cache-Control": "no-store" } }
  );
}
