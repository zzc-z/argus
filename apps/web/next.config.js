/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@argus/shared'],
  // 顶层 typedRoutes (Next 15 GA)；experimental.* 已废
  typedRoutes: true,
  // CSS Modules: Next 15 内置 .module.css 支持（*.module.less 不内置）
  // AGENTS.md §16.2 描述 "Next 历来对 less 都不内置支持，需要手动配 less-loader"
  // 我们选择改用 .module.css 零配置方案，删 less-loader / css-loader / fix-loader
};
module.exports = nextConfig;
