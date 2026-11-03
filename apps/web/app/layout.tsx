export const metadata = {
  title: "SciLoom · 智研织机",
  description: "基于大模型与 Agent 架构的全流程科研助手",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
