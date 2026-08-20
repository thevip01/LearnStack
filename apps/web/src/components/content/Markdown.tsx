"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

/**
 * All learner-facing prose from the API goes through here.
 *
 * `skipHtml` is deliberate and matches the schema's "no raw HTML" rule for
 * ProseBlock: extracted content is not trusted markup, and disabling raw HTML
 * closes the injection route without needing a sanitiser dependency.
 */
export function Markdown({ children, className }: { children: string | null | undefined; className?: string }) {
  if (!children) return null;
  return (
    <div className={cn("md-body", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {children}
      </ReactMarkdown>
    </div>
  );
}

/** Single-line markdown for table cells and list rows. */
export function InlineMarkdown({ children, className }: { children: string | null | undefined; className?: string }) {
  if (!children) return null;
  return (
    <span className={cn("md-body [&>*]:!mt-0 [&_p]:inline", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {children}
      </ReactMarkdown>
    </span>
  );
}
