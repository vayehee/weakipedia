import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { LoaderCircle, Moon, RefreshCw, Search, Sun, X } from "lucide-react";
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
const WIKIPEDIA_FAVICON_URL = "https://www.wikipedia.org/static/favicon/wikipedia.ico";

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

const DASHBOARD_TABS = [
  { id: "stats", label: "Stats" },
  { id: "views", label: "Views" },
  { id: "news", label: "News" },
  { id: "traffic", label: "Traffic" },
  { id: "claims", label: "Claims" },
  { id: "edits", label: "Edits" },
  { id: "editors", label: "Editors" },
] as const;

type DashboardView = (typeof DASHBOARD_TABS)[number]["id"];

type StaticDashboardRoute = {
  targetId: string;
  view: DashboardView;
};

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
  return value
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase()
    .replace(/\s+/g, " ")
    .trim();
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

function getDashboardView(value: string | null): DashboardView {
  return DASHBOARD_TABS.some((tab) => tab.id === value) ? (value as DashboardView) : "stats";
}

function getDashboardViewLabel(view: DashboardView) {
  if (view === "stats") {
    return "STATISTICS";
  }

  return view.toLocaleUpperCase();
}

function getTargetTitle(targetId: string) {
  if (targetId.toLocaleLowerCase() === "test") {
    return "Test";
  }

  return targetId.replace(/[_-]+/g, " ").replace(/\b\p{L}/gu, (letter) => letter.toLocaleUpperCase());
}

function getTargetFetchDate() {
  return "Jul 08, 2026";
}

