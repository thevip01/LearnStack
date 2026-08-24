import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { AppHeader } from "@/components/shell/AppHeader";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "LearnOS", template: "%s · LearnOS" },
  description: "One runtime, every subject: a generic learning workspace where the subject is data, not code.",
  applicationName: "LearnOS",
};

export const viewport: Viewport = {
  themeColor: "#090b10",
  colorScheme: "dark",
};

/**
 * The root layout owns the height chain (html → body → shell) so the workspace
 * can flex to fill the viewport, and mounts the client providers. It carries no
 * subject knowledge: every route below decides its own content, and a subject's
 * theme is scoped to the runtime subtree, never here.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-theme="dark" className="h-full">
      <body className="h-full">
        <Providers>
          <div className="flex h-full min-h-0 flex-col">
            <AppHeader />
            <main className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
