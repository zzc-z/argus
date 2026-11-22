<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph, reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

Check that the index is actually initialized — a bare `.codegraph/` directory is not enough:

```bash
codegraph status   # "Not initialized" → index is absent, fall back to grep
```

Indexing is the user's decision — never run `codegraph init` yourself. When the index is missing, use your usual tools instead.
<!-- CODEGRAPH_END -->
