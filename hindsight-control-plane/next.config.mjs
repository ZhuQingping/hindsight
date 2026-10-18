// @ts-check
import path from "node:path";
import { fileURLToPath } from "node:url";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

// Use a port-scoped distDir so multiple dev instances don't collide on the lock file
const distDir = process.env.PORT && process.env.PORT !== '9999'
  ? `.next-${process.env.PORT}`
  : '.next';

// Maximum upload/request body size for file retain. Next.js buffers request
// bodies that pass through middleware/proxy (the auth middleware does, for
// /api/files/retain) and truncates anything over this limit (default 10MB),
// which silently corrupts large document uploads. Default to 100MB to match the
// dataplane's HINDSIGHT_API_FILE_CONVERSION_MAX_BATCH_SIZE_MB default; accepts a
// human-readable size string ('100mb', '1gb') or a number of bytes.
const maxUploadEnv = process.env.HINDSIGHT_CP_MAX_UPLOAD_SIZE;
const maxUploadBodySize = maxUploadEnv
  ? (/^\d+$/.test(maxUploadEnv) ? Number(maxUploadEnv) : /** @type {NonNullable<import('next').NextConfig['experimental']>['proxyClientMaxBodySize']} */ (maxUploadEnv))
  : '100mb';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  distDir,
  basePath: basePath,
  assetPrefix: basePath,
  // Disable request logging in production
  logging: false,
  experimental: {
    proxyClientMaxBodySize: maxUploadBodySize,
  },
  // Set the monorepo root explicitly to avoid detecting wrong lockfiles in parent directories
  turbopack: {
    root: path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'),
  },
};

export default withNextIntl(nextConfig);
