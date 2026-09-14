import type { NextConfig } from "next";

// Stable export identity prevents rebuild drift while chunks retain content-hashed invalidation.
const nextConfig: NextConfig = {
  output: "export",
  generateBuildId: async () => "stock-probs",
};

export default nextConfig;
