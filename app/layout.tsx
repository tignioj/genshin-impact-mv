import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "映界 · 原神 MV 工坊",
  description: "使用角色 Wiki 素材、音乐与字幕，自动制作原神角色 MV。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
