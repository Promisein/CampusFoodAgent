import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "成电吃什么 - 校园餐饮 AI 推荐助手",
  description: "UESTC 智能餐饮推荐系统，输入需求即可获得个性化餐厅推荐",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
