import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'ASM AI Reporting Agent',
  description: 'AI-powered database reporting agent with a natural-language interface.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
