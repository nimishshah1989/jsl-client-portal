import '../styles/globals.css';

export const metadata = {
  title: 'JSL Client Portal | Jhaveri Securities',
  description: 'Your portfolio dashboard — performance, risk, holdings, and more.',
  icons: { icon: '/favicon.ico' },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-800 antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
