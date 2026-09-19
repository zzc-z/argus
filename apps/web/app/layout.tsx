import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import { ArgusLogo } from '@/components/ArgusLogo';
import './globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });

export const metadata: Metadata = {
  title: 'Argus · 多智能体深度研报',
  description: '面向工程师与研究员的 AI 洞察引擎',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={inter.variable}>
      <body className="min-h-screen bg-background text-on-surface antialiased">{children}</body>
    </html>
  );
}
