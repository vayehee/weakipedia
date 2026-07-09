from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from wikimedia_search.apis.w_article_revisions import ArticleRevisionsPayload


@dataclass(frozen=True)
class ArticleEditorSummary:
    editor_name: str
    edit_count: int


@dataclass(frozen=True)
class ArticleEditorsPayload:
    revision_count: int
    distinct_editor_count: int
    editors: list[ArticleEditorSummary]


def summarize_article_editors(revisions_payload: ArticleRevisionsPayload) -> ArticleEditorsPayload:
    editor_counts = Counter(
        revision["user"] for revision in revisions_payload.revisions if revision.get("user")
    )

    return ArticleEditorsPayload(
        revision_count=len(revisions_payload.revisions),
        distinct_editor_count=len(editor_counts),
        editors=[
            ArticleEditorSummary(editor_name=editor_name, edit_count=edit_count)
            for editor_name, edit_count in editor_counts.most_common()
        ],
    )
