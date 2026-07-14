# AVATAR-001 Implementation Plan

## Goal

Use the existing ASM AI Agent logo as the assistant avatar for AI-generated chat responses and loading states.

## Findings

- `frontend/src/components/asm/ChatMessage.tsx` renders assistant messages and SQL/query result cards.
- The old assistant identity icon was `Sparkles` from `lucide-react`.
- The project already has a reusable `MedAgentLogo` component used in the sidebar, header, login, empty state, and splash screen.

## Plan

- Reuse `MedAgentLogo` directly in `ChatMessage.tsx`.
- Replace only the assistant avatar and typing-state icon.
- Preserve user-message icon, SQL result card rendering, markdown rendering, message props, API contracts, animations, and layout.
- Remove the now-unused `Sparkles` import.
- Validate TypeScript, targeted lint, and production build.
