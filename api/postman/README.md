# Week 2 Postman companion

`Elder_Engage_Sprint3_Draft.postman_collection.json` is generated from safe, synthetic examples for the current REST draft.

Generate it from the project root with:

```powershell
node tools\generate_engagement_postman.mjs
```

The collection is contract-only. Its presence does not mean that an endpoint is implemented, callable, deployed or accepted. The default origin is loopback, all identity values are synthetic and credential variables are empty or explicitly non-working placeholders.

Before an iOS handoff, regenerate the collection from the same Git commit as the OpenAPI and deployed backend, use only approved staging access delivered through a secure channel, run the agreed smoke tests and record receipt by the named iOS developer.
