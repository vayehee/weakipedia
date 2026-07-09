import React, { useEffect, useRef, useState } from "react";
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
    ? "https://wikimedia-search-420014165339.europe-west1.run.app"
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

type SubmitState = "idle" | "submitting" | "error";

type ResolveResponse = {
  canSubmit: boolean;
  message: string;
  status: ValidationState["status"];
  suggestions: Suggestion[];
};

type StaticTargetResponse = {
  canonicalTitle: string;
  canonicalUrl: string;
  entityType: string;
  lang: string;
  route: string;
  targetId: string;
  titleSlug: string;
};

type StaticBuildStepRunResponse = {
  message: string;
  status: "success" | "error";
  stepId: string;
};

type ThemeMode = "light" | "dark";

const DASHBOARD_TABS = [
  { id: "overview", label: "Overview" },
  { id: "views", label: "Views" },
  { id: "news", label: "News" },
  { id: "traffic", label: "Traffic" },
  { id: "claims", label: "Claims" },
  { id: "edits", label: "Edits" },
  { id: "editors", label: "Editors" },
] as const;

type DashboardView = (typeof DASHBOARD_TABS)[number]["id"];

type StaticDashboardRoute = {
  lang: string | null;
  targetId: string;
  titleSlug: string | null;
  view: DashboardView;
};

type StaticBuildStepStatus = "pending" | "active" | "success" | "error";

type StaticBuildStep = {
  id: string;
  label: string;
  status: StaticBuildStepStatus;
  error?: string;
};

type StaticBuildStepDefinition = {
  id: string;
  label: string;
};

const STATIC_BUILD_STEPS = [
  {
    id: "article_identity",
    label: "Resolving Wikipedia article identity, namespace, redirects, and Wikidata entities...",
  },
  {
    id: "article_parse",
    label: "Processing article structure, sections, links, categories, templates, and citations...",
  },
  {
    id: "article_revisions",
    label: "Retrieving revision history and recent edit records...",
  },
  {
    id: "article_authorship",
    label: "Attributing current article revision text to contributing editors...",
  },
  {
    id: "pageviews_human",
    label: "Measuring human readership over time...",
  },
  {
    id: "pageviews_mobile_web",
    label: "Measuring mobile web readership over time...",
  },
  {
    id: "pageviews_mobile_app",
    label: "Measuring mobile app readership over time...",
  },
  {
    id: "pageviews_spider",
    label: "Measuring crawler and spider access patterns...",
  },
  {
    id: "pageviews_automated",
    label: "Measuring machine access patterns...",
  },
  {
    id: "traffic_incoming",
    label: "Mapping incoming traffic pathways to the article...",
  },
  {
    id: "traffic_outgoing",
    label: "Mapping outgoing traffic pathways from the article...",
  },
  {
    id: "editor_summary",
    label: "Summarizing editor activity and article stewardship signals...",
  },
  {
    id: "article_claims",
    label: "Processing article claims, arguments, and statements...",
  },
  {
    id: "claim_sources",
    label: "Mapping claims to citations and external source material...",
  },
  {
    id: "wikidata_entity",
    label: "Processing associated Wikidata entity labels, descriptions, sitelinks, and claims...",
  },
  {
    id: "google_trends",
    label: "Retrieving broader interest patterns around the article subject...",
  },
  {
    id: "google_news",
    label: "Retrieving recent publications around the article subject...",
  },
] as const;

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

async function createStaticTarget(selectedUrl: string) {
  const api = new URL("/static-targets", WIKIMEDIA_SEARCH_API_URL);
  const response = await fetch(api, {
    body: JSON.stringify({ selectedUrl }),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });

  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(error?.detail ?? "Unable to create this static target.");
  }

  return (await response.json()) as StaticTargetResponse;
}

