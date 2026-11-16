# Vendored code

Third-party code kept in the repository instead of installed, because its maintainers stopped updating it (CR-007 R19.9). **Never edit these files.** To change one, replace it with an upstream release, checked as below.

| Package | Version | Licence | Files | Why |
|---|---|---|---|---|
| [openapi-fetch](https://github.com/openapi-ts/openapi-typescript/tree/main/packages/openapi-fetch) | 0.17.0 | MIT | `src/index.js`, `src/index.d.ts` | In maintenance mode since 2025-12-29 ([#2559](https://github.com/openapi-ts/openapi-typescript/discussions/2559)); its maintainers advise keeping a copy in the project |
| [openapi-typescript-helpers](https://github.com/openapi-ts/openapi-typescript/tree/main/packages/openapi-typescript-helpers) | 0.1.0 | MIT | `dist/index.d.ts` (types only) | openapi-fetch's one dependency |

**Provenance.** Both tarballs came from `registry.npmjs.org`, and their sha512 matched the integrity the lockfile had pinned for them:

```
openapi-fetch-0.17.0.tgz               sha512-PsbZR1wAPcG91eEthKhN+Zn92FMHxv+/faECIwjXdxfTODGSGegYv0sc1Olz+HYPvKOuoXfp+0pA2XVt2cI0Ig==
openapi-typescript-helpers-0.1.0.tgz   sha512-OKTGPthhivLw/fHz6c3OPtg72vi86qaMlqbJuVJ23qOvQ+53uw1n7HdmkJFibloF7QEjDrDkzJiOJuockM/ljw==
```

The files are copied unchanged, except one line: `openapi-fetch/index.d.ts` imports its helper types from `../openapi-typescript-helpers/index.js` instead of the package name. Their sha256 as vendored:

```
4b8611e828be5c9475e1be3486722516a583c983a05b7beebb91db312dd01c17  openapi-fetch/index.js
188f4d17f76292ef3336fc067e74b69997a786e8b3340ee782be7cd994480553  openapi-fetch/index.d.ts
e08859a0433654484c23ea7d2447e7da43768e228643cde336290e80359be015  openapi-typescript-helpers/index.d.ts
```

The generator, `openapi-typescript` 7.13.0, is frozen too but stays a dev dependency: it only runs in development and CI, never in the browser. It is to be replaced before TypeScript 7 (the roadmap's backlog).
