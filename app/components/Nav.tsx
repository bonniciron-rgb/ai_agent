"use client";

import { useState } from "react";
import Link from "next/link";
import type { SessionPayload } from "@/lib/auth";

interface NavProps {
  session: SessionPayload;
}

interface NavLink {
  href: string;
  label: string;
}

// Daily-use links — always visible on desktop.
const PRIMARY: NavLink[] = [
  { href: "/", label: "Dashboard" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/proposals", label: "Proposals" },
  { href: "/analysis", label: "Analysis" },
  { href: "/orders", label: "Orders" },
];

// Everything else, grouped — lives under the "More" dropdown.
const GROUPS: { label: string; links: NavLink[] }[] = [
  {
    label: "Markets",
    links: [
      { href: "/regime", label: "Regime" },
      { href: "/leaders", label: "Leaders" },
      { href: "/insiders", label: "Insiders" },
      { href: "/buzz", label: "Buzz" },
      { href: "/ipos", label: "IPOs" },
      { href: "/signals", label: "Signals" },
      { href: "/watchlist", label: "Watchlist" },
    ],
  },
  {
    label: "Tracking",
    links: [
      { href: "/reconciliation", label: "Reconciliation" },
      { href: "/shadow", label: "Shadow" },
      { href: "/simulator", label: "Simulator" },
    ],
  },
  {
    label: "System",
    links: [
      { href: "/connections", label: "Connections" },
      { href: "/llm-usage", label: "Cost" },
    ],
  },
];

export function Nav({ session }: NavProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  const linkCls = "hover:text-zinc-100";

  return (
    <header className="border-b border-zinc-800 bg-zinc-950/70 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-semibold tracking-tight">
            AI Trading Agent
          </Link>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-4 text-sm text-zinc-400 sm:flex">
            {PRIMARY.map((link) => (
              <Link key={link.href} href={link.href} className={linkCls}>
                {link.label}
              </Link>
            ))}

            {/* "More" dropdown */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setMoreOpen((v) => !v)}
                aria-expanded={moreOpen}
                className={`flex items-center gap-1 ${linkCls}`}
              >
                More
                <span className="text-xs">{moreOpen ? "▴" : "▾"}</span>
              </button>
              {moreOpen && (
                <>
                  {/* click-outside backdrop */}
                  <button
                    type="button"
                    aria-hidden
                    tabIndex={-1}
                    className="fixed inset-0 z-10 cursor-default"
                    onClick={() => setMoreOpen(false)}
                  />
                  <div className="absolute right-0 z-20 mt-3 w-52 rounded-lg border border-zinc-800 bg-zinc-950 p-2 shadow-xl">
                    {GROUPS.map((group) => (
                      <div key={group.label} className="py-1">
                        <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
                          {group.label}
                        </div>
                        {group.links.map((link) => (
                          <Link
                            key={link.href}
                            href={link.href}
                            onClick={() => setMoreOpen(false)}
                            className="block rounded px-2 py-1.5 text-sm text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
                          >
                            {link.label}
                          </Link>
                        ))}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-zinc-500 sm:inline">
            {session.username ? `@${session.username}` : `user ${session.uid}`}
          </span>
          <a
            href="/api/auth/logout"
            className="hidden text-sm text-zinc-600 hover:text-zinc-300 sm:inline"
          >
            Sign out
          </a>

          {/* Mobile menu button */}
          <button
            className="rounded p-1 text-zinc-400 hover:text-zinc-100 sm:hidden"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Menu"
            aria-expanded={menuOpen}
          >
            {menuOpen ? (
              <svg
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <line x1="4" y1="4" x2="16" y2="16" />
                <line x1="16" y1="4" x2="4" y2="16" />
              </svg>
            ) : (
              <svg
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <line x1="3" y1="6" x2="17" y2="6" />
                <line x1="3" y1="10" x2="17" y2="10" />
                <line x1="3" y1="14" x2="17" y2="14" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile drawer */}
      {menuOpen && (
        <nav className="border-t border-zinc-800 px-6 py-3 sm:hidden">
          <div className="flex flex-col gap-1">
            {PRIMARY.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded px-2 py-2 text-sm text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </Link>
            ))}
          </div>
          {GROUPS.map((group) => (
            <div
              key={group.label}
              className="mt-3 border-t border-zinc-800 pt-2"
            >
              <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
                {group.label}
              </div>
              <div className="flex flex-col gap-1">
                {group.links.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="rounded px-2 py-2 text-sm text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
                    onClick={() => setMenuOpen(false)}
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
          <div className="mt-3 border-t border-zinc-800 pt-3 text-sm text-zinc-500">
            <span>
              {session.username
                ? `@${session.username}`
                : `user ${session.uid}`}
            </span>
            <a
              href="/api/auth/logout"
              className="ml-3 text-zinc-600 hover:text-zinc-300"
            >
              Sign out
            </a>
          </div>
        </nav>
      )}
    </header>
  );
}
