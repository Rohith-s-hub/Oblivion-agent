# TypeScript Knowledge Pack

## CRITICAL: Strict Mode is Non-Negotiable

ALWAYS initialize every TypeScript project with strict mode enabled. Without it, the compiler
misses entire classes of runtime bugs. Every project MUST have this in tsconfig.json:

    {
      "compilerOptions": {
        "strict": true,
        "noUncheckedIndexedAccess": true,
        "exactOptionalPropertyTypes": true,
        "noImplicitReturns": true,
        "noFallthroughCasesInSwitch": true,
        "forceConsistentCasingInFileNames": true,
        "esModuleInterop": true,
        "skipLibCheck": false,
        "moduleResolution": "bundler"
      }
    }

NEVER disable strict mode to silence errors. Fix the type instead.
NEVER use // @ts-ignore without a comment explaining exactly why.
NEVER use // @ts-nocheck in any file you did not generate from an external tool.

noUncheckedIndexedAccess is OFF by default even in strict mode. ALWAYS enable it manually.
It makes arr[0] return T | undefined instead of T, catching the most common runtime crash.

exactOptionalPropertyTypes distinguishes { a?: string } (key absent) from
{ a: string | undefined } (key present, value undefined). Enable it. They are not the same.


## Project Setup

### New Node.js/Backend Project

    mkdir my-project && cd my-project
    npm init -y
    npm install typescript tsx @types/node --save-dev
    npx tsc --init

Then overwrite tsconfig.json with the strict config above and add:

    "compilerOptions": {
      "target": "ES2022",
      "module": "NodeNext",
      "moduleResolution": "NodeNext",
      "outDir": "./dist",
      "rootDir": "./src",
      "declaration": true,
      "sourceMap": true
    }

Add to package.json:

    "scripts": {
      "dev": "tsx watch src/index.ts",
      "build": "tsc",
      "start": "node dist/index.js",
      "typecheck": "tsc --noEmit"
    }

ALWAYS separate typecheck from build. Run typecheck in CI without emitting files.

### New React/Vite Project

    npm create vite@latest my-app -- --template react-ts
    cd my-app && npm install

Add to tsconfig.app.json compilerOptions:

    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitReturns": true

### Monorepo with Workspaces

    {
      "compilerOptions": {
        "composite": true,
        "declarationMap": true
      }
    }

Each package needs its own tsconfig.json with "references" pointing to its deps.
ALWAYS use tsc --build (not plain tsc) in monorepos. Plain tsc ignores project references.


## CRITICAL: Common Foot-Guns

### 1. any Propagates Silently

    const data: any = fetchData();
    const name = data.user.name; // no error, crashes at runtime

NEVER assign any to a variable. If you receive any from a library, narrow it immediately:

    const data: unknown = fetchData();
    if (typeof data === "object" && data !== null && "user" in data) {
      // now narrow further
    }

### 2. Optional Chaining Does Not Narrow the Type

    const val = obj?.foo?.bar;
    // val is string | undefined -- but you might forget the undefined

ALWAYS handle the undefined case after optional chaining before passing the value anywhere
that expects a non-optional type.

### 3. as Casts Lie to the Compiler

    const el = document.getElementById("root") as HTMLElement;
    el.innerHTML = "hello"; // crashes if element does not exist

Use assertion functions or runtime checks:

    const el = document.getElementById("root");
    if (!el) throw new Error("root element missing");
    el.innerHTML = "hello";

Only use as when you have already confirmed the type through a runtime check and TypeScript
cannot see it.

### 4. JSON.parse Returns any

ALWAYS parse with a validation library. Never trust JSON.parse output:

    import { z } from "zod";
    const schema = z.object({ name: z.string() });
    const result = schema.parse(JSON.parse(raw)); // throws on invalid shape

### 5. Enums Have Runtime Overhead and Merge Surprises

Numeric enums (default) produce a reverse mapping object at runtime. Const enums break
with isolatedModules (used by Vite, esbuild, babel). AVOID enums entirely. Use union types:

    type Direction = "north" | "south" | "east" | "west";

