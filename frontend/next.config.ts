import type { NextConfig } from "next";

// Stable export identity prevents rebuild drift while chunks retain content-hashed invalidation.
const nextConfig: NextConfig = {
  output: "export",
  generateBuildId: async () => "stock-probs",
  // The production image is built on a 1 GiB Linode; bound Next's worker fan-out.
  experimental: { cpus: 1 },
};

export default nextConfig;
