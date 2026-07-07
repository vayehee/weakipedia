import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const mockTelegramUser = null as
  | null
  | {
      name: string;
      photoUrl: string;
    };

type ProjectKind = "wikipedia" | "wikidata";

type ParsedProjectUrl = {
  kind: ProjectKind;
  host: string;
  title: string;
};

type Suggestion = {
  description: string;
  faviconUrl: string;
  source: string;
  title: string;
  url: string;
};

type ParseError =
  | { error: "caseA" }
  | { error: "caseB"; kind: ProjectKind }
  | { error: "caseC"; kind: ProjectKind };

type ValidationState =
  | { status: "idle"; message: "" }
  | { status: "checking"; message: "" }
  | { status: "invalid"; message: string }
  | { status: "valid"; message: "" };

const ERROR_MESSAGES = {
  caseA: "URL need to point to a Wikipedia or a Wikidata project.",
} as const;

const FALLBACK_WIKIPEDIA_SEARCH_HOSTS = [
  "en.wikipedia.org",
  "fr.wikipedia.org",
  "de.wikipedia.org",
  "es.wikipedia.org",
  "it.wikipedia.org",
  "pt.wikipedia.org",
  "nl.wikipedia.org",
  "pl.wikipedia.org",
  "ru.wikipedia.org",
  "uk.wikipedia.org",
  "ar.wikipedia.org",
  "he.wikipedia.org",
  "fa.wikipedia.org",
  "hi.wikipedia.org",
  "ja.wikipedia.org",
  "ko.wikipedia.org",
  "zh.wikipedia.org",
  "id.wikipedia.org",
  "tr.wikipedia.org",
  "vi.wikipedia.org",
] as const;

let wikipediaHostsPromise: Promise<string[]> | null = null;

function projectName(kind: ProjectKind) {
  return kind === "wikipedia" ? "Wikipedia" : "Wikidata";
}

function validationMessage(error: ParseError) {
  if (error.error === "caseA") {
    return ERROR_MESSAGES.caseA;
  }

  if (error.error === "caseB") {
    return `URL need to point to a ${projectName(error.kind)} asset/article/record/page.`;
  }

  return `URL need to point to an existing ${projectName(error.kind)} asset/article/record/page.`;
}

function canonicalWikipediaUrl(host: string, title: string) {
  return `https://${host}/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
}

function canonicalWikidataUrl(entityId: string) {
  return `https://www.wikidata.org/wiki/${entityId}`;
}

function faviconUrl(host: string) {
  return `https://${host}/favicon.ico`;
}

function isWikipediaHost(host: string) {
  return /^[a-z0-9-]+\.wikipedia\.org$/.test(host);
}

function isWikidataHost(host: string) {
  return host === "wikidata.org" || host === "www.wikidata.org";
}

function titleFromPath(url: URL) {
  if (url.pathname.startsWith("/wiki/")) {
    return decodeURIComponent(url.pathname.slice("/wiki/".length)).replace(/_/g, " ");
  }

  if (url.pathname === "/w/index.php") {
    return url.searchParams.get("title")?.replace(/_/g, " ") ?? "";
  }

  return "";
}

function looksLikeUrl(value: string) {
  const trimmed = value.trim();

  return (
    /^https?:\/\//i.test(trimmed) ||
    trimmed.includes("wikipedia.org") ||
    trimmed.includes("wikidata.org")
  );
}

function parseProjectUrl(value: string): ParsedProjectUrl | ParseError {
  let url: URL;

  try {
    url = new URL(value.trim());
  } catch {
    return { error: "caseA" };
  }

  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return { error: "caseA" };
  }

  const host = url.hostname.toLowerCase();

  if (isWikipediaHost(host)) {
    const title = titleFromPath(url).trim();

    if (!title || title === "Main Page") {
      return { error: "caseB", kind: "wikipedia" };
    }

    return { kind: "wikipedia", host, title };
  }

  if (isWikidataHost(host)) {
    const title = titleFromPath(url).trim();

    if (!title) {
      return { error: "caseB", kind: "wikidata" };
    }

    return { kind: "wikidata", host: "www.wikidata.org", title };
  }

  return { error: "caseA" };
}

