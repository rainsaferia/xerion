import { NextResponse } from "next/server";

/** Frontend liveness probe. Does not call the backend. */
export function GET() {
  return NextResponse.json({ status: "ok", service: "frontend" });
}

