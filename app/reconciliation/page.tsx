import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import ReconciliationClient from "./ReconciliationClient";

export const dynamic = "force-dynamic";

export default async function ReconciliationPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  return (
    <>
      <Nav session={session} />
      <ReconciliationClient />
    </>
  );
}