Or use as const objects when you need the value dict:

    const Direction = { North: "north", South: "south" } as const;
    type Direction = typeof Direction[keyof typeof Direction];

### 6. forEach Does Not Await Promises

    arr.forEach(async (item) => {
      await doSomething(item); // promises are fired and forgotten
    });

ALWAYS use for...of for sequential async, or Promise.all(arr.map(...)) for parallel:

    for (const item of arr) {
      await doSomething(item);
    }

    await Promise.all(arr.map((item) => doSomething(item)));

### 7. Type Widening on let

    let x = "hello"; // inferred as string, not "hello"
    let y = "hello" as const; // inferred as "hello"

When you need a literal type, use as const or annotate explicitly.

### 8. Index Signatures Allow Missing Keys Without noUncheckedIndexedAccess

    const map: Record<string, string> = {};
    const val = map["missing"]; // without noUncheckedIndexedAccess: type is string

This is why noUncheckedIndexedAccess is mandatory. Without it, val.toUpperCase() crashes.


## File Templates

### src/types/index.ts - Shared Type Utilities

    // Make all properties required and non-nullable
    type Required<T> = { [K in keyof T]-?: NonNullable<T[K]> };

    // Extract the resolved value of a Promise
    type Awaited<T> = T extends Promise<infer U> ? U : T;

    // Branded types - prevent mixing semantically different strings
    type Brand<T, B> = T & { readonly _brand: B };
    type UserId = Brand<string, "UserId">;
    type OrderId = Brand<string, "OrderId">;

    // Result type - avoid throwing for expected failures
    type Result<T, E = Error> =
      | { ok: true; value: T }
      | { ok: false; error: E };

    function ok<T>(value: T): Result<T> {
      return { ok: true, value };
    }
    function err<E = Error>(error: E): Result<never, E> {
      return { ok: false, error };
    }

    export type { Brand, UserId, OrderId, Result };
    export { ok, err };

### src/lib/assert.ts - Assertion Utilities

    export function assert(condition: unknown, message: string): asserts condition {
      if (!condition) throw new Error("Assertion failed: " + message);
    }

    export function assertDefined<T>(
      val: T | null | undefined,
      message: string
    ): asserts val is T {
      if (val === null || val === undefined) {
        throw new Error("Expected defined value: " + message);
      }
    }

    export function unreachable(x: never, message?: string): never {
      throw new Error(message ?? "Unreachable case: " + JSON.stringify(x));
    }

Use unreachable in exhaustive switch statements:

    switch (direction) {
      case "north": return moveNorth();
      case "south": return moveSouth();
      default: return unreachable(direction); // compile error if a case is missing
    }

### src/lib/env.ts - Typed Environment Variables

    import { z } from "zod";

    const envSchema = z.object({
      NODE_ENV: z.enum(["development", "production", "test"]),
      PORT: z.coerce.number().default(3000),
      DATABASE_URL: z.string().url(),
      JWT_SECRET: z.string().min(32),
    });

    export const env = envSchema.parse(process.env);

ALWAYS validate env vars at startup. NEVER access process.env.ANYTHING inline without
going through this module.


## Patterns

### Type Narrowing - The RIGHT Way

    // discriminated union - ALWAYS prefer this pattern for variant types
    type ApiResponse<T> =
      | { status: "success"; data: T }
      | { status: "error"; code: number; message: string }
      | { status: "loading" };

    function handleResponse<T>(res: ApiResponse<T>) {
      switch (res.status) {
        case "success":
          return res.data; // TypeScript knows data exists here
        case "error":
          return res.code + ": " + res.message;
        case "loading":
          return null;
        default:
          return unreachable(res);
      }
    }

### Generic Constraints

    // BAD - too loose
    function getProperty<T, K>(obj: T, key: K) { ... }

    // GOOD - constrained
    function getProperty<T extends object, K extends keyof T>(obj: T, key: K): T[K] {
      return obj[key];
    }

