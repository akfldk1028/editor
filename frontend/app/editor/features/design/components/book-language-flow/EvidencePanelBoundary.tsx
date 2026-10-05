import { Component, type ReactNode } from 'react';

interface EvidencePanelBoundaryProps {
  children: ReactNode;
  resetKey: string;
}

interface EvidencePanelBoundaryState {
  hasError: boolean;
}

export class EvidencePanelBoundary extends Component<
  EvidencePanelBoundaryProps,
  EvidencePanelBoundaryState
> {
  state: EvidencePanelBoundaryState = { hasError: false };

  static getDerivedStateFromError(): EvidencePanelBoundaryState {
    return { hasError: true };
  }

  componentDidUpdate(previousProps: EvidencePanelBoundaryProps): void {
    if (
      this.state.hasError
      && previousProps.resetKey !== this.props.resetKey
    ) {
      this.setState({ hasError: false });
    }
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <aside className="book-evidence book-evidence--failure" role="alert">
          <span>EVIDENCE PANEL UNAVAILABLE</span>
          <p>The selected historical evidence could not be rendered.</p>
          <p>Select another run or MASS to continue.</p>
        </aside>
      );
    }

    return this.props.children;
  }
}
