# Pure metadata parser and injected one-call contract

No HTTP implementation, authentication, search, persistence or retry. This parser is imported by `next_phase/metadata` using its exact SHA256. `parse_metadata` requires unique-key finite UTF-8 JSON, exact integer business code, object data and the requested BVID returned by the response. It projects only bvid/title/aid/duration/pubdate. Missing versus invalid fields remain distinct; partial valid data is preserved. Wrong-target data is withheld. Raw messages/errors/headers are not projected; allowlisting is not universal DLP for title text.

`MetadataAdapter.read` invokes a trusted injected transport at most once, only for a valid BVID. Exact HTTP200 is required before parsing, but HTTP200 alone is not success. `parsed` means selected projection fields are valid, not a completed live action. Supplied/synthetic provenance remains unverified and never authenticates a session.

Schema facts derive from the pinned community MIT implementation [BiliStalkerMCP user_service.py](https://github.com/222wcnm/BiliStalkerMCP/blob/952fd83b9089b3f1b5bfde730b968fe63e3eb6df/bili_stalker_mcp/services/user_service.py#L530-L570), not official or live API documentation. No implementation or third-party test fixtures were vendored. See `SOURCES.json` and `LICENSE`. Bounds (512 KiB body, 500 title characters, signed-64-bit integers) are local defensive choices, not claimed platform limits.

Run from this directory: `python -B -m unittest discover -s tests -v`.
All 26 methods use synthetic inputs. Real endpoint/current schema and authorization are not established.
