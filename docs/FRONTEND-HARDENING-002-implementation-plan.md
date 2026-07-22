# FRONTEND-HARDENING-002 Implementation Plan

## Goal

Harden the desktop frontend without adding mobile-specific behavior or authentication.

## Scope

- Keep conversations in memory and never persist report or SQL data in browser storage.
- Use each conversation ID as the backend reporting `session_id`.
- Make abort, clear, delete, success, and failure transitions deterministic.
- Remove controls and diagnostics that are not backed by real behavior or backend data.
- Improve keyboard and assistive-technology support for desktop conversation controls.
- Validate consumed report responses at runtime.
- Bound response animation time and animate only the latest response.
- Lazy-load SQL table and chart functionality.
- Add frontend tests and restore a usable cross-platform lint command.
- Remove the vulnerable XLSX export dependency while preserving CSV, JSON, and SQL export.

## Out Of Scope

- Mobile responsive work.
- Login, authentication, authorization, and route protection.
- Backend API changes.

## Verification

- `npm.cmd test`
- `npx.cmd tsc --noEmit`
- `npm.cmd run lint`
- `npm.cmd run build`
- `npm.cmd audit --omit=dev`
