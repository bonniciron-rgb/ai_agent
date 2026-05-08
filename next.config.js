/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The Python serverless function at api/telegram_webhook.py is owned by
  // Vercel's Python runtime, not Next.js.  Skip Next's built-in /api routing
  // for that path so it falls through to the Python handler.
  async rewrites() {
    return [];
  },
};

module.exports = nextConfig;
