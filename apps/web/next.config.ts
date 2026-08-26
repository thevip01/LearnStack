import type { NextConfig } from "next";

/**
 * The API as this server can reach it. Not the same question as the URL a browser
 * should use: see the rewrite below.
 */
const API_VERSION_PATH = "/api/v1";

function apiTarget(): string {
  const raw = (process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL || "http://api:8000").replace(
    /\/+$/,
    "",
  );
  // Either convention is accepted in .env, so strip the version prefix before
  // appending it again and shipping /api/v1/api/v1/subjects.
  return raw.endsWith(API_VERSION_PATH) ? raw.slice(0, -API_VERSION_PATH.length) : raw;
}

const nextConfig: NextConfig = {
  // The Dockerfile copies .next/standalone, so the server must be self-contained.
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    // Lint runs in CI as its own step; a lint failure should not block an image build.
    ignoreDuringBuilds: true,
  },
  experimental: {
    // mermaid and @xyflow/react are large ESM packages; transpiling them once at
    // build time keeps the client bundles from re-parsing them per route.
    optimizePackageImports: ["lucide-react", "recharts", "@xyflow/react"],
  },

  /**
   * The browser calls this origin and this server passes it on, which is the only
   * arrangement where the session cookie survives.
   *
   * That cookie is httpOnly with `SameSite=Lax`, and a browser reads "same site"
   * off the document's hostname. A page opened on http://localhost:3000 calling
   * http://127.0.0.1:8000 is therefore cross-site: the cookie is set once and then
   * withheld from every request after it, the API sees an anonymous caller, and the
   * client redirects to /login. It looks like an instant logout and it is not a
   * CORS problem, so no CORS setting fixes it. Safari refuses cross-site cookies
   * outright and fails every single time.
   *
   * Proxying makes the cookie first-party by construction, removes the preflight
   * on every mutation, and means the app works when opened on 127.0.0.1 or on a LAN
   * address instead of only on the one hostname someone happened to configure.
   * `apps/web/src/lib/apiTarget.ts` holds the client half and its tests.
   */
  async rewrites() {
    const target = apiTarget();
    return [
      { source: `${API_VERSION_PATH}/:path*`, destination: `${target}${API_VERSION_PATH}/:path*` },
      // Both liveness probes sit outside the versioned surface, and the readiness
      // banner polls /readyz from the browser.
      { source: "/readyz", destination: `${target}/readyz` },
      { source: "/healthz", destination: `${target}/healthz` },
    ];
  },
};

export default nextConfig;
