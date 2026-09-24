import { Component } from "react";

/** Keeps a rendering failure in one panel from blanking the whole command centre. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("CityPulse UI error:", error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="state error" role="alert">
          <p className="state-title">Something went wrong in this view</p>
          <p className="muted">{String(this.state.error?.message || this.state.error)}</p>
          <button type="button" className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      );
    }
    return this.props.children;
  }
}
