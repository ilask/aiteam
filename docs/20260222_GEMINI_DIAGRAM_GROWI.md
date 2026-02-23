GEMINI_DIAGRAM_SPEC:
Scope:
- GROWI semantic search using Elasticsearch vector backend and OpenAI embeddings.
- Hybrid retrieval: vector similarity + keyword fallback/fusion.

Nodes:
- N1 User (Browser)
- N2 GROWI Web UI
- N3 GROWI API Server
- N4 AuthZ/ACL Filter
- N5 Semantic Search Service (GROWI plugin/service)
- N6 OpenAI Embeddings API
- N7 Elasticsearch Vector Index (`growi_semantic_pages`)
- N8 Elasticsearch Keyword Index (`growi_pages_text`)
- N9 MongoDB (GROWI pages source)
- N10 Reindex Worker (batch + incremental)
- N11 Gemini Agent
- N12 nanobanana MCP
- N13 Claude Agent
- N14 Codex Agent

Directed Edges:
- E1 N1 -> N2: user submits semantic query
- E2 N2 -> N3: `/search` request (query, user context)
- E3 N3 -> N4: resolve ACL/readable scope
- E4 N4 -> N3: return allowed page filters
- E5 N3 -> N5: semantic query execution request
- E6 N5 -> N6: generate embedding for query text
- E7 N6 -> N5: return query vector
- E8 N5 -> N7: vector kNN search with ACL filter
- E9 N5 -> N8: keyword BM25 search
- E10 N7 -> N5: vector hits (page_id, score_v)
- E11 N8 -> N5: keyword hits (page_id, score_k)
- E12 N5 -> N3: hybrid fused ranking
- E13 N3 -> N9: hydrate title/snippet/path
- E14 N9 -> N3: return page metadata/content
- E15 N3 -> N2: final ranked response
- E16 N2 -> N1: render results
- E17 N9 -> N10: page create/update/delete event
- E18 N10 -> N5: indexing job with changed chunks
- E19 N5 -> N6: generate embeddings for chunks
- E20 N6 -> N5: return chunk vectors
- E21 N5 -> N7: upsert/delete vector docs + metadata
- E22 N5 -> N8: upsert/delete keyword docs

Request Sequence:
1. Indexing/update path
1.1 N9 emits page change events to N10.
1.2 N10 sends changed page chunks to N5.
1.3 N5 requests chunk embeddings from N6.
1.4 N5 writes vector docs to N7 and keyword docs to N8.
2. Search/query path
2.1 N1 sends query from N2 to N3.
2.2 N3 resolves ACL via N4 and forwards query+filter to N5.
2.3 N5 gets query embedding from N6.
2.4 N5 executes vector search on N7 and keyword search on N8.
2.5 N5 fuses scores and returns ranked page IDs to N3.
2.6 N3 hydrates page metadata from N9 and returns response to N2.
2.7 N2 renders ranked semantic results to N1.

Ownership Constraint (Mandatory):
- nanobanana MCP ownership is gemini only.
- Allowed: N11 (Gemini Agent) -> N12 (nanobanana MCP).
- Disallowed: N13 (Claude Agent) -> N12.
- Disallowed: N14 (Codex Agent) -> N12.
- Canonical owner flag: `NANOBANANA_OWNER=gemini`.
