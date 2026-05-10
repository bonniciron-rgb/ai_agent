import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import SimulatorClient from "./SimulatorClient";
import { getSimulatorSymbols } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function SimulatorPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const symbols = await getSimulatorSymbols().catch(() => [] as string[]);

  return (
    <>
      <Nav session={session} />
      <SimulatorClient symbols={symbols} />
    </>
  );
}
