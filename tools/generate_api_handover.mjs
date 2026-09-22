import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const destination = path.join(root, 'api', 'handover', 'backend-release-1');
const sourceSpec = path.join(root, 'api', 'openapi', 'elder-engage-v1.openapi.json');
const sourceCollection = path.join(root, 'api', 'postman', 'Elder_Engage_Sprint3_Draft.postman_collection.json');
const baseUrl = 'https://api-test.eldercaresaathi.com';
const methods = new Set(['get', 'post', 'put', 'patch', 'delete']);
const check = process.argv.includes('--check');
const load = async (name) => JSON.parse(await readFile(name, 'utf8'));
const encode = (value) => `${JSON.stringify(value, null, 2)}\n`;
const digest = (value) => createHash('sha256').update(value).digest('hex');

const spec = await load(sourceSpec);
const collection = await load(sourceCollection);
if (spec.info.version !== '0.3.5' || spec['x-contract-status'] !== 'sprint-3-draft') {
  throw new Error('Source contract version/status changed; review the handover before regenerating.');
}
const planned = [];
for (const [route, item] of Object.entries(spec.paths)) {
  for (const method of Object.keys(item)) {
    if (!methods.has(method)) continue;
    if (item[method]['x-implementation-status'] === 'planned-not-callable') {
      planned.push(`${method.toUpperCase()} ${route}`);
      delete item[method];
    }
  }
  if (Object.keys(item).length === 0) delete spec.paths[route];
}
if (planned.sort().join('|') !== 'GET /v1/admin/users|POST /v1/admin/users') {
  throw new Error(`Unexpected planned routes: ${planned.join(', ')}`);
}

spec.info.summary = 'Backend Release 1 callable REST API for development integration';
spec.info.description = 'Shareable development-integration contract for the protected client-owned Amiko test address. This is not production deployment, Google Play release, or client acceptance. Only routes implemented in Backend Release 1 are listed. Test identities and credentials are provided separately through an approved private channel.';
spec['x-contract-status'] = 'backend-release-1-development-handover';
spec['x-implementation-status'] = 'The 36 listed operations have matching backend routes in the development release; authenticated scenarios require separately authorised test access.';
delete spec['x-planned-expansions'];
spec.servers = [{ url: baseUrl, description: 'Protected development integration address; not production' }];
const replaceDescription = (route, method, oldText, newText) => {
  const operation = spec.paths[route]?.[method];
  if (!operation?.description?.includes(oldText)) {
    throw new Error(`Expected source wording changed for ${method.toUpperCase()} ${route}; review it.`);
  }
  operation.description = operation.description.replace(oldText, newText);
};
replaceDescription('/v1/auth/staff/session', 'post',
  'Administrators require a password plus a verified authenticator-app code; enrollment and verification remain pending implementation. The validated staff endpoint is a disabled-by-default interface candidate, not deployed or accepting real credentials yet. Without a real staff adapter it returns DEPENDENCY_UNAVAILABLE and never issues tokens.',
  'Administrators require a password plus a verified authenticator-app code. Fictional development staff accounts are available only through the approved private test-access process; real staff onboarding belongs to the later Administrator console.');
replaceDescription('/v1/auth/refresh', 'post',
  'because this draft defines no safe recovery/status operation. This implementation step supports Members only; staff support remains dependent on EE-010, and deployment verification is required before treating it as callable.',
  'because this release defines no safe recovery/status operation. This rule applies to Member and staff sessions.');
for (const [route, method] of [
  ['/v1/auth/logout', 'post'],
  ['/v1/me/sessions', 'get'],
  ['/v1/me/sessions/{sessionId}', 'delete'],
]) {
  replaceDescription(route, method, ' Staff support remains pending implementation.', ' Member and staff sessions are supported.');
}
spec['x-client-error-actions'].REFRESH_OUTCOME_UNKNOWN =
  spec['x-client-error-actions'].REFRESH_OUTCOME_UNKNOWN.replace('this draft', 'this release');

