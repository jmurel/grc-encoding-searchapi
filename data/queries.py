"""
Write queries.json file of 36 distinct searches sent via SearchApi

Each entry holds the request parameters and a ready-made URL. NFC and NFD queries look identical on screen, so the URL's percent-encoding differetiates by shwoing the exact bytes sent

"""

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

DATA_DIR = Path(__file__).parent
REPO_DIR = DATA_DIR.parent
# bench.py and server.py in repo root
sys.path.insert(0, str(REPO_DIR))

from bench import ENCODINGS
from server import API_URL, search_params, to_encoding

queries = []
for passage in json.loads((DATA_DIR / "passages.json").read_text()):
    for encoding in ENCODINGS:
        params = search_params(to_encoding(passage["greek"], encoding))
        queries.append(
            {
                "id": passage["id"],
                "source": passage["source"],
                "encoding": encoding,
                "code_points": len(params["q"]),
                "params": params,
                "url": f"{API_URL}?{urlencode(params)}",
            }
        )

document = {
    "endpoint": API_URL,
    "auth_header": "Authorization: Bearer <SEARCHAPI_API_KEY>",
    "queries": queries,
}
(DATA_DIR / "queries.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
print(f"wrote {len(queries)} queries to queries.json")
