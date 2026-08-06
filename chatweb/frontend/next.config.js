/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // react-syntax-highlighter ships ESM that Next must transpile.
  transpilePackages: ["react-syntax-highlighter"],
};

module.exports = nextConfig;