function uniqueSuggestions(suggestions: Suggestion[]) {
  const seen = new Set<string>();

  return suggestions.filter((suggestion) => {
    if (seen.has(suggestion.url)) {
      return false;
    }

    seen.add(suggestion.url);
    return true;
  });
}

function normalizeSearchText(value: string) {
  return value.toLocaleLowerCase().normalize("NFKC").replace(/\s+/g, " ").trim();
}

function filterSuggestionsForQuery(suggestions: Suggestion[], query: string) {
  const normalizedQuery = normalizeSearchText(query);
  const queryTokens = normalizedQuery.split(" ").filter(Boolean);

  if (normalizedQuery.length < 2) {
    return suggestions;
  }

  const titleMatches = suggestions.filter((suggestion) => {
    const title = normalizeSearchText(suggestion.title);

    return title.includes(normalizedQuery) || queryTokens.every((token) => title.includes(token));
  });

  if (titleMatches.length > 0) {
    return titleMatches;
  }

  return suggestions.filter((suggestion) =>
    queryTokens.every((token) =>
      normalizeSearchText(`${suggestion.title} ${suggestion.description}`).includes(token),
    ),
  );
}

function cleanSnippet(value = "") {
  const withoutTags = value.replace(/<[^>]*>/g, "");
  const textarea = document.createElement("textarea");
  textarea.innerHTML = withoutTags;
  return textarea.value;
}

async function wikipediaSearchHosts() {
  if (!wikipediaHostsPromise) {
    wikipediaHostsPromise = fetch(
      "https://meta.wikimedia.org/w/api.php?action=sitematrix&format=json&origin=*&smtype=language",
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error("Unable to load Wikimedia site matrix.");
        }

        return response.json() as Promise<{
          sitematrix: Record<
            string,
            | {
                site?: Array<{
                  closed?: string;
                  code: string;
                  url: string;
                }>;
              }
            | number
          >;
        }>;
      })
      .then((data) => {
        const hosts = Object.values(data.sitematrix).flatMap((entry) => {
          if (typeof entry !== "object" || !entry.site) {
            return [];
          }

          return entry.site
            .filter((site) => site.code === "wiki" && !("closed" in site))
            .map((site) => {
              try {
                return new URL(site.url).hostname.toLowerCase();
              } catch {
                return "";
              }
            })
            .filter((host) => isWikipediaHost(host));
        });

        const priorityRank = new Map(
          FALLBACK_WIKIPEDIA_SEARCH_HOSTS.map((host, index) => [host, index]),
        );
        const uniqueHosts = [...new Set(hosts)];

        return uniqueHosts.sort((left, right) => {
          const leftPriority = priorityRank.get(
            left as (typeof FALLBACK_WIKIPEDIA_SEARCH_HOSTS)[number],
          );
          const rightPriority = priorityRank.get(
            right as (typeof FALLBACK_WIKIPEDIA_SEARCH_HOSTS)[number],
          );

          if (leftPriority === undefined && rightPriority === undefined) {
            return left.localeCompare(right);
          }

          if (leftPriority === undefined) {
            return 1;
          }

          if (rightPriority === undefined) {
            return -1;
          }

          return leftPriority - rightPriority;
        });
      })
      .catch(() => [...FALLBACK_WIKIPEDIA_SEARCH_HOSTS]);
  }

  return wikipediaHostsPromise;
}

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  signal: AbortSignal,
  mapper: (item: T) => Promise<R>,
) {
  const results: R[] = new Array(items.length);
  let nextIndex = 0;

  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, async () => {
      while (nextIndex < items.length && !signal.aborted) {
        const currentIndex = nextIndex;
        const item = items[nextIndex];
        nextIndex += 1;
        results[currentIndex] = await mapper(item);
      }
    }),
  );

  return results.filter((result): result is R => Boolean(result));
}

