/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@argus/shared'],
  // Enable built-in Less support for *.module.less files
  experimental: {
    typedRoutes: true,
  },
};
module.exports = nextConfig;
