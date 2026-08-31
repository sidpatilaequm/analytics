import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import PublicView from "./components/PublicView.jsx";
import "./styles.css";

const publicMatch = window.location.pathname.match(/^\/r\/(.+)$/);
const root = createRoot(document.getElementById("root"));

root.render(
  <React.StrictMode>
    {publicMatch ? <PublicView slug={publicMatch[1]} /> : <App />}
  </React.StrictMode>
);