# GREETING-LANGUAGE-001 Walkthrough

Greeting questions are classified as `GENERAL_CHAT` with `sub_intent=greeting`.
`GenerateChatResponseNode` bypasses the LLM for this sub-intent and returns the text from
`backend/app/resources/greetings.md`.

The greeting resource now returns Turkish copy:

`Merhaba! Ben Med Agent. Randevu verileriyle ilgili sorularınızda size yardımcı olabilirim.`

If the resource file cannot be read, the node now uses the same Turkish fallback instead of English.