### Async Error Handling Without Try-Catch Everywhere

    async function safeAsync<T>(
      fn: () => Promise<T>
    ): Promise<Result<T, Error>> {
      try {
        return ok(await fn());
      } catch (e) {
        return err(e instanceof Error ? e : new Error(String(e)));
      }
    }

    // Usage
    const result = await safeAsync(() => fetchUser(id));
    if (!result.ok) {
      logger.error(result.error);
      return;
    }
    console.log(result.value);

### Zod Schema as Single Source of Truth

    import { z } from "zod";

    const UserSchema = z.object({
      id: z.string().uuid(),
      email: z.string().email(),
      role: z.enum(["admin", "user"]),
      createdAt: z.coerce.date(),
    });

    type User = z.infer<UserSchema>; // derive the type from the schema

    // Use the same schema for:
    // - API input validation
    // - Database row parsing
    // - Form validation (with zodResolver in react-hook-form)


## EDGE CASES AND GOTCHAS

### 1. moduleResolution "node" is Deprecated for ESM

If using "module": "NodeNext" or "module": "ESNext" targeting modern Node, set
"moduleResolution": "NodeNext" or "moduleResolution": "bundler". Using "node" with
ESM causes import resolution failures that look like missing modules.

### 2. isolatedModules Breaks Const Enums Silently

Vite and esbuild transpile each file independently. Const enum values get inlined at compile
time by tsc, but Vite does not run tsc -- it strips types with esbuild. Const enum
references become undefined at runtime with no error. Use as const objects instead.

### 3. strictNullChecks and Array Methods

    const arr = [1, 2, 3];
    const found = arr.find((x) => x > 2);
    // found is number | undefined -- NOT number

ALWAYS handle the undefined case from find, at, and indexed access.

### 4. Type Predicates Can Lie

    function isString(x: unknown): x is string {
      return true; // compiles, lies at runtime
    }

TypeScript trusts your type predicate return value completely. A wrong predicate corrupts
the type system silently. ALWAYS verify the runtime check matches the claimed type.

### 5. Object.keys Returns string[], Not (keyof T)[]

    const obj = { a: 1, b: 2 };
    Object.keys(obj).forEach((key) => {
      obj[key]; // ERROR: Element implicitly has an any type
    });

Cast explicitly when you know the shape:

    (Object.keys(obj) as (keyof typeof obj)[]).forEach((key) => {
      obj[key]; // number
    });

### 6. Interface vs Type Alias Merging

Interfaces can be re-declared and merged. Type aliases cannot. This matters for library
augmentation. Use interface when you expect consumers to extend your type. Use type
for unions, intersections, and computed types.

### 7. Excess Property Checking Only on Fresh Object Literals

    type Point = { x: number; y: number };
    const p: Point = { x: 1, y: 2, z: 3 }; // ERROR - excess property
    const obj = { x: 1, y: 2, z: 3 };
    const p2: Point = obj; // NO ERROR - obj is a wider type, structurally compatible

For strict input validation, use Zod or explicit runtime checks.

### 8. Promise<void> is Not Interchangeable with () => void

    type VoidFn = () => void;
    const asyncFn: VoidFn = async () => { await something(); }; // compiles
    // but the caller will NOT await it -- fire and forget silently

When a callback is expected to be async, declare it as () => Promise<void>, not () => void.

### 9. tsconfig.json paths Do Not Work at Runtime

Adding path aliases in tsconfig ("@/*": ["./src/*"]) makes the compiler happy but Node.js
has no idea about them at runtime. You MUST also configure the bundler (Vite, webpack) or
use tsconfig-paths for Node scripts:

    node -r tsconfig-paths/register dist/index.js

### 10. Declaration Files (.d.ts) Are Not Compiled, They Are Loaded

If you place a .d.ts file in src/, tsc loads it as ambient declarations. Any
export in it makes it a module-scoped declaration (not global). Omit export or use
declare global {} for global augmentations.


## BACKUP-BEFORE-CHANGE Protocol

