# Weakipedia API Modules

These backend modules define the external or derived data streams used to build static and dynamic dashboards.

| module | official name | api | endpoint | handles | destination db table |
|---|---|---|---|---|---|
| `w_article_metadata.py` | MediaWiki Action API | Wikipedia Action API | `/w/api.php?action=query&titles={title}&prop=info%7Cpageprops&redirects=1&format=json` | Canonical title, page ID, namespace, redirects, Wikidata QID | `api_queries`, `w_articles`, `targets` |
| `w_article_parse.py` | MediaWiki Action API | Wikipedia Action API | `/w/api.php?action=parse&page={title}&prop=text%7Csections%7Ccategories%7Clinks%7Cexternallinks%7Ctemplates%7Cimages%7Crevid%7Cdisplaytitle&formatversion=2&format=json` | Article HTML/text, sections, categories, links, external links, templates, images, latest revision ID | `api_queries`, `w_articles`, `w_article_sections`, `w_article_links`, `target_sources` |
| `w_article_revisions.py` | MediaWiki Action API | Wikipedia Action API | `/w/api.php?action=query&prop=revisions&titles={title}&rvprop=ids%7Ctimestamp%7Cuser%7Cuserid%7Ccomment%7Csize%7Cflags&rvlimit=500&format=json&formatversion=2` | Last 500 revisions, editor names/IDs, timestamps, comments, size, minor flags | `api_queries`, `w_article_revisions`, `w_editors` |
| `w_article_authorship.py` | WikiWho | WikiWho API | Provider endpoint by language/article/revision | Token or phrase-level authorship attribution: original editor, introduced revision, timestamp, and surviving text spans | `api_queries`, `w_article_text_authorship`, `w_article_revisions`, `w_editors` |
| `w_article_pageviews.py` | Wikimedia REST API Pageviews | Wikimedia Pageviews API | `/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia.org/desktop/user/{title}/daily/{start}/{end}` | Desktop human/user pageviews | `api_queries`, `w_article_views` |
| `w_article_pageviews.py` | Wikimedia REST API Pageviews | Wikimedia Pageviews API | `/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia.org/mobile-web/user/{title}/daily/{start}/{end}` | Mobile web human/user pageviews | `api_queries`, `w_article_views` |
| `w_article_pageviews.py` | Wikimedia REST API Pageviews | Wikimedia Pageviews API | `/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia.org/mobile-app/user/{title}/daily/{start}/{end}` | Mobile app human/user pageviews | `api_queries`, `w_article_views` |
| `w_article_pageviews.py` | Wikimedia REST API Pageviews | Wikimedia Pageviews API | `/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia.org/all-access/spider/{title}/daily/{start}/{end}` | Spider/crawler pageviews | `api_queries`, `w_article_views` |
| `w_article_pageviews.py` | Wikimedia REST API Pageviews | Wikimedia Pageviews API | `/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia.org/all-access/automated/{title}/daily/{start}/{end}` | Automated/non-human pageviews | `api_queries`, `w_article_views` |
| `w_article_traffic.py` | Wikinav | Wikinav API | `/api/v1/{lang}/{title}/sources/latest?start=1&limit=500&sort=desc` | Incoming article traffic | `api_queries`, `w_article_traffic` |
| `w_article_traffic.py` | Wikinav | Wikinav API | `/api/v1/{lang}/{title}/destinations/latest?start=1&limit=500&sort=desc` | Outgoing article traffic | `api_queries`, `w_article_traffic` |
| `w_article_editors.py` | Weakipedia derived revisions analysis | Derived from Wikipedia revisions | Internal parser over `w_article_revisions.py` output | Aggregated editor activity | `w_article_editors`, `w_editors` |
| `w_article_claims.py` | Weakipedia claims analysis | Weakipedia analysis / LLM | Internal analysis over parsed article text | Objective claim/argument extraction | `w_article_args` |
| `w_article_sources.py` | Weakipedia source extraction | Wikipedia parse + source fetcher | Internal extraction over parse result and external source URLs | Citation/source extraction, source canonicalization, source text fetching | `target_sources`, `w_article_claims_sources` |
| `wdata_item.py` | Wikibase API | Wikidata API | `/w/api.php?action=wbgetentities&ids={qid}&props=labels%7Cdescriptions%7Csitelinks%7Cclaims&format=json` | Wikidata labels, descriptions, sitelinks, claims | `api_queries`, `wdata_items` |
| `wdata_item.py` | Wikibase API | Wikidata API | `/w/api.php?action=wbsearchentities&search={query}&language={lang}&format=json` | Wikidata item search by label/query | `api_queries`, `wdata_items` |
| `g_trends.py` | Google Trends | Google Trends provider/API | Provider-dependent | Trend interest over time/region | `api_queries`, `g_trends` |
| `g_news.py` | Google News | Google News provider/API | Provider-dependent | News articles mentioning the target | `api_queries`, `g_news` |