const allowed = new Set(Object.entries(spec.paths).flatMap(([route, item]) =>
  Object.keys(item).filter((method) => methods.has(method)).map((method) => `${method.toUpperCase()} ${route}`),
));
if (allowed.size !== 36) throw new Error(`Expected 36 callable operations; found ${allowed.size}.`);
const routeKey = (entry) => {
  const url = entry.request.url.raw.replace(/^\{\{baseUrl\}\}/, '').split('?')[0]
    .replace(/\{\{([^{}]+)\}\}/g, '{$1}');
  return `${entry.request.method.toUpperCase()} ${url}`;
};
const kept = new Set();
for (const group of collection.item) {
  group.item = group.item.filter((entry) => {
    const key = routeKey(entry);
    if (!allowed.has(key)) return false;
    if (kept.has(key)) throw new Error(`Duplicate Postman request: ${key}`);
    kept.add(key);
    entry.request.description = entry.request.description.replace(
      /^Contract-only request\. It is not claimed callable until the matching backend is deployed and verified\.$/,
      'Backend Release 1 development route. Use only authorised test identities; production availability is not claimed.',
    );
    return true;
  });
}
if (kept.size !== 36 || [...allowed].some((key) => !kept.has(key))) {
  throw new Error('Postman requests do not match the 36 callable OpenAPI operations.');
}
collection.info.name = 'Amiko Backend Release 1 - Development Integration';
collection.info.description = 'Only the 36 callable development API operations. No credentials included. Read README.md before use; production availability and client acceptance are not claimed.';
for (const variable of collection.variable) {
  if (variable.key === 'baseUrl') variable.value = baseUrl;
  if (variable.key === 'providerIdToken') variable.value = '';
}
const staff = collection.item.flatMap((group) => group.item).find((entry) =>
  entry.request.url.raw.endsWith('/v1/auth/staff/session'),
);
if (!staff) throw new Error('Staff sign-in request missing.');
const staffBody = JSON.parse(staff.request.body.raw);
staffBody.username = '{{staffUsername}}';
staffBody.password = '{{staffPassword}}';
staff.request.body.raw = JSON.stringify(staffBody, null, 2);
staff.request.description = 'Contributor and Administrator sign-in use this route. Administrator sign-in also requires the current authenticator-app code. Test credentials must be supplied privately; none are in this collection.';
const refresh = collection.item.flatMap((group) => group.item).find((entry) =>
  entry.request.url.raw.endsWith('/v1/auth/refresh'),
);
if (!refresh?.request.description.includes('this draft')) {
  throw new Error('Expected Postman refresh guidance changed; review it.');
}
refresh.request.description = refresh.request.description.replace('this draft', 'this release');
collection.variable.push(
  { key: 'staffUsername', value: '', type: 'string' },
  { key: 'staffPassword', value: '', type: 'string' },
);

const specText = encode(spec);
const collectionText = encode(collection);
const manifest = {
  package: 'Amiko Backend Release 1 REST API development handover',
  generatedOn: '2026-09-23',
  environment: 'protected development integration; not production',
  baseUrl,
  apiVersion: spec.info.version,
  implementedRouteCount: allowed.size,
  excludedOperations: planned,
  verifiedOperationalRoute: 'GET /ready returned HTTP 200 twice after the 2026-09-23 development deployment; not an iOS integration endpoint',
  deployedBackendSourceRevision: '7b7f2afc040d07233b574ebf1fae678cdb56a1eb',
  lastRecordedDevelopmentImageDigest: 'sha256:f5ef5dca510f231586d47ad4482fa2cd3537ed9b1790f3fcab151ad8e90053e1',
  buildEvidence: 'https://github.com/Anit0607/elder-engagement-platform/actions/runs/35775799854',
  gatewaySmokeEvidence: 'https://github.com/Anit0607/elder-engagement-platform/actions/runs/35776484294',
  files: {
    'openapi.json': digest(specText),
    'postman_collection.json': digest(collectionText),
  },
  note: 'The pinned image and source revision were checked against the running Cloud Run service after deployment. The protected public address passed health, readiness, unauthenticated denial and direct-address safeguards. This package contains no live credentials or client personal data.',
};
const files = {
  'openapi.json': specText,
  'postman_collection.json': collectionText,
  'manifest.json': encode(manifest),
};
if (!check) await mkdir(destination, { recursive: true });
for (const [name, content] of Object.entries(files)) {
  const target = path.join(destination, name);
  if (check) {
    if (await readFile(target, 'utf8') !== content) throw new Error(`${name} is out of date. Regenerate and review the package.`);
  } else {
    await writeFile(target, content, 'utf8');
  }
}
console.log(`${check ? 'Verified' : 'Generated'} Backend Release 1 API handover: 36 implemented routes, 2 excluded.`);
