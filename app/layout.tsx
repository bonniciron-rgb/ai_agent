import type { Metadata, Viewport } from "next";
import "./globals.css";
import { RegisterServiceWorker } from "./components/RegisterServiceWorker";
import { InstallPrompt } from "./components/InstallPrompt";

export const metadata: Metadata = {
  title: "AI Trading Agent",
  description: "Daily-loop AI trading agent dashboard",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Ethera",
    startupImage: [
      {
        url: "/splash/iphone-x.png",
        media:
          "(device-width: 375px) and (device-height: 812px) and (-webkit-device-pixel-ratio: 3)",
      },
      {
        url: "/splash/iphone-15-pro.png",
        media:
          "(device-width: 393px) and (device-height: 852px) and (-webkit-device-pixel-ratio: 3)",
      },
    ],
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [
      { url: "/icons/apple-touch-icon-180.png", sizes: "180x180" },
      { url: "/icons/apple-touch-icon-167.png", sizes: "167x167" },
      { url: "/icons/apple-touch-icon-152.png", sizes: "152x152" },
    ],
  },
};

export const viewport: Viewport = {
  themeColor: "#0E2138",
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-950 text-zinc-100 font-sans antialiased">
        {children}
        <RegisterServiceWorker />
        <InstallPrompt />
      </body>
    </html>
  );
}
