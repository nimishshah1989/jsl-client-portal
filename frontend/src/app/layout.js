import { Inter } from 'next/font/google';
import '../styles/globals.css';

const inter = Inter({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700', '800'],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata = {
  title: 'JSL Client Portal | Jhaveri Securities',
  description: 'Your portfolio dashboard — performance, risk, holdings, and more.',
  icons: { icon: '/favicon.ico' },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className={`${inter.className} bg-slate-50 text-slate-800 antialiased min-h-screen overflow-x-hidden`}>
        {children}
      </body>
    </html>
  );
}
