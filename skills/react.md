---
skill: react
layer: interface
tags: [typescript, react, frontend, component, hook]
---

## Component conventions

```tsx
import type { ButtonProps } from "./button.types";

export function Button({ variant = "primary", children, ...rest }: ButtonProps) {
  return (
    <button className={cn(base, variants[variant])} {...rest}>
      {children}
    </button>
  );
}
```

Rules:
- Use function components with typed `Props`. Default-export only for routes/pages.
- Co-locate types in `component.types.ts` when they grow beyond three lines.
- Destructure props; spread `...rest` for HTML pass-through.
- Use `cn()` from `lib/utils` for Tailwind class merging.

## Hook rules

```tsx
export function useSubscribeNewsletter() {
  return useMutation({
    mutationFn: subscribe,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["newsletter"] }),
  });
}
```

Rules:
- Name every hook `useX` with a capital X.
- Hooks must always be called unconditionally at the top level.
- Data-fetching hooks wrap `useQuery`/`useMutation`; never call `fetch` from components.
- Return a stable API object, not a tuple.

## Error & loading state

- Every async component handles three states: loading, error, success.
- Use `react-error-boundary` for render errors.
- Show skeletons for loading, inline toasts for transient errors.

## shadcn/ui rules

- **ONLY use `@/components/ui/*` if `src/components/ui/` folder appears in the project tree.** If not present, use plain HTML elements with Tailwind classes (`<button className="bg-orange-500 ...">`).
- **NEVER use the `@/` import alias unless tsconfig shows `paths` configured.** Use relative imports instead (`./theme`, `../components/...`).
- If shadcn IS installed: import components from `@/components/ui/*`, never rewrite primitives. Extend via `className` / `asChild`; do not copy-paste component source.
