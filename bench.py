"""
Benchmark MCP tool

Start server.py as subprocess, append one JSON line per call to <out>/results.jsonl

Planned 77 calls total:
  grid    12 passages x 3 encodings, run twice in different random orders (72)
  repeat  send one query 5 additional times as small test case to measure how much identical calls vary
"""

import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

import click
from mcp import Client, StdioServerParameters

REPO_DIR = Path(__file__).parent
DATA_DIR = REPO_DIR / "data"
RESULTS_DIR = REPO_DIR / "results"
ENCODINGS = ["nfc", "nfd", "plain"]
GRID_RUNS = 2
REPEATS = 5
SEED = 42


def read_key() -> str:
    """
    Get SearchApi key from .env
    """
    if key := os.environ.get("SEARCHAPI_API_KEY"):
        return key
    env_file = REPO_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "SEARCHAPI_API_KEY" and value.strip():
                return value.strip()
    sys.exit("No SEARCHAPI_API_KEY found")


def plan(passages: list[dict]) -> list[tuple[str, int, dict, str]]:
    """
    Every call formatted as (kind, run, passage, encoding)
    """
    jobs = []
    for run in range(1, GRID_RUNS + 1):
        grid = [("grid", run, p, encoding) for p in passages for encoding in ENCODINGS]
        random.Random(SEED + run - 1).shuffle(grid)
        jobs += grid
        if run == 1:
            jobs += [("repeat", n, passages[0], "nfc") for n in range(1, REPEATS + 1)]
    return jobs


def payload_of(result) -> dict:
    """
    JSON payload from structured content or text block
    """
    if isinstance(result.structured_content, dict):
        return result.structured_content
    return json.loads(result.content[0].text)


async def main(limit: int | None, results_dir: Path) -> None:
    passages = json.loads((DATA_DIR / "passages.json").read_text())
    out = results_dir / "results.jsonl"
    results_dir.mkdir(parents=True, exist_ok=True)

    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            row = json.loads(line)
            done.add((row["kind"], row["run"], row["id"], row["encoding"]))
    todo = [j for j in plan(passages) if (j[0], j[1], j[2]["id"], j[3]) not in done][:limit]
    print(f"{len(done)} calls on file, {len(todo)} to run", flush=True)

    # Limit server reception to only what's required: key, dir to store raw responses, and endpoint override
    env = {"SEARCHAPI_API_KEY": read_key(), "RAW_DIR": str(results_dir / "raw")}
    if url := os.environ.get("SEARCHAPI_URL"):
        env["SEARCHAPI_URL"] = url
    server = StdioServerParameters(command=sys.executable, args=[str(REPO_DIR / "server.py")], env=env)

    # cache=None so no client-side response cache between timer and server
    async with Client(server, cache=None) as client:
        for index, (kind, run, passage, encoding) in enumerate(todo):
            start = time.perf_counter()
            result = await client.call_tool(
                "find_greek_source", {"passage": passage["greek"], "encoding": encoding}
            )
            e2e_s = time.perf_counter() - start

            if result.is_error:
                # stop at first failure to conserve credits
                sys.exit(f"tool error on {passage['id']}/{encoding}: {result.content[0].text}")

            payload = payload_of(result)
            row = {
                "id": passage["id"],
                "encoding": encoding,
                "kind": kind,
                "run": run,
                "call_index": index,
                "e2e_s": round(e2e_s, 4),
                "tool_bytes": len(json.dumps(payload, ensure_ascii=False).encode()),
                **payload,
            }
            with out.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            timing = payload["timing"]
            print(
                f"{kind:6} {run} {passage['id']:22} {encoding:5} "
                f"e2e={e2e_s:.3f}s http={timing['http_s']:.3f}s "
                f"searchapi={timing['searchapi_total_s']}s results={len(payload['results'])}",
                flush=True,
            )


@click.command()
@click.option("--limit", type=int, default=None, help="run at most N new calls")
@click.option("--out", type=click.Path(path_type=Path), default=RESULTS_DIR, help="results directory")
def cli(limit: int | None, out: Path) -> None:
    asyncio.run(main(limit, out))


if __name__ == "__main__":
    cli()
