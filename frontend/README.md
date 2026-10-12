# frontend

The React + TypeScript UI: a chat view (CR-001 R12.11), a live run view with React Flow (R6.1), and the approval and answer screens (R6.2, R6.3).

**Empty until phase 11.** The stack is fixed by R6.5: React 18, TypeScript `strict`, Vite, React Flow, TanStack Query, Tailwind, Vitest + Testing Library, and an API client generated from the backend's OpenAPI schema. It will be served by an unprivileged nginx container built from `frontend/Dockerfile`.
