import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  return (
    <main className="shell">
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">Project environment ready</p>
        <h1 id="page-title">Weakipedia</h1>
        <p className="lede">
          A clean starting point for the Weakipedia front-end, wired for local
          development and GitHub Pages deployment.
        </p>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
