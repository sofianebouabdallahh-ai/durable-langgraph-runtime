/** A page that failed to draw: say so plainly, report it, offer a way back. */
import { Component, type ErrorInfo, type ReactNode } from "react";

import { reportError } from "./errors";

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    if (info.componentStack) error.stack = `${error.stack ?? ""}\n${info.componentStack}`;
    reportError("render", error);
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-lg px-6 py-20 text-center" data-testid="page-error">
        <h1 className="font-display text-3xl font-medium">This page stopped working</h1>
        <p className="mt-3 text-stone-500 dark:text-stone-400">
          Your chats and agents are safe. The error was written to the app's log; if it happens again, Send feedback with what you were doing.
        </p>
        <button
          type="button"
          className="mt-6 rounded-xl bg-stone-900 px-4 py-2.5 text-sm font-medium text-white dark:bg-stone-100 dark:text-stone-900"
          onClick={() => {
            window.location.reload();
          }}
        >
          Reload the page
        </button>
      </div>
    );
  }
}
