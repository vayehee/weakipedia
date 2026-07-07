import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { LoaderCircle, Moon, Search, Sun, X } from "lucide-react";
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
const VAYEHEE_FAVICON_URL =
  "https://vayehee.com/wp-content/uploads/2021/11/cropped-cropped-logo-small-1-32x32.png";

type NavigatorWithVirtualKeyboard = Navigator & {
  virtualKeyboard?: {
    overlaysContent: boolean;
  };
};

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

type ThemeMode = "light" | "dark";

function getInitialThemeMode(): ThemeMode {
  const storedTheme = window.localStorage.getItem("weakipedia-theme");

  if (storedTheme === "light" || storedTheme === "dark") {
    return storedTheme;
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

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

function normalizeSuggestionText(value: string) {
  return value.normalize("NFKC").toLocaleLowerCase().replace(/\s+/g, " ").trim();
}

function suggestionTitleMatchesSearchTerm(suggestion: Suggestion, searchTerm: string) {
  const normalizedSearchTerm = normalizeSuggestionText(searchTerm);
  const normalizedTitle = normalizeSuggestionText(suggestion.title);
  const normalizedTitleWithoutEntityId = normalizeSuggestionText(
    suggestion.title.replace(/\s+\((?:Q|P|L)\d+\)$/i, ""),
  );

  return (
    normalizedTitle === normalizedSearchTerm ||
    normalizedTitleWithoutEntityId === normalizedSearchTerm
  );
}

function exactSearchTermSuggestions(suggestions: Suggestion[], searchTerm: string) {
  return suggestions.filter((suggestion) => suggestionTitleMatchesSearchTerm(suggestion, searchTerm));
}

function displayValidationMessage(
  validation: ValidationState,
  hasExactSuggestion: boolean,
  showCreateSuggestion: boolean,
) {
  if (
    validation.status === "invalid" &&
    validation.message === "Choose a Wikipedia or Wikidata result."
  ) {
    return showCreateSuggestion
      ? "Select a match or create one."
      : hasExactSuggestion
        ? "Select a match and click Enter."
        : validation.message;
  }

  return validation.message;
}

function App() {
  const user = mockTelegramUser;
  const [themeMode, setThemeMode] = useState<ThemeMode>(getInitialThemeMode);
  const [articleUrl, setArticleUrl] = useState("");
  const [selectedSuggestionUrl, setSelectedSuggestionUrl] = useState("");
  const [selectedCreateValue, setSelectedCreateValue] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [validation, setValidation] = useState<ValidationState>({
    status: "idle",
    message: "",
  });
  const searchTerm = articleUrl.trim();
  const hasExactSuggestion = suggestions.some((suggestion) =>
    suggestionTitleMatchesSearchTerm(suggestion, searchTerm),
  );
  const showCreateSuggestion =
    suggestions.length > 0 && validation.status !== "valid" && Boolean(searchTerm) && !hasExactSuggestion;
  const hasSearchValue = articleUrl.length > 0;
  const nextThemeMode = themeMode === "light" ? "dark" : "light";
  const ThemeIcon = themeMode === "light" ? Moon : Sun;

  useEffect(() => {
    const virtualKeyboard = (navigator as NavigatorWithVirtualKeyboard).virtualKeyboard;

    if (virtualKeyboard) {
      virtualKeyboard.overlaysContent = true;
    }
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    window.localStorage.setItem("weakipedia-theme", themeMode);
  }, [themeMode]);

  useEffect(() => {
    function updatePortraitPadding() {
      const width = window.innerWidth;
      const height = window.innerHeight;
      let paddingTop = height * 0.15;

      if (width <= height) {
        const range = Math.max(height - 450, 1);
        const progress = Math.max(0, Math.min(1, (width - 450) / range));
        paddingTop = height * 0.15 * progress;
      }

      document.documentElement.style.setProperty(
        "--search-shell-portrait-padding-top",
        `${paddingTop}px`,
      );
    }

    updatePortraitPadding();
    window.addEventListener("resize", updatePortraitPadding);
    window.addEventListener("orientationchange", updatePortraitPadding);

    return () => {
      window.removeEventListener("resize", updatePortraitPadding);
      window.removeEventListener("orientationchange", updatePortraitPadding);
    };
  }, []);

  function resetSearch() {
    setArticleUrl("");
    setSelectedSuggestionUrl("");
    setSelectedCreateValue("");
    setSuggestions([]);
    setValidation({ status: "idle", message: "" });
  }

  function selectSuggestion(suggestion: Suggestion) {
    setSelectedSuggestionUrl(suggestion.url);
    setSelectedCreateValue("");
    setSuggestions([]);
    setValidation({ status: "valid", message: "" });
    setArticleUrl(suggestion.url);
  }

  function selectCreateSuggestion() {
    const createValue = `Create: ${searchTerm}`;
    setSelectedSuggestionUrl("");
    setSelectedCreateValue(createValue);
    setSuggestions([]);
    setValidation({ status: "valid", message: "" });
    setArticleUrl(createValue);
  }

  function submitSearch() {
    if (suggestions.length > 0) {
      selectSuggestion(suggestions[0]);
    }
  }

  function toggleTheme() {
    setThemeMode(nextThemeMode);
  }

  useEffect(() => {
    const trimmed = articleUrl.trim();

    if (!trimmed) {
      setSelectedSuggestionUrl("");
      setSuggestions([]);
      setValidation({ status: "idle", message: "" });
      return;
    }

    if (trimmed === selectedSuggestionUrl || trimmed === selectedCreateValue) {
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

          const exactSuggestions = exactSearchTermSuggestions(result.suggestions, trimmed);
          setSuggestions(exactSuggestions.length > 0 ? exactSuggestions : result.suggestions);
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
  }, [articleUrl, selectedCreateValue, selectedSuggestionUrl]);

  return (
    <div className="page">
      <header className="topbar">
        <div className="account">
          <button
            className="theme-button"
            type="button"
            aria-label={`Switch to ${nextThemeMode} mode`}
            title={`Switch to ${nextThemeMode} mode`}
            onClick={toggleTheme}
          >
            <ThemeIcon aria-hidden="true" strokeWidth={2} />
          </button>
          {user ? (
            <>
              <button className="logout-button" type="button">
                Logout
              </button>
              <img className="avatar" src={user.photoUrl} alt={user.name} />
            </>
          ) : (
            <button className="login-button" type="button">
              Login / Sign up
            </button>
          )}
        </div>
      </header>

      <main className="search-shell" aria-labelledby="page-title">
        <div className="brand">
          <div id="page-title" className="brand-text" role="heading" aria-level={1}>
            Weakipedia
          </div>
          <div className="brand-byline-layer" aria-hidden="true">
            <div className="brand-byline">
              <span className="brand-byline-by">by</span>
              <img
                className="brand-byline-favicon"
                src={VAYEHEE_FAVICON_URL}
                alt=""
              />
              <span className="brand-byline-name">ayehee</span>
            </div>
          </div>
        </div>
        <p className="tagline">
          In the Artificial Intelligence age,{" "}
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
          is <u>paramount</u>... but <u>flawed</u>. <strong>Fix it!</strong>
        </p>
        <form
          className="search-form"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            submitSearch();
          }}
        >
          <div className="input-row">
            <div className="input-field">
              <Search className="input-icon" aria-hidden="true" strokeWidth={2} />
              <input
                aria-label="Wikipedia article URL"
                className="url-input"
                enterKeyHint="search"
                inputMode="search"
                placeholder="Search or paste Wikipedia article URL..."
                type="search"
                value={articleUrl}
                onChange={(event) => {
                  setSelectedSuggestionUrl("");
                  setSelectedCreateValue("");
                  setArticleUrl(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") {
                    return;
                  }

                  event.preventDefault();
                  submitSearch();
                }}
              />
              {hasSearchValue ? (
                <button
                  className="clear-search-button"
                  type="button"
                  aria-label="Clear search"
                  onClick={resetSearch}
                >
                  <X aria-hidden="true" strokeWidth={2} />
                </button>
              ) : null}
            </div>
          </div>
          {suggestions.length > 0 ? (
            <div className="suggestions-tray" role="listbox" aria-label="Search suggestions">
              {suggestions.map((suggestion) => (
                <button
                  className="suggestion-option"
                  key={suggestion.url}
                  type="button"
                  onClick={() => selectSuggestion(suggestion)}
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
              {showCreateSuggestion ? (
                <button
                  className="suggestion-option suggestion-create-option"
                  type="button"
                  onClick={selectCreateSuggestion}
                >
                  <img
                    className="suggestion-favicon"
                    src={VAYEHEE_FAVICON_URL}
                    alt=""
                    aria-hidden="true"
                  />
                  <span className="suggestion-title">
                    Create <strong>{searchTerm}</strong>
                  </span>
                  <span className="suggestion-description">
                    Build the resource for AI to inform from...
                  </span>
                </button>
              ) : null}
            </div>
          ) : null}
          <p
            className={`validation-message ${
              validation.status === "invalid" ? "is-error" : ""
            }`}
            aria-live="polite"
          >
            {validation.status === "checking" ? (
              <span className="checking-status">
                <LoaderCircle className="checking-spinner" aria-hidden="true" />
                <span>Checking...</span>
              </span>
            ) : (
              displayValidationMessage(validation, hasExactSuggestion, showCreateSuggestion)
            )}
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
