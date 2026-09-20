# BillWise — frontend-v2

Check a hospital bill against India's published (NPPA) price ceilings.

```bash
cp .env.example .env   # VITE_API_BASE, VITE_USE_MOCKS
npm install
npm run dev
npm test               # money formatter
```

- `VITE_USE_MOCKS=true` runs the whole app with no backend. Add `?mock=processing|needs_review|ready|failed` to the URL to force a bill state.
- All API calls and response types live in `src/lib/api.ts`. Field-name changes go there and nowhere else.
- Money is a decimal string end to end; `src/lib/money.ts` formats it, never parses it.
