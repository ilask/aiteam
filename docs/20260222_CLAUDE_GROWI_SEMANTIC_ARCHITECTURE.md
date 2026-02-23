# GROWI Semantic Search Architecture Overview (Claude)

## Scope
Enable ACL-safe semantic + hybrid search in GROWI with Elasticsearch as vector backend and OpenAI embeddings, while keeping existing keyword search as fallback.

## Core Components
- `PageEventProducer` (create/update/delete/publish/unpublish hooks in app server)
- `SemanticIndexWorker` (queue consumer for chunking, embedding, upsert/delete)
- `OpenAIEmbeddingClient` (`text-embedding-3-small` default; model/version configurable)
- `ElasticsearchVectorStore` (`growi_semantic_pages` index, `dense_vector` + metadata)
- `HybridSearchService` (vector kNN + BM25 fusion)
- `AclFilterBuilder` (user/group scope filter applied at query time)

## Ingestion Flow
1. Page revision event is emitted with `pageId`, `revisionId`, operation type, and visibility metadata.
2. Worker loads latest readable content, strips unsupported markup, and chunks text (target 400-800 tokens, 80 token overlap).
3. Worker computes deterministic `chunkId` (`pageId:revisionId:chunkNo`) for idempotent upsert.
4. Worker batches embedding calls to OpenAI with retry/backoff and timeout guard.
5. Worker upserts chunks to Elasticsearch with fields like:
   - `pageId`, `revisionId`, `path`, `title`, `chunkText`, `acl`, `updatedAt`
   - `embedding` (`dense_vector`, cosine similarity)
   - `embeddingModel`, `embeddingVersion`
6. Delete/unpublish emits tombstone job that removes all chunks by `pageId`.
7. Failures are retried; exhausted jobs go to DLQ for operator replay.

## Query Flow
1. User submits query; server resolves ACL scope first.
2. Query text is embedded via OpenAI (short timeout, low retry count).
3. Execute Elasticsearch kNN on vector index with ACL filter.
4. Execute BM25 keyword search on existing text index in parallel.
5. Fuse scores (RRF or weighted sum), deduplicate by `pageId`, rerank top N.
6. Hydrate snippets/highlights from MongoDB or cached page metadata.
7. Return result set with debug metadata (`vectorScore`, `keywordScore`, `finalScore`).
8. If embedding/query path fails, automatically fall back to keyword-only search.

## Reliability & Operability
- Idempotency: chunk ID and revision-aware upsert prevent duplicate writes.
- Consistency: queue-driven async indexing + periodic reconciliation job (detect index drift).
- Backpressure: bounded worker concurrency and OpenAI rate-limit handling.
- Resilience: circuit breaker for embedding API; graceful degradation to lexical search.
- Security: ACL filter is mandatory in both kNN and BM25 paths (no post-filter-only design).
- Observability: metrics for embed latency/error rate, indexing lag, recall@k, fallback rate.
- Governance: store model/version per chunk to support safe re-embedding migrations.

## Rollout Stages
1. `Stage 0 - Dark Launch`
   - Build index mappings, worker, and admin controls behind feature flags.
2. `Stage 1 - Backfill + Shadow Read`
   - Backfill all pages; run semantic retrieval in shadow mode and log offline relevance.
3. `Stage 2 - Canary`
   - Enable for internal/admin users or selected spaces; monitor latency, error budget, quality.
4. `Stage 3 - General Availability`
   - Enable hybrid search by default; keep keyword fallback and rollback toggle.
5. `Stage 4 - Continuous Improvement`
   - Tune chunking/ranking, run A/B tests, execute controlled model upgrade re-index.
