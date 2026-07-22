# Stream Response Delivery — Walkthrough

## Live trace

Session `codex-stream-live-trace-20260722` returned HTTP 200 for both turns. Turn 2 emitted thirteen progress events followed by exactly one `complete` event. The event contained:

- outcome `NO_RESULT_GUIDANCE`;
- a successful zero-row `query_result`;
- title `Sonuç Bulunamadı`;
- non-empty Turkish Markdown including `belirtilen kriterlere uygun kayıt bulunamadı`;
- valid analytics, insights, observations, and visualization metadata.

The stream then reached EOF normally. Repeating the request through the running frontend proxy on port 8080 produced the same sequence and payload.

## Boundary results

`ReportingService`, `WorkflowResult`, `_map_to_response`, the streaming endpoint, `stream_workflow`, and NDJSON serialization all retained the controlled empty-result response. `generateReportStream` accepted the payload. `useChatController.send` replaced the empty streaming placeholder with the report Markdown, set `streaming` to false, and treated the controlled report as successful. `ChatMessage` rendered the text even when query rows and optional analytical fields were absent.

No exception, rejected promise, early return, malformed event, queue race, or hiding condition was reproduced. The observed blank response is therefore outside the current live code path and is classified as a stale or different client instance.

## Resolution

No production behavior was changed. The running application already delivers and renders the result correctly. Regression tests now lock down all traced boundaries so a future delivery regression fails deterministically.

