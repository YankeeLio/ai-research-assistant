/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 容器部署只保留 standalone 运行时，镜像从 1.2GB 降到约 200MB
  output: "standalone",
  // 开发期把 /api 透传到 FastAPI，避免跨域与环境变量切换
  async rewrites() {
    const target = process.env.API_ORIGIN || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
};

export default nextConfig;