async function exactWikipediaSuggestion(parsed: ParsedProjectUrl, signal: AbortSignal) {
  const api = new URL(`https://${parsed.host}/w/api.php`);
  api.search = new URLSearchParams({
    action: "query",
    format: "json",
    origin: "*",
    prop: "info",
    redirects: "1",
    titles: parsed.title,
  }).toString();

  const response = await fetch(api, { signal });

  if (!response.ok) {
    return false;
  }

  const data = (await response.json()) as {
    query?: {
      pages?: Record<string, { missing?: string; ns?: number; title: string }>;
    };
  };

  const page = Object.values(data.query?.pages ?? {})[0];

  if (!page || "missing" in page || (page.ns !== 0 && page.ns !== 2)) {
    return null;
  }

  return {
    description: page.ns === 2 ? "User page" : "Article",
    faviconUrl: faviconUrl(parsed.host),
    source: parsed.host,
    title: page.title,
    url: canonicalWikipediaUrl(parsed.host, page.title),
  };
}

async function searchWikipedia(parsed: ParsedProjectUrl, signal: AbortSignal) {
  const api = new URL(`https://${parsed.host}/w/api.php`);
  api.search = new URLSearchParams({
    action: "query",
    format: "json",
    origin: "*",
    list: "search",
    srnamespace: "0|2",
    srlimit: "5",
    srsearch: parsed.title,
  }).toString();

  const response = await fetch(api, { signal });

  if (!response.ok) {
    return [];
  }

  const data = (await response.json()) as {
    query?: {
      search?: Array<{ snippet?: string; title: string }>;
    };
  };

  return (data.query?.search ?? []).map((result) => ({
    description: cleanSnippet(result.snippet),
    faviconUrl: faviconUrl(parsed.host),
    source: parsed.host,
    title: result.title,
    url: canonicalWikipediaUrl(parsed.host, result.title),
  }));
}

async function searchWikipediaHost(host: string, query: string, signal: AbortSignal) {
  const api = new URL(`https://${host}/w/api.php`);
  api.search = new URLSearchParams({
    action: "opensearch",
    format: "json",
    limit: "3",
    namespace: "0",
    origin: "*",
    search: query,
  }).toString();

  const response = await fetch(api, { signal });

  if (!response.ok) {
    return [];
  }

  const data = (await response.json()) as [string, string[], string[], string[]];
  const [, titles = [], descriptions = [], urls = []] = data;

  return titles.map((title, index) => ({
    description: descriptions[index] ?? "",
    faviconUrl: faviconUrl(host),
    source: host,
    title,
    url: urls[index] || canonicalWikipediaUrl(host, title),
  }));
}

async function exactWikidataSuggestion(parsed: ParsedProjectUrl, signal: AbortSignal) {
  const entityId = parsed.title.match(/^(Q\d+|P\d+|L\d+)$/i)?.[1]?.toUpperCase();

  if (!entityId) {
    return null;
  }

  const api = new URL("https://www.wikidata.org/w/api.php");
  api.search = new URLSearchParams({
    action: "wbgetentities",
    format: "json",
    ids: entityId,
    languages: "en",
    origin: "*",
    props: "labels|descriptions",
  }).toString();

  const response = await fetch(api, { signal });

  if (!response.ok) {
    return false;
  }

  const data = (await response.json()) as {
    entities?: Record<
      string,
      {
        descriptions?: { en?: { value: string } };
        labels?: { en?: { value: string } };
        missing?: string;
      }
    >;
  };

  const entity = data.entities?.[entityId];

  if (!entity || "missing" in entity) {
    return null;
  }

  const label = entity.labels?.en?.value;

  return {
    description: entity.descriptions?.en?.value ?? entityId,
    faviconUrl: faviconUrl("www.wikidata.org"),
    source: "wikidata.org",
    title: label ? `${label} (${entityId})` : entityId,
    url: canonicalWikidataUrl(entityId),
  };
}

async function searchWikidata(parsed: ParsedProjectUrl, signal: AbortSignal) {
  const api = new URL("https://www.wikidata.org/w/api.php");
  api.search = new URLSearchParams({
    action: "wbsearchentities",
    format: "json",
    language: "en",
    limit: "5",
    origin: "*",
    search: parsed.title,
  }).toString();

  const response = await fetch(api, { signal });

  if (!response.ok) {
    return [];
  }

  const data = (await response.json()) as {
    search?: Array<{ description?: string; id: string; label?: string }>;
  };

  return (data.search ?? []).map((result) => ({
    description: result.description ?? result.id,
    faviconUrl: faviconUrl("www.wikidata.org"),
    source: "wikidata.org",
    title: result.label ? `${result.label} (${result.id})` : result.id,
    url: canonicalWikidataUrl(result.id),
  }));
}