async function readStaticTarget(targetId: string, signal: AbortSignal) {
  const api = new URL(`/static-targets/${encodeURIComponent(targetId)}`, WIKIMEDIA_SEARCH_API_URL);
  const response = await fetch(api, { signal });

  if (!response.ok) {
    throw new Error("Unable to read this static target.");
  }

  return (await response.json()) as StaticTargetResponse;
}

async function runStaticTargetBuildStep(
  targetId: string,
  stepId: string,
  signal: AbortSignal,
) {
  const api = new URL(
    `/static-targets/${encodeURIComponent(targetId)}/build-steps/${encodeURIComponent(stepId)}`,
    WIKIMEDIA_SEARCH_API_URL,
  );
  const response = await fetch(api, {
    method: "POST",
    signal,
  });

  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(error?.detail ?? "Unable to run this static build step.");
  }

  return (await response.json()) as StaticBuildStepRunResponse;
}

function wikipediaCreateSlug(value: string) {
  return value.trim().replace(/\s+/g, "_");
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
  if (value === "stats") {
    return "overview";
  }

  return DASHBOARD_TABS.some((tab) => tab.id === value) ? (value as DashboardView) : "overview";
}

function getDashboardViewLabel(view: DashboardView) {
  if (view === "overview") {
    return "OVERVIEW";
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
  return "July 8, 2026";
}

function createStaticBuildSteps(): StaticBuildStep[] {
  return STATIC_BUILD_STEPS.map((step: StaticBuildStepDefinition) => ({
    id: step.id,
    label: step.label,
    status: "pending",
  }));
}

function getStaticDashboardRoute(location: Location): StaticDashboardRoute | null {
  const { pathname, search } = location;
  const searchParams = new URLSearchParams(search);

  if (pathname === "/static") {
    const targetId = searchParams.get("target");

    if (targetId) {
      return {
        lang: searchParams.get("lang"),
        targetId,
        titleSlug: searchParams.get("title"),
        view: getDashboardView(searchParams.get("view")),
      };
    }
  }

  const targetPathMatch = pathname.match(/^\/static\/target\/([^/]+)\/?$/);

  if (targetPathMatch) {
    return {
      lang: searchParams.get("lang"),
      targetId: decodeURIComponent(targetPathMatch[1]),
      titleSlug: searchParams.get("title"),
      view: getDashboardView(searchParams.get("view")),
    };
  }

  const targetEqualsMatch = pathname.match(/^\/static\/target=([^/]+)\/?$/);

  if (targetEqualsMatch) {
    return {
      lang: searchParams.get("lang"),
      targetId: decodeURIComponent(targetEqualsMatch[1]),
      titleSlug: searchParams.get("title"),
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
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [themeMode, setThemeMode] = useState<ThemeMode>(getInitialThemeMode);
  const [articleUrl, setArticleUrl] = useState("");
  const [selectedSuggestionUrl, setSelectedSuggestionUrl] = useState("");
  const [selectedCreateValue, setSelectedCreateValue] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [submitError, setSubmitError] = useState("");
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
    setSubmitState("idle");
    setSubmitError("");
    setSuggestions([]);
    setValidation({ status: "idle", message: "" });
  }

  function selectSuggestion(suggestion: Suggestion) {
    setSelectedSuggestionUrl(suggestion.url);
    setSelectedCreateValue("");
    setSubmitState("idle");
    setSubmitError("");
    setSuggestions([]);
    setValidation({ status: "valid", message: "" });
    setArticleUrl(suggestion.url);
    window.setTimeout(() => searchInputRef.current?.focus(), 0);
  }

  function selectCreateSuggestion() {
    const createValue = `Create: ${searchTerm}`;
    setSelectedSuggestionUrl("");
    setSelectedCreateValue(createValue);
    setSubmitState("idle");
    setSubmitError("");
    setSuggestions([]);
    setValidation({ status: "valid", message: "" });
    setArticleUrl(createValue);
    window.setTimeout(() => searchInputRef.current?.focus(), 0);
  }

  async function submitSearch() {
    if (!hasSelectedSearchValue || submitState === "submitting") {
      return;
    }

    setSubmitState("submitting");
    setSubmitError("");

    try {
      if (selectedCreateValue && searchTerm === selectedCreateValue) {
        const createSearchTerm = selectedCreateValue.replace(/^Create:\s*/i, "");
        window.location.assign(`/create/${encodeURIComponent(wikipediaCreateSlug(createSearchTerm))}`);
        return;
      }

      const target = await createStaticTarget(selectedSuggestionUrl);
      window.location.assign(target.route);
    } catch (error) {
      setSubmitState("error");
      setSubmitError((error as Error).message);
    }
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
        lang={staticDashboardRoute.lang}
        targetId={staticDashboardRoute.targetId}
        titleSlug={staticDashboardRoute.titleSlug}
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
                ref={searchInputRef}
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
                  setSubmitState("idle");
                  setSubmitError("");
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
                  onMouseDown={(event) => event.preventDefault()}
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
                  onMouseDown={(event) => event.preventDefault()}
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
              submitState !== "submitting" &&
              (validation.status === "invalid" || hasSelectedSearchValue || submitState === "error")
                ? "is-error"
                : ""
            }`}
            aria-live="polite"
          >
            {submitState === "submitting" ? (
              <span className="checking-status">
                <LoaderCircle className="checking-spinner" aria-hidden="true" />
                <span>Submitted...</span>
              </span>
            ) : submitState === "error" ? (
              submitError
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
  lang: string | null;
  activeView: DashboardView;
  nextThemeMode: ThemeMode;
  ThemeIcon: typeof Moon;
  titleSlug: string | null;
  onToggleTheme: () => void;
};

function StaticDashboardPage({
  lang,
  targetId,
  titleSlug,
  activeView,
  nextThemeMode,
  ThemeIcon,
  onToggleTheme,
}: StaticDashboardPageProps) {
  const [dashboardSearch, setDashboardSearch] = useState("");
  const [staticTarget, setStaticTarget] = useState<StaticTargetResponse | null>(null);
  const [staticTargetLookupFailed, setStaticTargetLookupFailed] = useState(false);
  const [staticBuildSteps, setStaticBuildSteps] = useState<StaticBuildStep[]>(createStaticBuildSteps);
  const targetTitle = staticTarget?.canonicalTitle ?? getTargetTitle(targetId);
  const targetFetchDate = getTargetFetchDate();
  const dashboardViewLabel = getDashboardViewLabel(activeView);
  const publicTargetSlug = titleSlug ?? staticTarget?.titleSlug ?? targetId;
  const isStaticBuildComplete = staticBuildSteps.every(
    (step) => step.status === "success" || step.status === "error",
  );
  const hasStaticBuildErrors = staticBuildSteps.some((step) => step.status === "error");

  useEffect(() => {
    if (targetId.toLocaleLowerCase() === "test") {
      setStaticTarget(null);
      setStaticTargetLookupFailed(false);
      return;
    }

    const controller = new AbortController();
    setStaticTargetLookupFailed(false);

    async function loadStaticTarget() {
      try {
        if (lang && titleSlug) {
          const recoveredTarget = await createStaticTarget(
            `https://${lang}.wikipedia.org/wiki/${titleSlug}`,
          );

          if (!controller.signal.aborted) {
            setStaticTarget(recoveredTarget);
          }
          return;
        }

        const target = await readStaticTarget(targetId, controller.signal);
        if (!controller.signal.aborted) {
          setStaticTarget(target);
        }
      } catch (error: unknown) {
        if ((error as Error).name === "AbortError" || controller.signal.aborted) {
          return;
        }

        setStaticTargetLookupFailed(true);
      }
    }

    void loadStaticTarget();

    return () => controller.abort();
  }, [lang, targetId, titleSlug]);

  useEffect(() => {
    if (!staticTargetLookupFailed) {
      return;
    }

    setStaticBuildSteps((currentSteps) =>
      currentSteps.map((step, index) =>
        index === 0
          ? {
              ...step,
              status: "error",
              error: "Static target metadata could not be loaded from the backend.",
            }
          : step,
      ),
    );
  }, [staticTargetLookupFailed]);

  useEffect(() => {
    setStaticBuildSteps(createStaticBuildSteps());

    if (!staticTarget) {
      return;
    }

    const controller = new AbortController();

    async function runBuildSteps() {
      for (const step of STATIC_BUILD_STEPS) {
        if (controller.signal.aborted) {
          return;
        }

        setStaticBuildSteps((currentSteps) =>
          currentSteps.map((currentStep) =>
            currentStep.id === step.id
              ? { ...currentStep, status: "active", error: undefined }
              : currentStep,
          ),
        );

        try {
          const result = await runStaticTargetBuildStep(staticTarget.targetId, step.id, controller.signal);

          if (controller.signal.aborted) {
            return;
          }

          setStaticBuildSteps((currentSteps) =>
            currentSteps.map((currentStep) =>
              currentStep.id === step.id
                ? {
                    ...currentStep,
                    status: result.status,
                    error: result.status === "error" ? result.message : undefined,
                  }
                : currentStep,
            ),
          );
        } catch (error) {
          if ((error as Error).name === "AbortError" || controller.signal.aborted) {
            return;
          }

          setStaticBuildSteps((currentSteps) =>
            currentSteps.map((currentStep) =>
              currentStep.id === step.id
                ? {
                    ...currentStep,
                    status: "error",
                    error: (error as Error).message,
                  }
                : currentStep,
            ),
          );
        }
      }
    }

    void runBuildSteps();

    return () => controller.abort();
  }, [staticTarget]);

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
              href={`/static?target=${encodeURIComponent(publicTargetSlug)}${
                lang ? `&lang=${encodeURIComponent(lang)}` : ""
              }${titleSlug ? `&title=${encodeURIComponent(titleSlug)}` : ""}&view=${tab.id}`}
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
              aria-label="refresh data"
              title="refresh data"
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
            {staticTargetLookupFailed
              ? "This target route exists, but its temporary metadata cache is no longer available. Persistent target storage is the next backend step."
              : "This frozen dashboard will show the article, traffic, views, edits, claims, sources, and related signals captured for this target."}
          </p>
        </section>

        {isStaticBuildComplete && !hasStaticBuildErrors ? (
          <section className="dashboard-grid" aria-label="Static dashboard sections">
            <DashboardPanel title="Overview" body="Resolved identity, canonical title, and build date." />
            <DashboardPanel title="Article" body="Parsed sections, links, categories, and current text." />
            <DashboardPanel title="Views" body="Desktop, mobile, spider, and automated pageview trends." />
            <DashboardPanel title="Traffic" body="Inbound and outbound navigation from Wikinav." />
            <DashboardPanel title="Editors" body="Revision activity and article-specific editor analysis." />
            <DashboardPanel title="Claims & sources" body="Arguments detected in the article and the sources mapped to them." />
          </section>
        ) : (
          <StaticBuildMonitor steps={staticBuildSteps} />
        )}
      </main>
    </div>
  );
}

type StaticBuildMonitorProps = {
  steps: StaticBuildStep[];
};

function StaticBuildMonitor({ steps }: StaticBuildMonitorProps) {
  return (
    <section className="static-build-monitor" aria-label="Static target build progress">
      <ol className="static-build-list">
        {steps.map((step) => (
          <li className={`static-build-step is-${step.status}`} key={step.label}>
            <span className="static-build-step-label">{step.label}</span>
            {step.status === "active" ? (
              <LoaderCircle className="static-build-spinner" aria-hidden="true" />
            ) : null}
            {step.status === "error" && step.error ? (
              <span className="static-build-error-message">{step.error}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
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
