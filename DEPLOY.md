# Getting a public link

## Step 1 — deploy from your laptop first (about 5 minutes)

Do this before wiring CI. You want to see the thing live and click through it
yourself before a pipeline is in the way.

```bash
cd reiseplan
git init && git add -A && git commit -m "Reiseplan POC"

brew install flyctl          # or: curl -L https://fly.io/install.sh | sh
fly auth login

# Keep the fly.toml in the repo — do not let launch regenerate it.
fly launch --no-deploy --copy-config --name reiseplan-uat --region fra

fly volumes create reiseplan_data --size 1 --region fra --yes

fly secrets set \
  UAT_CODES="rishabh:r1-plum,anna:r1-oak,priya:r1-ash,ci:round1-ci" \
  SESSION_SECRET="$(openssl rand -hex 32)"

fly deploy
```

Your link: `https://reiseplan-uat.fly.dev`

Check it before sharing:

```bash
curl -s https://reiseplan-uat.fly.dev/healthz
# {"ok":true,"build":"dev","gated":true}
```

`"gated": true` is the one that matters. If it says `false`, `UAT_CODES` did
not land and the app is open to the internet — fix that before you send the
URL to anyone.

## Step 2 — connect GitHub

No connector needed; `gh` is faster anyway.

```bash
gh auth login
gh repo create reiseplan --private --source=. --push

gh secret set FLY_API_TOKEN         --body "$(fly auth token)"
gh secret set SESSION_SECRET        --body "$(openssl rand -hex 32)"
gh secret set UAT_CODES             --body "rishabh:r1-plum,anna:r1-oak,priya:r1-ash,ci:round1-ci"
gh secret set UAT_TEST_CODE         --body "round1-ci"
gh secret set BROWSERSTACK_USERNAME --body "<your username>"
gh secret set BROWSERSTACK_ACCESS_KEY --body "<your key>"
gh variable set FLY_APP_NAME        --body "reiseplan-uat"
```

Rotating `SESSION_SECRET` here logs everyone out, so use the same value you
set on Fly, or expect to re-authenticate testers on the next deploy.

From now on every push to `main` deploys and runs the BrowserStack matrix.

```bash
gh workflow run "deploy and browserstack"   # or just push
gh run watch
```

## Step 3 — run the browser suite locally once

Before you spend BrowserStack minutes, confirm the specs pass against the
live URL from your own machine. I could not execute these in the sandbox —
Chromium's CDN was unreachable — so this is their first real run.

```bash
cd e2e && npm install && npx playwright install chromium
BASE_URL=https://reiseplan-uat.fly.dev UAT_TEST_CODE=round1-ci \
  npx playwright test --project=chromium
```

Then the full matrix:

```bash
BROWSERSTACK_USERNAME=... BROWSERSTACK_ACCESS_KEY=... \
BASE_URL=https://reiseplan-uat.fly.dev UAT_TEST_CODE=round1-ci \
  npm run test:bs
```

## Step 4 — hand out codes

One code per person, from the `UAT_CODES` you set. Feedback is attributed, so
the summary tells you who tested and who went quiet:

```bash
curl -s https://reiseplan-uat.fly.dev/api/feedback/summary \
  -H "x-uat-token: <paste from your browser cookie>"
```

Revoke one tester: drop their entry from `UAT_CODES`, `fly deploy`.
End the round: rotate `SESSION_SECRET`.

---

## What will probably go wrong

**`fly launch` overwrites fly.toml.** It likes to regenerate config and guess
your app is a generic Python project. `--copy-config --no-deploy` keeps what
is in the repo. If it rewrites anyway, `git checkout fly.toml` and deploy.

**Volume in the wrong region.** The volume and the machine must share a
region or the mount fails at boot with a confusing scheduling error. Both are
`fra` above.

**First request is slow.** `min_machines_running = 1` keeps one warm. If you
drop it to 0 to save money, testers will hit a 5–10 second cold start and
report it as a bug.

**DB rate limiting under load.** `DB_API_BASE` points at
`v6.db.transport.rest`, which allows 100 requests per minute *for the entire
internet*. Ten testers clicking around is fine. A demo where twenty people
search at once is not. Before anything public, run your own container:

```bash
fly launch --image ghcr.io/public-transport/db-vendo-client:latest \
  --name reiseplan-db --region fra
fly secrets set DB_API_BASE="http://reiseplan-db.internal:3000" -a reiseplan-uat
```

**Cookies fail on Safari.** `COOKIE_SECURE=true` plus `force_https` is
already set, which is what Safari's ITP wants. If you ever test over plain
HTTP, set `COOKIE_SECURE=false` or the session silently will not persist —
and the symptom looks like a broken login, not a cookie problem.
