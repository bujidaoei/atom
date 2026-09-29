import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { SessionProvider } from "./session";
import "./index.css";

class Guard extends Component<{ children: ReactNode }, { message: string }> {
  state = { message: "" };

  static getDerivedStateFromError(error: Error) {
    return { message: error.message || "页面渲染失败" };
  }

  render() {
    if (this.state.message) {
      return (
        <p className="px-6 py-10 text-sm">
          页面没有打开：{this.state.message}
        </p>
      );
    }
    return this.props.children;
  }
}

const basename = import.meta.env.BASE_URL.replace(/\/$/, "");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Guard>
      <BrowserRouter basename={basename || undefined}>
        <SessionProvider>
          <App />
        </SessionProvider>
      </BrowserRouter>
    </Guard>
  </StrictMode>,
);
