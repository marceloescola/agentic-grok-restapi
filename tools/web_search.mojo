from __future__ import annotations

from tools.base import ToolDef


class WebSearchTool:
    @property
    def definition(self) -> ToolDef:
        return ToolDef(
            name="web_search",
            description="Search the web for current, up-to-date information. Returns top results with titles, snippets, and URLs.",
            parameters={"query": "the search query"},
        )

    async def run(self, query: str = "") -> str:
        if not query.strip():
            return "Error: empty search query"
        try:
            from duckduckgo_search import DDGS

            results = list(DDGS().text(query, max_results=5))
            if not results:
                return "No results found."

            lines = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                body = r.get("body", "")
                href = r.get("href", "")
                lines.append(f"{i}. {title}\n   {body}\n   URL: {href}")
            return "\n\n".join(lines)
        except ImportError:
            return "Error: duckduckgo-search library not installed. Run: pip install duckduckgo-search"
        except Exception as exc:
            return f"Search error: {exc}"
