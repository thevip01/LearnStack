import type { NextConfig } from "next";

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
};

export default nextConfig;
