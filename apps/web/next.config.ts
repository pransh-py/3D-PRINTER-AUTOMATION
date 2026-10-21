import type { NextConfig } from "next";

const apiInternalUrl = (
  process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  distDir:
    process.env.PRINTFLOW_PRINT_STATION === "1" &&
    process.env.PRINTFLOW_WEB_VERIFICATION === "1"
      ? ".next-station-verification"
      : process.env.PRINTFLOW_LAN_WEB === "1"
      ? ".next-lan"
      : process.env.PRINTFLOW_PRINT_STATION === "1"
        ? ".next-print-station"
        : process.env.PRINTFLOW_WEB_VERIFICATION === "1"
          ? ".next-verification"
          : ".next",
  experimental: {
    proxyClientMaxBodySize: "101mb",
  },
  turbopack: {
    root: process.cwd(),
  },
  async redirects() {
    return process.env.PRINTFLOW_PRINT_STATION === "1"
      ? []
      : [{ source: "/print", destination: "/get-a-quote", permanent: false }];
  },
  async rewrites() {
    return [
      ...(process.env.PRINTFLOW_PRINT_STATION === "1"
        ? [
            {
              source: "/api/printer/:path*",
              destination: "http://127.0.0.1:8123/api/printer/:path*",
            },
          ]
        : []),
      {
        source: "/api/v1/:path*",
        destination: `${apiInternalUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