### Before Changing tsconfig.json

    cp tsconfig.json tsconfig.json.bak
    npx tsc --noEmit 2>&1 | tee /tmp/ts-errors-before.txt

After the change, compare error counts. A new strict flag can expose hundreds of latent errors.

### Before Mass Type Refactor (changing a shared interface/type)

    git stash push -m "pre-refactor-snapshot"
    git checkout -b refactor/type-name

Run npx tsc --noEmit first. Record the baseline error count. Never start a refactor on
a branch that already has type errors -- you cannot tell what you introduced.

### Before Upgrading TypeScript Version

    cp package.json package.json.bak
    cp tsconfig.json tsconfig.json.bak
    npx tsc --noEmit 2>&1 | wc -l  # baseline error count

Then upgrade and recount. Each major TS version tightens inference -- new errors are expected.

### Before Upgrading a @types/* Package

    npm ls @types/node  # record current version
    cp package-lock.json /tmp/package-lock.bak.json

Type definition upgrades can change inferred types in ways that cascade across the project.


## DIAGNOSTIC RECIPES

### When tsc Reports Errors But the App Runs Fine

    1. Run: npx tsc --noEmit --listFiles | head -50
       -- check which files are being included
    2. Look for skipLibCheck: true in tsconfig -- this hides library errors but also
       hides your own errors if they are in .d.ts files
    3. Check include and exclude arrays in tsconfig
    4. Run: npx tsc --noEmit --traceResolution 2>&1 | grep ERROR | head -20
    5. If errors are in node_modules, set skipLibCheck: true ONLY as a last resort
       and document why

### When Module Resolution Fails at Runtime (import works in tsc, crashes in Node)

    1. Check module and moduleResolution in tsconfig
    2. For ESM: confirm package.json has "type": "module"
    3. For ESM imports: file extensions MUST be explicit in source
       -- write: import { foo } from "./foo.js"  (not ./foo.ts, not ./foo)
    4. For path aliases: confirm tsconfig-paths is loaded or bundler alias config matches
    5. Run: node --input-type=module --eval "import './dist/index.js'"
       to get the raw Node error

### When Generic Type Inference Breaks and You Get unknown

    1. Hover over the function call in the IDE to see what TypeScript inferred
    2. Explicitly pass the type parameter: fn<MyType>(arg) instead of fn(arg)
    3. Check if the generic constraint is too narrow or if the argument type does not
       satisfy the constraint
    4. Add a temporary console.log of the type via a helper:
           function typeCheck<T>(_: T): T { return _; }
           const result = typeCheck(myValue); // hover shows inferred type

### When exactOptionalPropertyTypes Causes Mass Errors After Enabling

    1. Run: npx tsc --noEmit 2>&1 | grep exactOptional | wc -l
    2. The most common pattern to fix:
       -- WRONG: { foo?: string } receiving { foo: string | undefined }
       -- FIX: explicitly conditionally include the key:
           const obj = { ...(value !== undefined && { foo: value }) };

### When Zod Validation Fails in Prod But Passes in Dev

    1. Log the raw input BEFORE parsing: console.log(JSON.stringify(input))
    2. Check for Date vs string mismatch -- databases return Date objects,
       APIs return strings. Use z.coerce.date() for inputs that could be either.
    3. Check for extra fields with .strict() vs .strip() (default) vs .passthrough()
    4. Check for number coercion: query params are always strings, use z.coerce.number()


## COMMON ERRORS Table

