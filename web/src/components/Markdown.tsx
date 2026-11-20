import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Assistant text as Markdown. Raw HTML is not rendered (react-markdown default). */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown break-words leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // in-app links (#/sheet?id=3) stay in the app; the rest open a new tab
          a: ({ children, href }) =>
            href?.startsWith("#") ? (
              <a href={href}>{children}</a>
            ) : (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
