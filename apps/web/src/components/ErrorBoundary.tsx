import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean; message: string | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ui_error_boundary", { error: error.message, info });
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="page" role="alert">
          <h1>Something went wrong</h1>
          <p>{this.state.message ?? "Unexpected UI error"}</p>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, message: null })}
          >
            Try again
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
