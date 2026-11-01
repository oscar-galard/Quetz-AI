---
skill: typescript
layer: interface
tags: [typescript, types, strict, frontend]
---

## Strict configuration

```json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "moduleResolution": "bundler"
  }
}
```

Rules:
- Always enable `strict`. Turn on `noUncheckedIndexedAccess` for array access safety.
- Use `unknown` + type guards instead of `any`. Never disable `eslint` rules inline.
- Prefer `readonly` arrays / `Readonly<T>` for shared data.

## Types vs interfaces

- Use `interface` for object shapes that consumers extend.
- Use `type` for unions, intersections, mapped types, and literals.
- Export types alongside the component they describe.

## Error handling

```ts
export async function fetchSubscriber(id: string): Promise<Subscriber> {
  const response = await api.get(`/subscribers/${id}`);
  if (!response.ok) {
    throw new SubscriberNotFoundError(id);
  }
  return SubscriberSchema.parse(await response.json());
}
```

Rules:
- Use discriminated unions for error kinds (`{ kind: "not_found" } | { kind: "unauthorized" }`).
- Validate third-party responses with Zod before using them.
- Never swallow errors silently — rethrow or log with context.
