# Sprint 3 Postman companion

`Elder_Engage_Sprint3_Draft.postman_collection.json` is generated from safe, synthetic examples for the current REST draft.

Generate it from the project root with:

```powershell
node tools\generate_engagement_postman.mjs
```

The collection is contract-only. Its presence does not mean that an endpoint is implemented, callable, deployed or accepted. The default origin is loopback, all identity values are synthetic and credential variables are empty or explicitly non-working placeholders.

For iOS development integration, share `../handover/backend-release-1/postman_collection.json` together with its README and OpenAPI file. That collection uses the protected development address and excludes the two unimplemented Administrator routes. It contains no live test credential. The historical collection here remains for source-contract regression checks, not direct handover.
