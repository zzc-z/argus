/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@argus/shared'],
  experimental: {
    typedRoutes: true
  }
};
module.exports = nextConfig;
