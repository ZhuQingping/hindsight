import { NextRequest, NextResponse } from "next/server";
import { DATAPLANE_URL, getDataplaneHeaders } from "@/lib/contextbase-client";

export async function GET() {
  const response = await fetch(`${DATAPLANE_URL}/v1/file-storage/config`, {
    headers: getDataplaneHeaders(),
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) {
    return NextResponse.json(data, { status: response.status });
  }
  return NextResponse.json(data, { status: 200 });
}

export async function PUT(request: NextRequest) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  const response = await fetch(`${DATAPLANE_URL}/v1/file-storage/config`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      ...getDataplaneHeaders(),
    },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    return NextResponse.json(data, { status: response.status });
  }
  return NextResponse.json(data, { status: 200 });
}
