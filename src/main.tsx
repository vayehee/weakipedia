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

async function validateWikipediaUrl(parsed: ParsedProjectUrl, signal: AbortSignal) {
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
      pages?: Record<string, { missing?: string; ns?: number }>;
    };
  };

  const page = Object.values(data.query?.pages ?? {})[0];

  return Boolean(page && !("missing" in page) && (page.ns === 0 || page.ns === 2));
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
    description: result.snippet?.replace(/<[^>]*>/g, "") ?? "",
    title: result.title,
    url: canonicalWikipediaUrl(parsed.host, result.title),
  }));
}

async function validateWikidataUrl(parsed: ParsedProjectUrl, signal: AbortSignal) {
  const entityId = parsed.title.match(/^(Q\d+|P\d+|L\d+)$/i)?.[1]?.toUpperCase();

  if (!entityId) {
    return false;
  }

  const api = new URL("https://www.wikidata.org/w/api.php");
  api.search = new URLSearchParams({
    action: "wbgetentities",
    format: "json",
    ids: entityId,
    origin: "*",
    props: "",
  }).toString();

  const response = await fetch(api, { signal });

  if (!response.ok) {
    return false;
  }

  const data = (await response.json()) as {
    entities?: Record<string, { missing?: string }>;
  };

  return Boolean(data.entities?.[entityId] && !("missing" in data.entities[entityId]));
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
    title: result.label ? `${result.label} (${result.id})` : result.id,
    url: canonicalWikidataUrl(result.id),
  }));
}

function App() {
  const user = mockTelegramUser;
  const [articleUrl, setArticleUrl] = useState("");
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
    if (!articleUrl.trim()) {
      setSuggestions([]);
      setValidation({ status: "idle", message: "" });
      return;
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
    const timeout = window.setTimeout(() => {
      setValidation({ status: "checking", message: "" });
      setSuggestions([]);

      const validator =
        parsedUrl.kind === "wikipedia" ? validateWikipediaUrl : validateWikidataUrl;
      const searcher = parsedUrl.kind === "wikipedia" ? searchWikipedia : searchWikidata;

      validator(parsedUrl, controller.signal)
        .then(async (isValid) => {
          if (isValid) {
            setSuggestions([]);
            setValidation({ status: "valid", message: "" });
            return;
          }

          const nextSuggestions = await searcher(parsedUrl, controller.signal);
          setSuggestions(nextSuggestions);
          setValidation({
            status: "invalid",
            message: validationMessage({ error: "caseC", kind: parsedUrl.kind }),
          });
        })
        .catch((error: unknown) => {
          if ((error as Error).name === "AbortError") {
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
                    setArticleUrl(suggestion.url);
                  }}
                >
                  <span className="suggestion-title">{suggestion.title}</span>
                  <span className="suggestion-description">{suggestion.description}</span>
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
            {validation.status === "checking" ? "Checking URL..." : validation.message}
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
