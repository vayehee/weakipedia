import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const mockTelegramUser = null as
  | null
  | {
      name: string;
      photoUrl: string;
    };

const WIKIMEDIA_SEARCH_API_URL =
  import.meta.env.VITE_WIKIMEDIA_SEARCH_API_URL ??
  (import.meta.env.PROD
    ? "https://wikimedia-search-d5r7glossa-ew.a.run.app"
    : "http://127.0.0.1:8080");

type Suggestion = {
  description: string;
  faviconUrl: string;
  source: string;
  title: string;
  url: string;
};

type ValidationState =
  | { status: "idle"; message: "" }
  | { status: "checking"; message: "" }
  | { status: "invalid"; message: string }
  | { status: "valid"; message: "" };

type ResolveResponse = {
  canSubmit: boolean;
  message: string;
  status: ValidationState["status"];
  suggestions: Suggestion[];
};

function toValidationState(result: ResolveResponse): ValidationState {
  if (result.status === "valid") {
    return { status: "valid", message: "" };
  }

  if (result.status === "idle" || result.status === "checking") {
    return { status: result.status, message: "" };
  }

  return { status: "invalid", message: result.message };
}

async function resolveWikimediaInput(input: string, signal: AbortSignal) {
  const api = new URL("/resolve", WIKIMEDIA_SEARCH_API_URL);
  api.searchParams.set("input", input);

  const response = await fetch(api, { signal });

  if (!response.ok) {
    throw new Error("Unable to resolve Wikimedia input.");
  }

  return (await response.json()) as ResolveResponse;
}

function App() {
  const user = mockTelegramUser;
  const [articleUrl, setArticleUrl] = useState("");
  const [selectedSuggestionUrl, setSelectedSuggestionUrl] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [validation, setValidation] = useState<ValidationState>({
    status: "idle",
    message: "",
  });
  const canSubmit = validation.status === "valid";

  useEffect(() => {
    const trimmed = articleUrl.trim();

    if (!trimmed) {
      setSelectedSuggestionUrl("");
      setSuggestions([]);
      setValidation({ status: "idle", message: "" });
      return;
    }

    if (trimmed === selectedSuggestionUrl) {
      setSuggestions([]);
      setValidation({ status: "valid", message: "" });
      return;
    }

    const controller = new AbortController();
    setSuggestions([]);
    setValidation({ status: "checking", message: "" });

    const timeout = window.setTimeout(() => {
      resolveWikimediaInput(trimmed, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) {
            return;
          }

          setSuggestions(result.suggestions);
          setValidation(toValidationState(result));
        })
        .catch((error: unknown) => {
          if ((error as Error).name === "AbortError" || controller.signal.aborted) {
            return;
          }

          setSuggestions([]);
          setValidation({
            status: "invalid",
            message: "Wikimedia search is temporarily unavailable.",
          });
        });
    }, 300);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [articleUrl, selectedSuggestionUrl]);

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
          <span className="wiki-wordmark" aria-label="Wikipedia">
            <span className="wiki-wordmark-tall">W</span>
            <span>I</span>
            <span>K</span>
            <span>I</span>
            <span>P</span>
            <span>E</span>
            <span>D</span>
            <span>I</span>
            <span className="wiki-wordmark-tall">A</span>
          </span>{" "}
          is <u>irreplaceable</u>... yet <u>flawed</u>. <strong>Fix it!</strong>
        </p>
        <form
          className="search-form"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
          }}
        >
          <div className="input-row">
            <input
              aria-label="Wikipedia article URL"
              className="url-input"
              placeholder="Wikipedia article URL"
              type="text"
              value={articleUrl}
              onChange={(event) => {
                setSelectedSuggestionUrl("");
                setArticleUrl(event.target.value);
              }}
            />
            <button className="submit-button" type="submit" disabled={!canSubmit}>
              Submit
            </button>
          </div>
          {suggestions.length > 0 ? (
            <div className="suggestions-tray" role="listbox" aria-label="Search suggestions">
              {suggestions.map((suggestion) => (
                <button
                  className="suggestion-option"
                  key={suggestion.url}
                  type="button"
                  onClick={() => {
                    setSelectedSuggestionUrl(suggestion.url);
                    setSuggestions([]);
                    setValidation({ status: "valid", message: "" });
                    setArticleUrl(suggestion.url);
                  }}
                >
                  <img
                    className="suggestion-favicon"
                    src={suggestion.faviconUrl}
                    alt=""
                    aria-hidden="true"
                  />
                  <span className="suggestion-title">{suggestion.title}</span>
                  <span className="suggestion-description">
                    {suggestion.source}
                    {suggestion.description ? ` - ${suggestion.description}` : ""}
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          <p
            className={`validation-message ${
              validation.status === "invalid" ? "is-error" : ""
            }`}
            aria-live="polite"
          >
            {validation.status === "checking" ? "Checking..." : validation.message}
          </p>
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
