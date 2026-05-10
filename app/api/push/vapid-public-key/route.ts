import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  const key = process.env.VAPID_PUBLIC_KEY?.trim();
  if (!key) return NextResponse.json({ error: "Push not configured" }, { status: 503 });
  return NextResponse.json({ key });
}
