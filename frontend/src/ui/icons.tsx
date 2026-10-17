import { Bell, Calculator, FileSearch, Library, NotebookPen, Wrench, type LucideIcon } from "lucide-react";

const TOOL_ICONS: Record<string, LucideIcon> = {
  calculator: Calculator,
  search: FileSearch,
  retrieve: Library,
  save_note: NotebookPen,
  notify: Bell,
};

export function ToolIcon({ tool, className = "size-4" }: { tool: string; className?: string }) {
  const Icon = TOOL_ICONS[tool] ?? Wrench;
  return <Icon aria-hidden className={className} />;
}
