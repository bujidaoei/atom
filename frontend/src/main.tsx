import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./index.css";

const container = document.getElementById("root");
if (!container) throw new Error("找不到 #root 挂载点。");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
