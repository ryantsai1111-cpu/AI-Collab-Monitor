# GitHub and official Dot integration research

Research date: 2026-10-05 UTC. Scope: public documentation and static public source inspection only. **Native Dot connection remains BLOCKED; no runtime acceptance was performed or earned.** The existing final acceptance report remains authoritative.

## Findings

| Route | Documentation result | Existing ChatGPT/Dot continuity | Minimum prerequisites |
|---|---|---|---|
| OpenAI Responses API with official Python SDK | SUPPORTED for a separately created API conversation | No documented access to an existing ChatGPT or Dot conversation | Authorized API project, API credential, applicable billing/model access, adapter implementation and explicit runtime validation |
| Sign in with ChatGPT plan usage for OSS/local apps | SUPPORTED in current preview documentation; local eligibility and successful authorization UNKNOWN here | Explicitly excludes access to ChatGPT conversations and other account context | Eligible OSS/local app and account/workspace, separate interactive OAuth authorization, stable host ID, validated identity/permissions, protected token storage, preview-compatible requests |
| ChatKit JS/Python | SUPPORTED chat UI/custom backend framework | No inspected documentation establishes existing Dot identity/history continuation | Web-capable frontend integration, custom agent backend, session/storage handling, backend credentials or eligible OAuth, desktop compatibility testing |
| Plugins/previous Apps SDK route | SUPPORTED direction is extending ChatGPT/Codex with tools, skills and optional UI | Does not establish a desktop application API for sending to/resuming the user's Dot | Plugin/MCP implementation, connection authorization and supported host |
| Native Dot channel access | Officially documented ChatGPT, Slack and Teams channels | Product says Dot context carries across these channels; desktop app embedding UNKNOWN | A separately verified officially supported bridge, authorized channel and exact identity/thread mapping |
| Local Ollama/llama.cpp adapter | Documented local model transport pattern; not implemented or exercised | No Dot/ChatGPT continuity | Explicitly selected local backend, licensed pre-existing model/runtime, loopback-only server and own session history |

### Public API conversation is a separate object

The [official Python SDK](https://github.com/openai/openai-python) exposes Responses API calls and streaming. The [conversation-state guide](https://developers.openai.com/api/docs/guides/conversation-state) documents durable Conversations API IDs and subsequent Responses calls using those IDs. These are API-created conversation objects; the inspected sources do not provide a mapping from a ChatGPT/Dot conversation ID. Importing user-selected text would be a context handoff, not native resume. Ordinary [API platform billing](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform) is managed separately from ChatGPT billing.

### Current official OAuth path changes the credential prerequisite

The [OSS/local ChatGPT plan usage overview](https://developers.openai.com/siwc/token-sharing-open-source) explicitly allows eligible Responses requests using the user's plan, while explicitly excluding conversations/account context. Therefore “every third-party OpenAI integration requires a new API key” would be inaccurate. Separate app authorization remains required; existing Codex login or copied browser credentials are not evidence of that authorization.

[Registration documentation](https://developers.openai.com/siwc/token-sharing-open-source/sign-in) describes dynamic registration, a persistent opaque host identifier, issued client ID, and OAuth identity/permission validation. No client secret or partner API key is needed for that documented direct OSS flow. [Account/session guidance](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions) requires protected token storage and account-specific registration separation. No tokens, credentials, configuration or login artifacts were read or created in this research.

[Inference documentation](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference) specifies the public Responses endpoint and account-specific model choices; it explicitly excludes ChatGPT backend-api endpoints. [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) require streaming with storage disabled, request-supplied history, and omit conversation/previous-response IDs over HTTP. Persistent Conversations API state must therefore not be assumed for this OAuth route. Local SQLite history can supply context but does not become ChatGPT/Dot history.

The [commercial client-ID page](https://developers.openai.com/siwc/request-client-id) describes select partners/waitlist, while the OSS pages describe dynamic registration. Read these as different integration audiences; availability for this exact app/account is unverified. The [app-server guide](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) is another documented transport for OAuth-backed Responses inference. It would still be a separate inference integration and does not prove native Dot connection. No provider/model setting was changed.

### ChatKit and plugin direction

[ChatKit JS](https://github.com/openai/chatkit-js) supplies web/React chat components, and [ChatKit Python](https://github.com/openai/chatkit-python) supports a custom server. A Qt WebEngine container is a possible engineering design, not a compatibility claim established by these sources. A native PySide pane can also use the official API SDK directly; neither UI choice supplies existing Dot identity/history.

The [current ChatKit guide](https://developers.openai.com/api/docs/guides/chatkit) favors custom server integration for new work and documents Agent Builder's November 30, 2026 shutdown. Do not base a new adapter on a hosted workflow assumed to be generally available. ChatKit UI assets and local model inference have separate network dependencies; a local backend alone does not prove an offline frontend.

The former [Apps SDK URL now redirects to Plugins](https://developers.openai.com/plugins), whose documented direction is extending ChatGPT/Codex. That cannot be promoted into an inverse API embedding ChatGPT inside this desktop program. [Agents SDK](https://github.com/openai/openai-agents-python) supports provider-independent orchestration and its own sessions; these sessions are also distinct from an existing Dot.

### Native Dot evidence boundary

The September 29, 2026 [official Dot announcement](https://openai.com/index/introducing-dots/) documents access through ChatGPT, Slack and Teams, cross-channel context, and optional laptop access. It does not specify an embeddable public Dot message/history/interrupt API. No official bridge was established in the inspected sources. This is a bounded “not found/documented here” result, not proof that no enterprise/private integration could ever exist. Slack/Teams availability alone does not prove access through their public app APIs.

## Static third-party offline patterns

Only upstream primary sources were inspected, not random ChatGPT wrappers.

- [Ollama Python client source](https://github.com/ollama/ollama-python/blob/main/ollama/_client.py): chat posts messages to /api/chat; streaming checks HTTP status, parses JSON lines, reports structured errors and yields response objects. Useful pattern: isolated asynchronous transport, explicit history input, delta/error normalization, bounded cancellation and own session mapping. Inspection does not establish actual cancellation semantics or offline operation for every Ollama configuration.
- [Ollama API specification](https://github.com/ollama/ollama/blob/main/docs/api.md): documents chat/model operations and JSON streaming. A genuine offline adapter needs an already available local model and no cloud/pull fallback; those conditions were not inspected locally.
- [llama.cpp server specification](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md): documents default loopback serving, Chat Completions compatibility, and a Responses compatibility layer implemented via conversion. Useful pattern: explicit loopback provider with capability negotiation. Protocol similarity does not imply full Responses semantics, OpenAI model identity, Dot memory or native approvals.

These repositories are source candidates, not a security certification. Mutable main/master references were inspected without commit pinning, dependency audit, package execution, installation, downloads of models, backend calls or local runtime probes. No third-party backend was selected.

## Next decision and acceptance conditions

For the original mandatory Dot requirement, the minimum missing prerequisite is an official supported bridge specifying how this exact Dot's identity and conversation are authorized, addressed, streamed, resumed and interrupted. Until that is supplied and validated, keep its native connection disabled/BLOCKED.

A separate public API or local model pane would require an explicit scope decision because it changes the backend identity and continuity semantics. If authorized later, implement and verify it independently; label it accurately. Runtime acceptance needs an actual authorized response, exact identity/session mapping, interruption/resume behavior and evidence captured through the real UI. This report changes no acceptance counts and cannot certify three-real-agent operation.
