import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const mockTelegramUser = null as
  | null
  | {
      name: string;
      photoUrl: string;
    };

function App() {
  const user = mockTelegramUser;

  return (
    <div className="page">
      <header className="topbar">
        {user ? (
          <div className="account">
            <button className="logout-button" type="button">
              Logout
            </button>
            <img className="avatar" src={user.photoUrl} alt={user.name} />
          </div>
        ) : (
          <button className="login-button" type="button">
            Login / Sign up
          </button>
        )}
      </header>

      <main className="search-shell" aria-labelledby="page-title">
        <h1 id="page-title" className="brand">
          Weakipedia
        </h1>
        <p className="tagline">
          In the age of AI,{" "}
          <img
            className="source-favicon"
            src="https://en.wikipedia.org/favicon.ico"
            alt=""
            aria-hidden="true"
          />
          <strong>Wikipedia</strong> is paramount… but flawed. You have the power to
          fix it!
        </p>
        <form className="search-form" role="search">
          <div className="input-row">
            <input
              aria-label="Wikipedia article URL"
              className="url-input"
              inputMode="url"
              placeholder="Wikipedia article URL"
              type="url"
            />
            <button className="submit-button" type="submit">
              Submit
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
