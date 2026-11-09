import type { Metadata } from "next";
import "./tailwind-built.css";

export const metadata: Metadata = {
  title: "Project Intelligence Platform",
  description: "EPC Project Intelligence Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark h-full antialiased">
      <body className="min-h-full flex flex-col font-sans">{children}</body>
    </html>
  );
}
