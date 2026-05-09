import Link from "next/link";
import type { SessionPayload } from "@/lib/auth";

interface NavProps {
  session: SessionPayload;
}

export function Nav({ session }: NavProps) {
  return (
    <header className="border-b border-zinc-800 bg-zinc-950/70 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-semibold tracking-tight">
            AI Trading Agent
          </Link>
          <nav className="flex items-center gap-4 text-sm text-zinc-400">
            <Link href="/" className="hover:text-zinc-100">
              Dashboard
            </Link>
            <Link href="/proposals" className="hover:text-zinc-100">
              Proposals
            </Link>
            <Link href="/orders" className="hover:text-zinc-100">
              Orders
            </Link>
            <Link href="/watchlist" className="hover:text-zinc-100">
              Watchlist
            </Link>
            <Link href="/signals" className="hover:text-zinc-100">
              Signals
            </Link>
          </nav>
        </div>
        <div className="text-sm text-zinc-500">
          {session.username ? `@${session.username}` : `user ${session.uid}`}
          <a
            href="/api/auth/logout"
            className="ml-3 text-zinc-600 hover:text-zinc-300"
          >
            Sign out
          </a>
        </div>
      </div>
    </header>
  );
}
