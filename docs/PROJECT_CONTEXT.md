# Project context

TechSearch targets a local CPU laptop demonstration for English web-development information retrieval. Search results are actual source parents with evidence and attribution. The same production ranking code drives Search, Lab, CLI, and offline benchmarks.

The workspace began with two collectors and two legacy root exports. Those root JSON files were inspected for shape without changing them. The newer collector schemas support structured evidence that cannot be inferred when the older exports flattened it. A fresh, explicit acquisition is the route to recovering that source structure.

There was no existing master architecture file in the workspace at inspection. [The architecture](MASTER_ARCHITECTURE.md) records the supplied specification and the subsequent file-storage design.