async function searchAllProjects(query: string, signal: AbortSignal) {
  void wikipediaSearchHosts();
  const hosts = [...FALLBACK_WIKIPEDIA_SEARCH_HOSTS];
  const wikipediaSearches = mapWithConcurrency(hosts, 8, signal, (host) =>
    searchWikipediaHost(host, query, signal).catch(() => []),
  );
  const wikidataSearch = searchWikidata(
    { kind: "wikidata", host: "www.wikidata.org", title: query },
    signal,
  ).catch(() => []);

  const [wikipediaResults, wikidataResults] = await Promise.all([
    wikipediaSearches,
    wikidataSearch,
  ]);

  return filterSuggestionsForQuery(
    uniqueSuggestions([...wikipediaResults.flat(), ...wikidataResults]),
    query,
  ).slice(0, 10);
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

  const parsedUrl = useMemo(() => {
    if (!articleUrl.trim()) {
      return null;
    }

    return parseProjectUrl(articleUrl);
  }, [articleUrl]);

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

    if (!looksLikeUrl(trimmed)) {
      const controller = new AbortController();
      setSuggestions([]);
      setValidation({ status: "checking", message: "" });
      const timeout = window.setTimeout(() => {
        searchAllProjects(trimmed, controller.signal)
          .then((nextSuggestions) => {
            if (controller.signal.aborted) {
              return;
            }

            setSuggestions(nextSuggestions);
            setValidation({
              status: "invalid",
              message:
                nextSuggestions.length > 0
                  ? "Choose a Wikipedia or Wikidata result."
                  : "No Wikipedia or Wikidata results found.",
            });
          })
          .catch((error: unknown) => {
            if ((error as Error).name === "AbortError" || controller.signal.aborted) {
              return;
            }

            setSuggestions([]);
            setValidation({
              status: "invalid",
              message: "No Wikipedia or Wikidata results found.",
            });
          });
      }, 350);

      return () => {
        controller.abort();
        window.clearTimeout(timeout);
      };
    }

    if (!parsedUrl || "error" in parsedUrl) {
      setSuggestions([]);
      setValidation({
        status: "invalid",
        message: validationMessage(parsedUrl ?? { error: "caseA" }),
      });
      return;
    }

    const controller = new AbortController();
    setValidation({ status: "checking", message: "" });
    setSuggestions([]);
    const timeout = window.setTimeout(() => {
      const exactSuggestion =
        parsedUrl.kind === "wikipedia" ? exactWikipediaSuggestion : exactWikidataSuggestion;
      const searcher = parsedUrl.kind === "wikipedia" ? searchWikipedia : searchWikidata;

      exactSuggestion(parsedUrl, controller.signal)
        .then(async (suggestion) => {
          if (controller.signal.aborted) {
            return;
          }

          if (suggestion) {
            setSuggestions([suggestion]);
            setValidation({ status: "valid", message: "" });
            return;
          }

          const nextSuggestions = await searcher(parsedUrl, controller.signal);

          if (controller.signal.aborted) {
            return;
          }

          setSuggestions(nextSuggestions);
          setValidation({
            status: "invalid",
            message: validationMessage({ error: "caseC", kind: parsedUrl.kind }),
          });
        })
        .catch((error: unknown) => {
          if ((error as Error).name === "AbortError" || controller.signal.aborted) {
            return;
          }

          setSuggestions([]);
          setValidation({
            status: "invalid",
            message: validationMessage({ error: "caseC", kind: parsedUrl.kind }),
          });
        });
    }, 300);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [articleUrl, parsedUrl]);

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
          In the age of AI, <strong>WIKIPEDIA</strong> is <u>irreplaceable</u>... yet{" "}
          <u>flawed</u>. <strong>Fix it!</strong>
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
              inputMode="url"
              placeholder="Wikipedia article URL"
              type="url"
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
