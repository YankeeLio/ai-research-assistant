"""引用图谱探针：打印节点排名、角色与库内连边。"""

from __future__ import annotations

import json

import httpx


def main() -> None:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as client:
        resp = client.get("/api/graph")
        resp.raise_for_status()
        data = resp.json()

        print("stats :", json.dumps(data["stats"], ensure_ascii=False))
        print("nodes :", len(data["nodes"]))

        library = [n for n in data["nodes"] if n["in_library"]]
        print("\n库内节点（按 PageRank）:")
        for node in sorted(library, key=lambda n: -n["pagerank"]):
            print(
                f"  {node['role']:12s} pr={node['pagerank']:.4f} "
                f"in={node['degree_in']:2d} out={node['degree_out']:2d}  {node['label'][:52]}"
            )

        internal = [e for e in data["edges"] if e["kind"] == "internal"]
        print(f"\n库内互引 {len(internal)} 条:")
        for edge in internal[:12]:
            print(f"  {edge['source']} -> {edge['target']}")

        resp = client.get("/api/graph/survey")
        resp.raise_for_status()
        survey = resp.json()
        print("\n综述摘要:\n" + survey["summary"])


if __name__ == "__main__":
    main()
