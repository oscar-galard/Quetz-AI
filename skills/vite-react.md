---
skill: vite-react
layer: infrastructure
tags: [typescript, react, vite, tailwind, frontend, shadcn, npm, scaffold]
---

## Scaffold Vite + React + TypeScript

**Setup commands (run in order):**
```bash
npx create-vite@latest frontend --template react-ts
cd frontend && npm install
npm install tailwindcss @tailwindcss/vite
```

## Configure Tailwind in vite.config.ts

```typescript
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    tailwindcss(),
  ],
})
```

## Add Tailwind import to CSS

In `src/index.css` (or `src/App.css`), add at the TOP:
```css
@import "tailwindcss";
```

## Project structure after scaffold

```
frontend/
├── src/
│   ├── App.tsx
│   ├── index.css          # add @import "tailwindcss"; here
│   ├── main.tsx
│   └── ...
├── vite.config.ts         # add tailwindcss plugin here
├── tsconfig.json
├── package.json
└── index.html
```

## Common commands

```bash
cd frontend && npm run dev      # start dev server
cd frontend && npm run build    # production build
cd frontend && npm run lint     # run ESLint
```

## shadcn/ui (optional, add later)

```bash
cd frontend && npx shadcn@latest init
```

## Rules

- Keep components in `src/components/`
- Use function components with typed props
- Import Tailwind classes directly: `className="bg-blue-500 text-white p-4"`
- Use `cn()` from `@/lib/utils` for class merging (if using shadcn)
