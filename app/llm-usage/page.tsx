import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import UsageClient from "./UsageClient";

export const dynamic = "force-dynamic";

export default async function LlmUsagePage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  return (
    <>
      <Nav session={session} />
      <UsageClient />
    </>
  );
}
