"""
MCP server with  tool to retrieve source of polytonic Greek text

This script sends an input passage to Google via SearchApi and returns the top organic results, trimmed to what a model needs to name the author and work. The script also returns timings to later report latency
"""

import os
import time
import unicodedata
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer

# overridable so test_replay.py can point the server at recorded responses
API_URL = os.environ.get("SEARCHAPI_URL", "https://www.searchapi.io/api/v1/search")

mcp = MCPServer("greek-source-finder")

# one HTTP client to share connection across calls
_http: httpx.AsyncClient | None = None


def to_encoding(text: str, encoding: str) -> str:
    """
    Return `text` in one of three Unicode encodings

    nfc    precomposed: one code point per accented letter
    nfd    decomposed: base letter plus combining marks
    plain  all accents and breathings removed
    """
    if encoding == "nfc":
        return unicodedata.normalize("NFC", text)
    decomposed = unicodedata.normalize("NFD", text)
    if encoding == "nfd":
        return decomposed
    if encoding == "plain":
        kept = "".join(c for c in decomposed if not unicodedata.combining(c))
        return unicodedata.normalize("NFC", kept)
    raise ValueError(f"unknown encoding: {encoding}")


def search_params(query: str) -> dict[str, str]:
    """
    SearchApi request for one query: Google, US results, English interface
    """
    return {"engine": "google", "q": query, "gl": "us", "hl": "en"}


@mcp.tool()
async def find_greek_source(
    passage: str, encoding: Literal["nfc", "nfd", "plain"] = "nfc"
) -> dict[str, Any]:
    """
    Search Google for polytonic Greek text, return top results
    """
    global _http
    if _http is None:
        # key never appears URL or log
        key = os.environ["SEARCHAPI_API_KEY"]
        _http = httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {key}"})

    query = to_encoding(passage, encoding)
    start = time.perf_counter()
    response = await _http.get(API_URL, params=search_params(query))
    http_s = time.perf_counter() - start
    response.raise_for_status()
    data = response.json()
    meta = data.get("search_metadata", {})
    info = data.get("search_information", {})
    search_id = meta.get("id", "unknown")

    # optional: keep full SearchApi response on disk for audit
    if raw_dir := os.environ.get("RAW_DIR"):
        Path(raw_dir).mkdir(parents=True, exist_ok=True)
        Path(raw_dir, f"{search_id}.json").write_bytes(response.content)

    return {
        "query": query,
        "query_codepoints": len(query),
        "echoed_codepoints": len(data.get("search_parameters", {}).get("q", "")),
        "query_displayed": info.get("query_displayed"),
        "total_results": info.get("total_results"),
        "results": [
            {
                "position": r.get("position"),
                "title": r.get("title"),
                # record stable domain since links will be Google redirect URLs that change across sessions
                "domain": r.get("domain"),
                "link": r.get("link"),
                "snippet": r.get("snippet"),
            }
            for r in data.get("organic_results", [])
        ],
        "timing": {
            "http_s": round(http_s, 4),
            "searchapi_total_s": meta.get("total_time_taken"),
            "searchapi_request_s": meta.get("request_time_taken"),
            "searchapi_parsing_s": meta.get("parsing_time_taken"),
        },
        "search_id": search_id,
        "raw_bytes": len(response.content),
    }


if __name__ == "__main__":
    mcp.run()