| Error | Cause | Fix |
|---|---|---|
| Object is possibly undefined | noUncheckedIndexedAccess or optional chain | Add null check or use assertDefined() |
| Type string is not assignable to type never | Exhaustive check failed - union has unhandled case | Add missing case to switch or discriminated union |
| Cannot find module ./foo | Missing file extension in ESM or wrong moduleResolution | Add .js extension to import path (even for .ts files in ESM) |
| Property does not exist on type never | Previous narrowing made type never - logic bug | Check if conditions are mutually exclusive |
| Argument of type string undefined not assignable | Caller passes optional, callee expects required | Assert defined before call or make callee accept undefined |
| Type instantiation is excessively deep | Recursive generic, usually in Zod or mapped types | Break the recursion: use interface instead of type alias |
| isolatedModules - Re-exporting a type without type-only keyword | Vite/esbuild strips types, not values | Change export Foo to export type Foo |
| Declaration or statement expected | .ts file parsed as script, not module | Add at least one import or export, or add export {} |
| Expression produces a union type that is too complex | Too many combinations in a conditional type | Simplify the type or extract intermediate type aliases |
| Cannot use namespace as a type | Merged namespace/class pattern broken | Separate namespace and class declarations |


## Anti-Patterns

### NEVER use any as a function parameter type

    // BAD
    function process(data: any) { ... }

    // WHY: any infects everything it touches. Callers pass garbage, internals make
    // unverified assumptions, and runtime errors appear far from the source.

    // GOOD
    function process(data: unknown) {
      // narrow before use
    }

### NEVER use non-null assertion ! instead of a check

    // BAD
    const el = document.getElementById("root")!;

    // WHY: If the element is missing (wrong environment, SSR, test), you get
    // "Cannot set property of null" with no stack context pointing to the assertion.

    // GOOD
    const el = document.getElementById("root");
    if (!el) throw new Error("Missing #root element");

### NEVER use Function as a type

    // BAD
    function call(fn: Function) { fn(1, 2); }

    // WHY: Function is as unsafe as any for callable types. No parameter checking.

    // GOOD
    function call(fn: (a: number, b: number) => void) { fn(1, 2); }

### NEVER spread args: any[] for variadic functions

    // BAD
    function log(...args: any[]) { console.log(...args); }

    // GOOD
    function log(...args: unknown[]) { console.log(...args); }

### NEVER put business logic in .d.ts files

Type declaration files are for ambient type declarations only. Any runtime code in a .d.ts
file is silently ignored. Logic in .d.ts produces no output and no error.

### NEVER import types without the type keyword when using isolatedModules

    // BAD
    import { User } from "./types";

    // GOOD
    import type { User } from "./types";

    // WHY: Without import type, esbuild and Vite cannot determine if the import
    // is a value or type at transpile time.

### NEVER cast with as unknown as TargetType except in tests

    // BAD (in production code)
    const user = {} as unknown as User;

    // WHY: Double casting bypasses every type check. It is a promise to the compiler
    // that you are lying to it.

### NEVER rely on TypeScript to catch runtime type errors from external data

TypeScript is erased at runtime. fetch() returns any from the perspective of the actual
data shape. JSON from an API, data from localStorage, data from a database ORM that uses
unsafe casts -- NONE of it is guaranteed to match your TypeScript types without a runtime
validator (Zod, Valibot, io-ts). ALWAYS validate at trust boundaries.


## Production Checklist

- "strict": true in tsconfig.json
- "noUncheckedIndexedAccess": true in tsconfig.json
- "exactOptionalPropertyTypes": true in tsconfig.json
- npx tsc --noEmit exits with code 0 in CI
- No @ts-ignore without a comment explaining the exception
- No any types in function signatures (search: ": any")
- No non-null assertions ! on DOM queries or external data
- All JSON.parse calls go through a Zod schema or equivalent validator
- All environment variables accessed through a validated env module
- All async callbacks in forEach converted to for...of or Promise.all
- import type used for all type-only imports
- No numeric enums or const enums (use as const objects or union literals)
- Path aliases in tsconfig.json matched in bundler config AND runtime loader
- .js extensions on all relative imports when targeting ESM Node.js
- tsconfig-paths or equivalent configured for any Node.js scripts with path aliases
- Exhaustive switch statements use unreachable() on the default branch
- All Promise<void>-returning callbacks typed as () => Promise<void>, not () => void
- No business logic in .d.ts files
- TypeScript version pinned in package.json (not ^)
- @types/* packages pinned to avoid silent inference changes
