import { Bell, Calculator, Code2, Eraser, FileSearch, FileText, FolderOpen, Globe, Library, NotebookPen, NotebookText, SquareTerminal, Wrench, type LucideIcon } from "lucide-react";

const TOOL_ICONS: Record<string, LucideIcon> = {
  calculator: Calculator,
  search: FileSearch,
  retrieve: Library,
  save_note: NotebookPen,
  recall_notes: NotebookText,
  forget_note: Eraser,
  notify: Bell,
  web_search: Globe,
  read_webpage: FileText,
  run_python: Code2,
  run_shell: SquareTerminal,
  workspace_files: FolderOpen,
};

export function ToolIcon({ tool, className = "size-4" }: { tool: string; className?: string }) {
  const Icon = TOOL_ICONS[tool] ?? Wrench;
  return <Icon aria-hidden className={className} />;
}
