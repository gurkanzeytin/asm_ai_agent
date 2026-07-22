# FRONTEND-ANIMATED-TEXT-001 Walkthrough

## User Flow

When the assistant answer is inserted into the chat, the response text now reveals character by character. The rendered content still goes through the existing Markdown renderer, so lists, code blocks, links, and tables remain supported.

The chat header no longer shows the sun/moon theme toggle. The settings dialog no longer exposes the theme dropdown, leaving the existing language, temperature, display name, and logout controls.

## Files

- `frontend/src/components/ui/animated-text.tsx`
- `frontend/src/components/asm/ChatMessage.tsx`
- `frontend/src/components/asm/ChatHeader.tsx`
- `frontend/src/components/asm/SettingsDialog.tsx`
