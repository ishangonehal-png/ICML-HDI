import type { Metadata } from "next";

import "./globals.css";
import {
  ResearchDisclaimerBanner,
  ResearchDisclaimerFooter,
} from "@/components/layout/research-disclaimer";

export const metadata: Metadata = {
  title: "YC AIxBio · P0 Frontend Shell",
  description:
    "Upload → analysis → patient workspace shell for tri-modal LUAD research demo.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen flex-col">
          <ResearchDisclaimerBanner />
          <main className="mx-auto flex w-full max-w-[1480px] flex-1 flex-col px-4 py-6 lg:px-6">
            {children}
          </main>
          <ResearchDisclaimerFooter />
        </div>
      </body>
    </html>
  );
}
