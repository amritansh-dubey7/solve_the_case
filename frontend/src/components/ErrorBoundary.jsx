import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('Caught by ErrorBoundary:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="evidence-card unverified">
          <div className="doc-id">
            <span>Something broke in this panel</span>
            <span className="badge badge-unverified">⚠ error</span>
          </div>
          <p style={{ margin: 0 }}>
            {this.state.error.message || String(this.state.error)}
          </p>
          <p className="hint-note" style={{ marginTop: 8 }}>
            Open the browser console (F12) for the full stack trace. Other tabs should still work —
            switch tabs to keep using the app.
          </p>
        </div>
      )
    }
    return this.props.children
  }
}