function getStaticDashboardRoute(location: Location): StaticDashboardRoute | null {
  const { pathname, search } = location;
  const searchParams = new URLSearchParams(search);

  if (pathname === "/static") {
    const targetId = searchParams.get("target");

    if (targetId) {
      return {
        targetId,
        view: getDashboardView(searchParams.get("view")),
      };
    }
  }

  const targetPathMatch = pathname.match(/^\/static\/target\/([^/]+)\/?$/);

  if (targetPathMatch) {
    return {
      targetId: decodeURIComponent(targetPathMatch[1]),
      view: getDashboardView(searchParams.get("view")),
    };
  }

  const targetEqualsMatch = pathname.match(/^\/static\/target=([^/]+)\/?$/);

  if (targetEqualsMatch) {
    return {
      targetId: decodeURIComponent(targetEqualsMatch[1]),
      view: getDashboardView(searchParams.get("view")),
    };
  }

  return null;
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
  const staticDashboardRoute = getStaticDashboardRoute(window.location);
  const user = mockTelegramUser;
  const [themeMode, setThemeMode] = useState<ThemeMode>(getInitialThemeMode);
  const [articleUrl, setArticleUrl] = useState("");
  const [selectedSuggestionUrl, setSelectedSuggestionUrl] = useState("");
  const [selectedCreateValue, setSelectedCreateValue] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [isSubmitted, setIsSubmitted] = useState(false);
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
  const hasSelectedSearchValue =
    Boolean(searchTerm) && (searchTerm === selectedSuggestionUrl || searchTerm === selectedCreateValue);
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
    setIsSubmitted(false);
    setSuggestions([]);
    setValidation({ status: "idle", message: "" });
  }

  function selectSuggestion(suggestion: Suggestion) {
    setSelectedSuggestionUrl(suggestion.url);
    setSelectedCreateValue("");
    setIsSubmitted(false);
    setSuggestions([]);
    setValidation({ status: "valid", message: "" });
    setArticleUrl(suggestion.url);
  }

  function selectCreateSuggestion() {
    const createValue = `Create: ${searchTerm}`;
    setSelectedSuggestionUrl("");
    setSelectedCreateValue(createValue);
    setIsSubmitted(false);
    setSuggestions([]);
    setValidation({ status: "valid", message: "" });
    setArticleUrl(createValue);
  }

  function submitSearch() {
    if (!hasSelectedSearchValue) {
      return;
    }

    setIsSubmitted(true);
  }

  function toggleTheme() {
    setThemeMode(nextThemeMode);
  }

  function blockKeyboardTraySelection(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
    }
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

  if (staticDashboardRoute) {
    return (
      <StaticDashboardPage
        targetId={staticDashboardRoute.targetId}
        activeView={staticDashboardRoute.view}
        nextThemeMode={nextThemeMode}
        ThemeIcon={ThemeIcon}
        onToggleTheme={toggleTheme}
      />
    );
  }

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
        <BrandLogo id="page-title" />
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
                  setIsSubmitted(false);
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
                  onKeyDown={blockKeyboardTraySelection}
                  onKeyUp={blockKeyboardTraySelection}
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
                  onKeyDown={blockKeyboardTraySelection}
                  onKeyUp={blockKeyboardTraySelection}
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
              validation.status === "invalid" || (hasSelectedSearchValue && !isSubmitted)
                ? "is-error"
                : ""
            }`}
            aria-live="polite"
          >
            {isSubmitted ? (
              <span className="checking-status">
                <LoaderCircle className="checking-spinner" aria-hidden="true" />
                <span>Submitted...</span>
              </span>
            ) : hasSelectedSearchValue ? (
              <>
                Click Enter (keyboard) or{" "}
                <button className="inline-submit-button" type="button" onClick={submitSearch}>
                  here
                </button>{" "}
                to submit.
              </>
            ) : validation.status === "checking" ? (
              <span className="checking-status">
                <LoaderCircle className="checking-spinner" aria-hidden="true" />
                <span>Checking...</span>
              </span>
            ) : (
              displayValidationMessage(validation, hasExactSuggestion, showCreateSuggestion)
            )}
          </p>
          <p className="editor-claim">I am a Wikipedia editor</p>
        </form>
      </main>
    </div>
  );
}

type StaticDashboardPageProps = {
  targetId: string;
  activeView: DashboardView;
  nextThemeMode: ThemeMode;
  ThemeIcon: typeof Moon;
  onToggleTheme: () => void;
};

function StaticDashboardPage({
  targetId,
  activeView,
  nextThemeMode,
  ThemeIcon,
  onToggleTheme,
}: StaticDashboardPageProps) {
  const [dashboardSearch, setDashboardSearch] = useState("");
  const targetTitle = getTargetTitle(targetId);
  const targetFetchDate = getTargetFetchDate();
  const dashboardViewLabel = getDashboardViewLabel(activeView);

  function requestRefresh() {
    window.alert("Login / Sign up is required to refresh this dashboard.");
  }

  return (
    <div className="page static-dashboard-page">
      <header className="dashboard-topbar">
        <a className="dashboard-brand-link" href="/" aria-label="Back to Weakipedia search">
          <BrandLogo className="dashboard-brand" />
        </a>
        <form
          className="dashboard-search-form"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
          }}
        >
          <div className="input-field dashboard-input-field">
            <Search className="input-icon" aria-hidden="true" strokeWidth={2} />
            <input
              aria-label="Wikipedia article URL"
              className="url-input"
              enterKeyHint="search"
              inputMode="search"
              placeholder="Search or paste Wikipedia article URL..."
              type="search"
              value={dashboardSearch}
              onChange={(event) => setDashboardSearch(event.target.value)}
            />
            {dashboardSearch.length > 0 ? (
              <button
                className="clear-search-button"
                type="button"
                aria-label="Clear search"
                onClick={() => setDashboardSearch("")}
              >
                <X aria-hidden="true" strokeWidth={2} />
              </button>
            ) : null}
          </div>
        </form>
        <div className="account dashboard-account">
          <button
            className="theme-button"
            type="button"
            aria-label={`Switch to ${nextThemeMode} mode`}
            title={`Switch to ${nextThemeMode} mode`}
            onClick={onToggleTheme}
          >
            <ThemeIcon aria-hidden="true" strokeWidth={2} />
          </button>
          <button className="login-button" type="button">
            Login / Sign up
          </button>
        </div>
        <nav className="dashboard-tabs" aria-label="Dashboard views">
          {DASHBOARD_TABS.map((tab) => (
            <a
              className={`dashboard-tab ${activeView === tab.id ? "is-active" : ""}`}
              href={`/static?target=${encodeURIComponent(targetId)}&view=${tab.id}`}
              key={tab.id}
              aria-current={activeView === tab.id ? "page" : undefined}
            >
              {tab.label}
            </a>
          ))}
        </nav>
      </header>

      <main className="dashboard-shell">
        <section className="dashboard-hero" aria-labelledby="dashboard-title">
          <div className="dashboard-kicker">
            <span>
              {dashboardViewLabel} | {targetFetchDate}
            </span>
            <button
              className="dashboard-refresh-button"
              type="button"
              aria-label="Refresh dashboard"
              title="Login / Sign up required to refresh"
              onClick={requestRefresh}
            >
              <RefreshCw aria-hidden="true" strokeWidth={2} />
            </button>
          </div>
          <h1 id="dashboard-title" className="dashboard-title">
            <img className="dashboard-title-favicon" src={WIKIPEDIA_FAVICON_URL} alt="" />
            <span>{targetTitle}</span>
          </h1>
          <p>
            This frozen dashboard will show the article, traffic, views, edits, claims,
            sources, and related signals captured for this target.
          </p>
        </section>

        <section className="dashboard-grid" aria-label="Static dashboard sections">
          <DashboardPanel title="Overview" body="Resolved identity, canonical title, and build date." />
          <DashboardPanel title="Article" body="Parsed sections, links, categories, and current text." />
          <DashboardPanel title="Views" body="Desktop, mobile, spider, and automated pageview trends." />
          <DashboardPanel title="Traffic" body="Inbound and outbound navigation from Wikinav." />
          <DashboardPanel title="Editors" body="Revision activity and article-specific editor analysis." />
          <DashboardPanel title="Claims & sources" body="Arguments detected in the article and the sources mapped to them." />
        </section>
      </main>
    </div>
  );
}

type BrandLogoProps = {
  className?: string;
  id?: string;
};

function BrandLogo({ className = "", id }: BrandLogoProps) {
  return (
    <div className={`brand ${className}`.trim()}>
      <div id={id} className="brand-text" role="heading" aria-level={1}>
        Weakipedia
      </div>
      <div className="brand-byline-layer" aria-hidden="true">
        <div className="brand-byline">
          <span className="brand-byline-by">by</span>
          <img className="brand-byline-favicon" src={VAYEHEE_FAVICON_URL} alt="" />
          <span className="brand-byline-name">ayehee</span>
        </div>
      </div>
    </div>
  );
}

type DashboardPanelProps = {
  title: string;
  body: string;
};

function DashboardPanel({ title, body }: DashboardPanelProps) {
  return (
    <article className="dashboard-panel">
      <h2>{title}</h2>
      <p>{body}</p>
    </article>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
