import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Phantom Dev',
  description: 'Autonomous Computer Operator — live activity dashboard',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-gray-950 antialiased">{children}</body>
    </html>
  );
}
