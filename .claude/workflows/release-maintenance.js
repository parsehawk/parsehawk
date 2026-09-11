export const meta = {
  name: 'release-maintenance',
  description: 'One Maintain parsehawk release run for Dependabot alerts: read the open alerts, patch them on a branch, run the local checks, run the GPU-dependent end-to-end suite on the Linux NVIDIA VM over SSH, open or update the pull request, and, with merge: true, rebase-merge it once CI is green.',
  whenToUse: 'Run daily by the scheduled task or by hand from any working folder. args: {date: "YYYY-MM-DD" (required), dispatchedBy: "benedikt-hielscher" (required), coverFor: null, repoPath: "~/Projects/deeptable/parsehawk", gpuHost: "<ssh host alias>" (required), gpuRepoPath: "~/parsehawk", gpuHostLocation: null, issue: null, merge: false, dryRun: false, macE2E: false, allowMajor: false, startRuntime: true, companyOsRoot: "~/.claude/skills/closing-loops-company-os"}',
  phases: [
    { title: 'Preflight', detail: 'read-only: identities, clean main, toolchain, GPU host, existing sweep branch or PR' },
    { title: 'Review', detail: 'open Dependabot alerts, early exits, triage per alert, deadlines in code, case record' },
    { title: 'Patch', detail: 'branch, one patch agent per ecosystem, atomic conventional commits' },
    { title: 'Verify', detail: 'rebase, then local just check and GPU worktree tests in parallel; SHA-bound' },
    { title: 'Deliver', detail: 'push, open or update the PR, full CI via workflow_dispatch, then merge when authorized and green' },
  ],
}

// ---------------------------------------------------------------------------
// Dispatch workflow for the Company OS Workflow "Maintain parsehawk release"
// (decision 0032), scoped to Dependabot alerts: Prepare parsehawk release
// maintenance (read and triage the alerts) -> Maintain parsehawk release
// (patch, test locally, test on the Linux NVIDIA host, open the pull
// request, and merge it). With merge: true the run rebase-merges its own
// pull request once local checks, the GPU suite, and full CI passed on the
// same head; without it the run ends with the pull request open. A person
// records the Activity outcome either way.
//
// Boundaries kept on purpose:
//   - The merge is gated on args.merge, green CI, and an unchanged head
//     (--match-head-commit). No version tag, no release, no customer
//     deployment.
//   - Exactly one sweep branch at a time. An open sweep PR is continued when
//     new alerts appear and left alone otherwise, so the daily run is
//     idempotent.
//   - The Linux NVIDIA host is never mutated beyond a throwaway worktree
//     and, when allowed, starting the model runtime that the end-to-end
//     suite needs.
//   - Only public advisory data (GHSA ids, package names, versions) is
//     written to GitHub. No logs, no secrets.
//   - dryRun keeps everything local: no push to origin, no Issue or PR
//     write; the GPU host still receives the branch into its worktree.
// ---------------------------------------------------------------------------

const a = args && typeof args === 'object' ? args : {}
const DATE = a.date
const DISPATCHED_BY = a.dispatchedBy
const COVER_FOR = a.coverFor || null
const REPO_PATH = a.repoPath || '~/Projects/deeptable/parsehawk'
const GPU_HOST = a.gpuHost || null
const GPU_REPO = a.gpuRepoPath || '~/parsehawk'
const GPU_HOST_LOCATION = a.gpuHostLocation || null
const ISSUE = Number.isInteger(a.issue) && a.issue > 0 ? a.issue : null
const MERGE = a.merge === true
const DRY_RUN = a.dryRun === true
const MAC_E2E = a.macE2E === true
const ALLOW_MAJOR = a.allowMajor === true
const START_RUNTIME = a.startRuntime !== false
const COS = a.companyOsRoot || '~/.claude/skills/closing-loops-company-os'
const REPO = 'parsehawk/parsehawk'
const BRANCH_PREFIX = 'chore/dependabot-'
const BRANCH = `${BRANCH_PREFIX}${DATE}`
const WORKTREE = `${GPU_REPO}-dependabot-${DATE}`
const POLICY_DAYS = 7

if (!DATE || !/^\d{4}-\d{2}-\d{2}$/.test(DATE)) return { status: 'refused', reason: 'args.date (YYYY-MM-DD) is required; scripts cannot read the clock.' }
if (!DISPATCHED_BY) return { status: 'refused', reason: 'args.dispatchedBy (actor slug) is required.' }
if (!GPU_HOST) return { status: 'refused', reason: 'args.gpuHost (the SSH alias of the Linux NVIDIA VM) is required.' }

// Civil-date arithmetic without the Date object (unavailable to scripts).
function dayNumber(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''))
  if (!m) return null
  const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3])
  const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0
  const dim = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  if (mo < 1 || mo > 12 || d < 1 || d > dim[mo - 1]) return null
  const yy = mo <= 2 ? y - 1 : y
  const era = Math.floor(yy / 400)
  const yoe = yy - era * 400
  const mp = (mo + 9) % 12
  const doy = Math.floor((153 * mp + 2) / 5) + d - 1
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy
  return era * 146097 + doe - 719468
}
function isoFromDayNumber(n) {
  const z = n + 719468
  const era = Math.floor(z / 146097)
  const doe = z - era * 146097
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365)
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100))
  const mp = Math.floor((5 * doy + 2) / 153)
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1
  const mo = mp < 10 ? mp + 3 : mp - 9
  const y = yoe + era * 400 + (mo <= 2 ? 1 : 0)
  return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}
const TODAY = dayNumber(DATE)
if (TODAY === null) return { status: 'refused', reason: `args.date ${DATE} is not a calendar date.` }
const slugOf = (link) => { const m = /graph\/actors\/([^|\]]+)/.exec(String(link || '')); return m ? m[1].trim() : null }

const ACT = `${COS}/graph/activities/maintain-parsehawk-release`
const COMMON = `You are executing one step of the Closing Loops Company OS Workflow "Maintain parsehawk release" for the public open-source repository ${REPO}. The local checkout is ${REPO_PATH}; run every repository command there (cd ${REPO_PATH} first, or use git -C ${REPO_PATH}). Dispatched by ${DISPATCHED_BY} on ${DATE}. Read ${REPO_PATH}/AGENTS.md first and follow it (conventional commits with a reasoning body, atomic deployable commits, trunk-based flow, docs are part of the contract). The Company OS instructions live in ${COS}/graph/workflows/maintain-parsehawk-release.md, ${ACT}/, and ${COS}/graph/policies/software-maintenance.md; read the ones named in your task. ${DRY_RUN ? 'DRY RUN: no git push to origin, no GitHub Issue, PR, or comment write. Local branch work, read-only remote reads, and a direct push into the GPU host worktree are fine.' : ''} Write only public advisory data (GHSA ids, package names, versions) to GitHub; never paste logs, secrets, or credentials. Prefix every network-bound command or watcher with a timeout (e.g. \`timeout -k 30 900 <cmd>\`) and report a timeout as a failure, not a pass. Record wall-clock timestamps with \`date -u +%Y-%m-%dT%H:%M:%SZ\`. Your final text is a return value for a script, not a message to a person.`

const ctx = {}
const result = (status, extra) => ({ status, ...ctx, ...(extra || {}) })

// ---------------------------------------------------------------------------
phase('Preflight')
// ---------------------------------------------------------------------------

const PREFLIGHT_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    accountableLinks: { type: 'array', items: { type: 'string' } },
    backupLinks: { type: 'array', items: { type: 'string' } },
    actorGithub: { type: 'object', additionalProperties: { type: 'string' } },
    ghLogin: { type: 'string' },
    companyOsRevision: { type: 'string' },
    gpuHostLocationExists: { type: ['boolean', 'null'] },
    mainSha: { type: 'string' },
    untrackedFiles: { type: 'array', items: { type: 'string' } },
    sweepBranches: { type: 'array', items: { type: 'string' } },
    openSweepPr: { type: ['object', 'null'], properties: { number: { type: 'number' }, url: { type: 'string' }, headBranch: { type: 'string' }, headSha: { type: 'string' }, alertNumbers: { type: 'array', items: { type: 'number' } } }, required: ['number', 'url', 'headBranch', 'headSha', 'alertNumbers'] },
    tools: { type: 'object', properties: { just: { type: 'boolean' }, uv: { type: 'boolean' }, pnpm: { type: 'boolean' }, gh: { type: 'boolean' }, node: { type: 'boolean' } } },
    gpu: { type: 'object', properties: { reachable: { type: 'boolean' }, hostname: { type: 'string' }, gpuName: { type: 'string' }, vram: { type: 'string' }, dockerNvidiaRuntime: { type: 'boolean' }, repoPresent: { type: 'boolean' }, repoDirty: { type: 'boolean' }, repoBranch: { type: 'string' }, runtimeUp: { type: 'boolean' }, worktreeExists: { type: 'boolean' }, detail: { type: 'string' } }, required: ['reachable'] },
    blockers: { type: 'array', items: { type: 'string' } },
    startedAt: { type: 'string' },
  },
  required: ['ok', 'accountableLinks', 'backupLinks', 'actorGithub', 'ghLogin', 'companyOsRevision', 'gpuHostLocationExists', 'mainSha', 'untrackedFiles', 'sweepBranches', 'openSweepPr', 'gpu', 'blockers', 'startedAt'],
}

const preflight = await agent(
  `${COMMON}

Task: read-only preflight. Change nothing except fast-forwarding main. Return facts; do not judge who may dispatch.
1. Read ${COS}/graph/workflows/maintain-parsehawk-release.md and return verbatim the wikilink strings of accountable_actors (accountableLinks) and backup_accountable_actors (backupLinks). For each linked actor and for ${DISPATCHED_BY}, read ${COS}/graph/actors/<slug>.md and return actorGithub as {slug: github username} from the "github:username:" external identity. Return companyOsRevision: the "commit" in ${COS}/installation.json, else \`git -C ${COS} rev-parse HEAD\`, else "unknown".
2. ${GPU_HOST_LOCATION ? `Confirm that ${COS}/${GPU_HOST_LOCATION} exists and names ${GPU_HOST} or its address (gpuHostLocationExists true/false).` : 'No gpuHostLocation was given; return gpuHostLocationExists = null.'}
3. \`gh auth status\` must show a login; return \`gh api user --jq .login\` as ghLogin.
4. In ${REPO_PATH}: the branch must be main and \`git status --porcelain --untracked-files=no\` must be empty (tracked modifications are a blocker); list untracked files in untrackedFiles (not a blocker). Then \`git fetch origin --prune && git pull --ff-only\`; return the main SHA. List local and remote branches starting with ${BRANCH_PREFIX} in sweepBranches. Find an open pull request whose head branch starts with ${BRANCH_PREFIX} (\`gh pr list --repo ${REPO} --state open --json number,url,headRefName,headRefOid,body\`); return it in openSweepPr with the Dependabot alert numbers parsed from its body's "alert #N" markers, or null.
5. Toolchain: just, uv, pnpm, gh, node. Any missing one is a blocker.
6. GPU host, read-only: \`ssh -o BatchMode=yes -o ConnectTimeout=10 ${GPU_HOST} 'hostname; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; docker info --format "{{json .Runtimes}}"; docker compose version; test -d ${GPU_REPO} && echo repo-present; git -C ${GPU_REPO} status --porcelain --untracked-files=no | head -3; git -C ${GPU_REPO} rev-parse --abbrev-ref HEAD; test -d ${WORKTREE} && echo worktree-exists; command -v uv just parsehawk; curl -s -m 3 http://127.0.0.1:8080/v1/models | head -c 200'\`. Report reachability, GPU name and VRAM, nvidia runtime registered, repo present, repo dirty, its branch, whether the model runtime answers (runtimeUp), and whether ${WORKTREE} exists. Blockers: unreachable host, repo missing, nvidia Docker runtime missing, worktree already present.
7. Record startedAt.
ok=false when any blocker exists.`,
  { label: 'preflight', phase: 'Preflight', schema: PREFLIGHT_SCHEMA },
)

if (!preflight) return result('aborted', { reason: 'preflight agent returned nothing' })
ctx.preflight = preflight
if (!preflight.ok || preflight.blockers.length) return result('waiting', { reason: 'preflight blockers', blockers: preflight.blockers })

const accountable = preflight.accountableLinks.map(slugOf).filter(Boolean)
const backup = preflight.backupLinks.map(slugOf).filter(Boolean)
const isAccountable = accountable.includes(DISPATCHED_BY)
const isBackup = backup.includes(DISPATCHED_BY)
if (!isAccountable && !isBackup) return result('refused', { reason: `dispatchedBy=${DISPATCHED_BY} is not in Maintain parsehawk release's accountable_actors or backup_accountable_actors (${[...accountable, ...backup].join(', ')})` })
if (!isAccountable && !(COVER_FOR && accountable.includes(COVER_FOR))) return result('refused', { reason: `dispatchedBy=${DISPATCHED_BY} is a backup Accountable; pass coverFor with the absent Accountable person's slug (${accountable.join(', ')})` })
const dispatcherGithub = preflight.actorGithub[DISPATCHED_BY]
if (!dispatcherGithub || dispatcherGithub !== preflight.ghLogin) return result('refused', { reason: `the authenticated GitHub login (${preflight.ghLogin}) is not ${DISPATCHED_BY}'s github:username identity (${dispatcherGithub || 'none recorded'})` })
if (GPU_HOST_LOCATION && preflight.gpuHostLocationExists === false) return result('waiting', { reason: `${GPU_HOST_LOCATION} does not exist in ${COS}; bind the Linux NVIDIA host as a SystemLocation or drop the argument` })
const wallDate = String(preflight.startedAt || '').slice(0, 10)
const dayDiff = dayNumber(wallDate) === null ? null : Math.abs(dayNumber(wallDate) - TODAY)
if (dayDiff === null || dayDiff > 1) return result('refused', { reason: `args.date ${DATE} does not match the wall clock (${wallDate || 'unknown'})` })

// Exactly one sweep at a time: continue an open sweep PR, else start fresh.
const openPr = preflight.openSweepPr
const strayBranches = preflight.sweepBranches.filter(b => !openPr || !b.endsWith(openPr.headBranch))
if (!openPr && strayBranches.length) return result('waiting', { reason: `sweep branch(es) without an open PR exist: ${strayBranches.join(', ')}; delete them or open their PR by hand before the next run` })
const workBranch = openPr ? openPr.headBranch : BRANCH
log(`preflight ok: main=${preflight.mainSha.slice(0, 7)}, dispatcher ${DISPATCHED_BY} (${preflight.ghLogin})${COVER_FOR ? ` covering ${COVER_FOR}` : ''}, GPU host ${GPU_HOST}: ${preflight.gpu.gpuName || 'unknown GPU'} ${preflight.gpu.vram || ''}, runtime ${preflight.gpu.runtimeUp ? 'up' : 'down'}${openPr ? `, continuing open PR #${openPr.number} (${openPr.headBranch})` : ''}${DRY_RUN ? ' (DRY RUN)' : ''}`)

// ---------------------------------------------------------------------------
phase('Review')
// ---------------------------------------------------------------------------

const ALERTS_SCHEMA = {
  type: 'object',
  properties: {
    alerts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          number: { type: 'number' },
          ghsa: { type: 'string' },
          package: { type: 'string' },
          ecosystem: { type: 'string', enum: ['python', 'npm', 'other'] },
          severity: { type: 'string' },
          vulnerableRange: { type: 'string' },
          firstPatched: { type: ['string', 'null'] },
          scope: { type: 'string', enum: ['runtime', 'development', 'unknown'] },
          manifest: { type: 'string' },
          createdAt: { type: 'string' },
          summary: { type: 'string' },
        },
        required: ['number', 'ghsa', 'package', 'ecosystem', 'severity', 'vulnerableRange', 'firstPatched', 'scope', 'manifest', 'createdAt', 'summary'],
      },
    },
    fetchedAt: { type: 'string' },
  },
  required: ['alerts', 'fetchedAt'],
}

const alertsResult = await agent(
  `${COMMON}

Task: the review step of the Prepare parsehawk release maintenance Activity (read ${ACT}/prepare-parsehawk-release-maintenance.md), limited to Dependabot. Read-only.
Fetch every open Dependabot alert: \`timeout -k 30 300 gh api "repos/${REPO}/dependabot/alerts?state=open&per_page=100"\` and follow pagination (the Link header, or --paginate). One entry per alert: number, ghsa_id, dependency.package.name, ecosystem (pip -> python, npm -> npm, anything else -> other), security_advisory.severity, security_vulnerability.vulnerable_version_range, first_patched_version.identifier (null when none), dependency.scope (runtime, development, or unknown), dependency.manifest_path, created_at date, and the advisory summary in one line. Do not triage.`,
  { label: 'dependabot-alerts', phase: 'Review', schema: ALERTS_SCHEMA, effort: 'low' },
)
if (!alertsResult) return result('aborted', { reason: 'alerts agent returned nothing' })
const alerts = alertsResult.alerts
ctx.alerts = alerts.map(x => ({ number: x.number, ghsa: x.ghsa, package: x.package, ecosystem: x.ecosystem, severity: x.severity }))
if (!alerts.length) return result('nothing-to-do', { reason: 'no open Dependabot alerts', outcome: null })

const known = new Set(openPr ? openPr.alertNumbers : [])
const newAlerts = alerts.filter(x => !known.has(x.number))
if (openPr && !newAlerts.length) return result('pr-still-open', { reason: `PR #${openPr.number} already covers every open alert; nothing new since it was opened. Review and merge it.`, pr: { number: openPr.number, url: openPr.url } })
log(`review: ${alerts.length} open alert(s), ${newAlerts.length} not yet on a sweep branch`)

const TRIAGE_SCHEMA = {
  type: 'object',
  properties: {
    applicable: { type: 'boolean' },
    reachable: { type: 'string', enum: ['runtime', 'dev', 'build', 'unknown', 'not-applicable'] },
    action: { type: 'string', enum: ['patch', 'ignore', 'no-fix'] },
    strategy: { type: 'string' },
    target: { type: 'string' },
    majorBump: { type: 'boolean' },
    rationale: { type: 'string' },
  },
  required: ['applicable', 'reachable', 'action', 'majorBump', 'rationale'],
}
const triagePrompt = (x) => `${COMMON}

Task: triage exactly one Dependabot alert, applying ${COS}/graph/policies/software-maintenance.md (known vulnerabilities patched within one week of awareness; record awareness, affected versions, remediation, verification). Read-only.
Alert: ${JSON.stringify(x)}
Decide: does it apply to this repository as built (check uv.lock, pyproject.toml, pnpm-lock.yaml, pnpm-workspace.yaml overrides, apps/web/package.json, apps/docs/package.json)? How is it reached (runtime image, dev tooling, docs build, CI)? Fix strategy: python "floor" (raise the floor in pyproject.toml, then uv lock) when we depend on the package directly, else "lock-upgrade" (uv lock --upgrade-package); npm "override" (pnpm-workspace.yaml overrides block with the GHSA id in its comment, the established pattern here) or "bump-direct" for a direct dependency. target = the exact version or range that satisfies first_patched_version while staying on the major its dependents declare; majorBump=true when no such range exists. action=no-fix when firstPatched is null or no compatible release exists; action=ignore only with a concrete reason (not applicable to how we build, already fixed on main).`

let triaged = await pipeline(newAlerts, (x) => agent(triagePrompt(x), { label: `triage:${x.package}:${x.number}`, phase: 'Review', schema: TRIAGE_SCHEMA, effort: 'low' }).then(t => ({ alert: x, triage: t })))
const retryIdx = newAlerts.map((x, i) => (!triaged[i] || !triaged[i].triage ? i : -1)).filter(i => i >= 0)
if (retryIdx.length) {
  log(`triage: retrying ${retryIdx.length} alert(s) once`)
  const retried = await parallel(retryIdx.map(i => () => agent(triagePrompt(newAlerts[i]), { label: `triage-retry:${newAlerts[i].package}`, phase: 'Review', schema: TRIAGE_SCHEMA, effort: 'low' })))
  retryIdx.forEach((i, k) => { triaged[i] = { alert: newAlerts[i], triage: retried[k] || null } })
}
const untriaged = newAlerts.filter((x, i) => !triaged[i] || !triaged[i].triage)
const triage = triaged.filter(t => t && t.triage)
if (untriaged.length) return result('waiting', { reason: `${untriaged.length} alert(s) could not be triaged after a retry; nothing was patched`, untriaged: untriaged.map(x => x.number) })

for (const t of triage) {
  const aw = dayNumber(t.alert.createdAt) ?? TODAY
  t.awarenessDate = isoFromDayNumber(aw)
  t.deadline = isoFromDayNumber(aw + POLICY_DAYS)
  t.overdue = TODAY > aw + POLICY_DAYS
  t.group = t.alert.ecosystem
  if (t.triage.action === 'patch' && t.triage.majorBump && !ALLOW_MAJOR) {
    t.triage.action = 'no-fix'
    t.triage.rationale = `a major version bump needs an explicit allowMajor dispatch; ${t.triage.rationale}`
  }
  if (t.triage.action === 'patch' && !['python', 'npm'].includes(t.group)) {
    t.triage.action = 'no-fix'
    t.triage.rationale = `no patch mechanism for ecosystem ${t.alert.ecosystem}; ${t.triage.rationale}`
  }
}
const toPatch = triage.filter(t => t.triage.action === 'patch')
const noFix = triage.filter(t => t.triage.action === 'no-fix')
const ignored = triage.filter(t => t.triage.action === 'ignore')
const overdue = triage.filter(t => t.overdue && t.triage.action !== 'ignore')
Object.assign(ctx, { triage: triage.map(t => ({ alert: t.alert.number, ghsa: t.alert.ghsa, package: t.alert.package, ecosystem: t.alert.ecosystem, severity: t.alert.severity, action: t.triage.action, target: t.triage.target || null, majorBump: t.triage.majorBump, awarenessDate: t.awarenessDate, deadline: t.deadline, overdue: t.overdue, rationale: t.triage.rationale })), overdueCount: overdue.length })
log(`triage: ${toPatch.length} to patch, ${noFix.length} without a compatible fix, ${ignored.length} ignored; ${overdue.length} past the ${POLICY_DAYS}-day deadline`)
if (!toPatch.length) return result('nothing-to-patch', { reason: 'no new alert has a compatible fix; the unresolved ones are listed for the accountable person', outcome: null })

// Standing case record on GitHub, resolved only now that there is work.
let issueNumber = ISSUE
let issueUrl = null
if (!DRY_RUN) {
  const CASE_SCHEMA = { type: 'object', properties: { issueNumber: { type: 'number' }, issueUrl: { type: 'string' }, created: { type: 'boolean' } }, required: ['issueNumber', 'issueUrl', 'created'] }
  const rec = await agent(
    `${COMMON}

Task: resolve the standing GitHub Issue that Dependabot sweep pull requests reference (the Enforce Issue Reference check requires one). ${ISSUE ? `Use Issue #${ISSUE}: confirm it is open and return its number and URL.` : `Search open issues whose title contains "Dependabot" (\`gh issue list --repo ${REPO} --state open --search "Dependabot" --json number,title,url\`) and use the lowest-numbered match. If none exists, create one titled "chore(deps): Dependabot alert sweeps" whose body says it is the standing reference for the daily dependency sweep pull requests under the Company OS Workflow Maintain parsehawk release, dispatched by ${DISPATCHED_BY} and performed by Claude Code agents under that person's authorization.`} Return issueNumber, issueUrl, and whether it was created.`,
    { label: 'case-record', phase: 'Review', schema: CASE_SCHEMA, effort: 'low' },
  )
  if (!rec || !(Number.isInteger(rec.issueNumber) && rec.issueNumber > 0)) return result('waiting', { reason: 'no GitHub Issue could be resolved for the PR reference' })
  issueNumber = rec.issueNumber
  issueUrl = rec.issueUrl
  ctx.issue = { number: issueNumber, url: issueUrl }
}

// ---------------------------------------------------------------------------
phase('Patch')
// ---------------------------------------------------------------------------

const BRANCH_SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' }, headSha: { type: 'string' }, notes: { type: 'string' } }, required: ['ok', 'headSha'] }
const branchStep = await agent(
  `${COMMON}

Task: prepare the sweep branch. \`git status --porcelain --untracked-files=no\` must be empty. ${openPr ? `Continue the open PR's branch: \`git fetch origin ${workBranch} && git switch ${workBranch} && git reset --hard origin/${workBranch}\` (its commits ${openPr.headSha.slice(0, 7)} are already public), then \`git rebase origin/main\`; stop with ok=false on conflicts.` : `Create ${workBranch} from main ${preflight.mainSha} (git switch -c).`} Return ok and the branch head SHA. Do not push.`,
  { label: 'branch', phase: 'Patch', schema: BRANCH_SCHEMA, effort: 'low' },
)
if (!branchStep || !branchStep.ok) return result('waiting', { reason: `could not prepare ${workBranch}: ${(branchStep && branchStep.notes) || 'agent returned nothing'}` })

const PATCH_SCHEMA = {
  type: 'object',
  properties: {
    commits: { type: 'array', items: { type: 'object', properties: { sha: { type: 'string' }, subject: { type: 'string' } }, required: ['sha', 'subject'] } },
    changedFiles: { type: 'array', items: { type: 'string' } },
    patched: { type: 'array', items: { type: 'number' } },
    bumps: { type: 'array', items: { type: 'object', properties: { package: { type: 'string' }, from: { type: 'string' }, to: { type: 'string' } }, required: ['package', 'from', 'to'] } },
    unresolved: { type: 'array', items: { type: 'object', properties: { alert: { type: 'number' }, why: { type: 'string' } }, required: ['alert', 'why'] } },
    notes: { type: 'string' },
  },
  required: ['commits', 'changedFiles', 'patched', 'bumps', 'unresolved'],
}

// Sequential on purpose: every group edits the same checkout and branch.
const groups = ['python', 'npm'].map(g => ({ group: g, items: toPatch.filter(t => t.group === g) })).filter(g => g.items.length)
const patchResults = []
for (const g of groups) {
  const res = await agent(
    `${COMMON}

Task: implement the ${g.group} patches of the Maintain parsehawk release Activity (read ${ACT}/maintain-parsehawk-release.md) on the existing branch ${workBranch}; do not rebase or amend earlier commits.
Alerts to fix: ${JSON.stringify(g.items.map(t => ({ alert: t.alert, strategy: t.triage.strategy, target: t.triage.target, rationale: t.triage.rationale, awarenessDate: t.awarenessDate, deadline: t.deadline, overdue: t.overdue })))}
Rules:
- Follow the repository's established mechanisms. Python: raise the floor in pyproject.toml when we depend on the package directly, otherwise \`uv lock --upgrade-package <name>\`; always leave uv.lock consistent (\`uv lock\` then \`uv sync --frozen --all-extras\`). npm: prefer the pnpm-workspace.yaml overrides block with the GHSA ids in its comment, exactly like the existing entries; bump apps/*/package.json only for direct dependencies; then \`pnpm install\` (not frozen) and check that the lockfile diff touches only the intended packages.
- Stay on the declared major${ALLOW_MAJOR ? ' unless the triage target requires a major bump, which allowMajor permits' : ''}; report every version move in bumps (package, from, to).
- One conventional commit per package or tightly related set, subject "fix(deps): ...", body explaining why this shape is right (GHSA id and alert number, how the package reaches us, why the range stays on its major, awareness date and deadline, what was tested). Match the tone of \`git log -8\`. Reference the alert as "alert #<number>" in the body.
- Run the fast local gates before each commit: \`just format-check lint typecheck test-unit\` for Python changes, \`just web-typecheck web-test\` for npm changes.
- Do not touch unrelated files. Do not push.
Return the commits, changed files, which alert numbers are patched, the version bumps, and which remain unresolved with the reason.`,
    { label: `patch:${g.group}`, phase: 'Patch', schema: PATCH_SCHEMA },
  )
  patchResults.push({ group: g.group, result: res || { commits: [], changedFiles: [], patched: [], bumps: [], unresolved: g.items.map(t => ({ alert: t.alert.number, why: 'patch agent returned nothing' })), notes: '' } })
}
ctx.patchResults = patchResults
const commits = patchResults.flatMap(p => p.result.commits)
if (!commits.length) return result('waiting', { reason: `no patch commit was produced; ${workBranch} is checked out locally`, branch: workBranch })
const majorOf = (v) => (/(\d+)/.exec(String(v || '')) || [])[1]
const crossedMajor = (b) => majorOf(b.from) && majorOf(b.to) && majorOf(b.from) !== majorOf(b.to)
// The gate guards the packages this run set out to move (the triage targets):
// crossing a major on one of those means the patch agent left the plan. A
// transitive dependency that a target's own new release drags across a major
// (svgo 4.1 requiring css-select 6) is upstream's choice and cannot be avoided
// on the target's declared range; it is still reported in bumps and covered
// by the Verify phase and CI rather than blocking here.
const targetPackages = new Set(toPatch.map(t => String(t.alert.package || '').toLowerCase()))
const bumpPackage = (b) => String(b.package || '').trim().split(/[\s,(]/)[0].toLowerCase()
const majorBumps = patchResults.flatMap(p => p.result.bumps).filter(crossedMajor)
const unexpectedMajors = majorBumps.filter(b => targetPackages.has(bumpPackage(b)))
const transitiveMajors = majorBumps.filter(b => !targetPackages.has(bumpPackage(b)))
if (unexpectedMajors.length && !ALLOW_MAJOR) return result('waiting', { reason: 'a patch crossed a major version on a triage target without allowMajor; branch kept locally for a person to inspect', unexpectedMajors, transitiveMajors, branch: workBranch })
if (transitiveMajors.length) log(`patch: ${transitiveMajors.length} transitive dependenc${transitiveMajors.length === 1 ? 'y' : 'ies'} crossed a major inside a target's release (${transitiveMajors.map(b => `${b.package} ${b.from} -> ${b.to}`).join(', ')}); left to Verify and CI`)
log(`patch: ${commits.length} commit(s) on ${workBranch}`)

// ---------------------------------------------------------------------------
phase('Verify')
// ---------------------------------------------------------------------------

const REBASE_SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' }, headSha: { type: 'string' }, baseSha: { type: 'string' }, notes: { type: 'string' } }, required: ['ok', 'headSha', 'baseSha'] }
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    ran: { type: 'boolean' },
    passed: { type: 'boolean' },
    environment: { type: 'string' },
    sha: { type: 'string' },
    gpu: { type: 'string' },
    commands: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    failures: { type: 'array', items: { type: 'string' } },
    cleanupOk: { type: ['boolean', 'null'] },
    logPath: { type: 'string' },
    startedAt: { type: 'string' },
    endedAt: { type: 'string' },
  },
  required: ['ran', 'passed', 'environment', 'sha', 'commands', 'summary', 'failures', 'cleanupOk'],
}

const rebaseOntoMain = () => agent(`${COMMON}

Task: \`git fetch origin && git rebase origin/main\` on ${workBranch} (stop and report ok=false on conflicts; do not resolve them). Return the new head SHA and \`git rev-parse origin/main\` as baseSha. Do not push to origin.`, { label: 'rebase', phase: 'Verify', schema: REBASE_SCHEMA, effort: 'low' })

const verifyBoth = async (headSha) => {
  const [l, g] = await parallel([
    () => agent(
      `${COMMON}

Task: full local verification of branch ${workBranch} at ${headSha} on this machine (Maintain parsehawk release: "run tests on supported target environments"). Confirm \`git rev-parse HEAD\` equals ${headSha} and return it as sha. Run \`just check\` (format, lint, typecheck, unit and integration tests with the 100% coverage gate, OpenAPI and reference checks, docs build, web typecheck, tests and build, licenses). Save the complete output under $TMPDIR/parsehawk-dependabot-${DATE}-local.log. ${MAC_E2E ? 'Then, because macE2E=true, run `parsehawk restart` and `just e2e` on this Mac (vLLM Metal) and include that result.' : 'Do NOT run e2e here (macE2E=false); state explicitly that macOS Apple Silicon e2e was not run.'} Report passed=true only when every recipe passed. Do not modify files; if a check fails, report it. cleanupOk = null.`,
      { label: 'verify:local', phase: 'Verify', schema: VERIFY_SCHEMA },
    ),
    () => agent(
      `${COMMON}

Task: GPU verification on the Linux NVIDIA VM ${GPU_HOST} (primary checkout ${GPU_REPO}), which the Software maintenance policy requires before a release change. Never modify the host's primary checkout.
1. Transfer the commits git-natively, without origin: \`git push --force ssh://${GPU_HOST}/${GPU_REPO} ${headSha}:refs/heads/${workBranch}\`. If the host refuses a push into its non-bare repository, fall back to \`git bundle create "$TMPDIR/sweep.bundle" origin/main..${headSha} && scp "$TMPDIR/sweep.bundle" ${GPU_HOST}:/tmp/sweep.bundle\` and on the host \`git -C ${GPU_REPO} fetch /tmp/sweep.bundle ${workBranch}:${workBranch}\`.
2. On the host: \`git -C ${GPU_REPO} worktree add ${WORKTREE} ${workBranch}\`, then inside ${WORKTREE}: \`git rev-parse HEAD\` (must equal ${headSha}; return it as sha), \`nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader\` (return the GPU line as gpu), \`uv sync --frozen --all-extras\`, \`pnpm install --frozen-lockfile\`.
3. Model runtime: \`curl -s -m 5 http://127.0.0.1:8080/v1/models\`. ${START_RUNTIME ? `If it does not answer, start it from the primary checkout (\`cd ${GPU_REPO} && parsehawk start\`), wait until \`parsehawk status\` and \`parsehawk doctor\` report the runtime healthy (the first start may download model weights; allow up to 20 minutes), and leave it running afterwards.` : 'If it does not answer, stop with ran=false (startRuntime is off).'} The end-to-end harness reuses this running runtime.
4. Inside ${WORKTREE}: \`just test\` (unit and integration on Linux) and \`just e2e\` (the GPU-dependent suite; runtime-dependent job tests must PASS, not be skipped). Use \`timeout -k 60 2400\` around each.
5. Always, even after a failure: \`git -C ${GPU_REPO} worktree remove --force ${WORKTREE} && git -C ${GPU_REPO} branch -D ${workBranch}\`; report cleanupOk.
Copy the logs to $TMPDIR/parsehawk-dependabot-${DATE}-gpu.log locally. Report host name, GPU, verified SHA, each command's exit status, the pytest summary lines, and passed=true only when both suites passed.`,
      { label: `verify:gpu:${GPU_HOST}`, phase: 'Verify', schema: VERIFY_SCHEMA },
    ),
  ])
  return {
    local: l || { ran: false, passed: false, environment: 'macOS local', sha: '', commands: [], summary: 'agent returned nothing', failures: ['no result'], cleanupOk: null },
    gpu: g || { ran: false, passed: false, environment: `Linux NVIDIA ${GPU_HOST}`, sha: '', commands: [], summary: 'agent returned nothing', failures: ['no result'], cleanupOk: false },
  }
}
const verifiedHead = (v, sha) => v.local.passed && v.gpu.passed && v.local.sha === sha && v.gpu.sha === sha

let rebase = await rebaseOntoMain()
if (!rebase || !rebase.ok) return result('waiting', { reason: `rebase onto origin/main did not complete: ${(rebase && rebase.notes) || 'agent returned nothing'}; branch kept locally`, branch: workBranch })
let verification = await verifyBoth(rebase.headSha)
ctx.verification = verification
log(`verify: local ${verification.local.passed ? 'passed' : 'FAILED'}, GPU ${verification.gpu.passed ? 'passed' : 'FAILED'}${verification.gpu.cleanupOk === false ? ' (worktree cleanup FAILED)' : ''}`)
if (!verifiedHead(verification, rebase.headSha)) {
  return result('waiting', { reason: `verification did not pass on head ${rebase.headSha} (local sha ${verification.local.sha || '?'}, GPU sha ${verification.gpu.sha || '?'}); ${workBranch} is kept locally${openPr ? ` and PR #${openPr.number} is unchanged` : ' and nothing was pushed to origin'}`, outcome: null, branch: workBranch })
}

// ---------------------------------------------------------------------------
phase('Deliver')
// ---------------------------------------------------------------------------

if (DRY_RUN) return result('dry-run-complete', { reason: 'no push to origin, PR, or comment in a dry run', outcome: null, branch: workBranch, verifiedHead: rebase.headSha })

const PR_SCHEMA = {
  type: 'object',
  properties: {
    prNumber: { type: 'number' },
    prUrl: { type: 'string' },
    headSha: { type: 'string' },
    baseSha: { type: 'string' },
    checksPassed: { type: 'boolean' },
    checks: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, state: { type: 'string' } }, required: ['name', 'state'] } },
    notes: { type: 'string' },
  },
  required: ['prNumber', 'prUrl', 'headSha', 'baseSha', 'checksPassed', 'checks'],
}
const patchedAlerts = patchResults.flatMap(p => p.result.patched)
const unresolvedAll = [...noFix.map(t => ({ alert: t.alert.number, ghsa: t.alert.ghsa, package: t.alert.package, why: t.triage.rationale })), ...patchResults.flatMap(p => p.result.unresolved)]
const rollbackText = `Rollback: revert this pull request's commits on main (they land as rebased commits, so use their SHAs on main: git revert <first>^..<last>) through a new pull request; the previously published image ghcr.io/${REPO}:sha-${preflight.mainSha.slice(0, 7)} remains available if its publish run succeeded.`

let pr = null
for (let attempt = 1; attempt <= 2 && !pr; attempt += 1) {
  const candidate = await agent(
    `${COMMON}

Task: ${openPr ? `update the open pull request #${openPr.number} for ${workBranch}` : `open the pull request for ${workBranch}`} at head ${rebase.headSha} and obtain full CI evidence. Steps:
1. \`git fetch origin\`; if \`git rev-parse origin/main\` differs from ${rebase.baseSha}, return prNumber 0, baseSha = the new origin/main SHA, notes "main moved", WITHOUT pushing (the script rebases and verifies again).
2. \`git push -u origin ${workBranch}${openPr ? ' --force-with-lease' : ''}\`. ${openPr ? `Then \`gh pr edit ${openPr.number} --body-file <file>\`.` : `Then \`gh pr create --repo ${REPO} --base main --head ${workBranch} --title "chore(deps): patch Dependabot alerts (${DATE})" --body-file <file>\`.`} The body must contain: "Refs #${issueNumber}" (never "Closes"); a table of every patched alert as "alert #N" with GHSA id, package, ecosystem, from -> to, scope, awareness date, deadline, overdue yes/no${openPr ? ', keeping the rows of alerts patched in earlier runs' : ''}; a table of unresolved alerts with the reason; verification evidence: macOS local \`just check\` at ${verification.local.sha}${MAC_E2E ? ' and macOS e2e' : ' (macOS Apple Silicon e2e NOT run)'}, Linux NVIDIA unit, integration and e2e on ${GPU_HOST} (${verification.gpu.gpu || preflight.gpu.gpuName || 'GPU'}) at ${verification.gpu.sha} with the pytest summary lines; "${rollbackText}"; the line "Dispatched by ${DISPATCHED_BY}${COVER_FOR ? ` covering ${COVER_FOR}` : ''} on ${DATE} under GitHub login ${preflight.ghLogin} (Company OS ${preflight.companyOsRevision}); performed by Claude Code agents under that person's authorization; a person reviews and merges." Do not paste logs.
3. Pull-request CI is path-filtered, so trigger the full suites explicitly: \`gh workflow run ci-test.yaml --repo ${REPO} --ref ${workBranch}\` and \`gh workflow run ci-checks.yaml --repo ${REPO} --ref ${workBranch}\`, then \`timeout 2700 gh run watch <id> --exit-status\` for each (find the ids with \`gh run list --workflow <name> --branch ${workBranch} --limit 1\`), plus \`timeout 2700 gh pr checks <n> --watch\`. checksPassed=true only when both dispatched runs concluded success and every pull-request check is success or skipped.
Return the PR number, URL, head SHA (must equal ${rebase.headSha}), baseSha, and every check with its state.
Patched alerts: ${JSON.stringify(patchedAlerts)}; unresolved: ${JSON.stringify(unresolvedAll)}; bumps: ${JSON.stringify(patchResults.flatMap(p => p.result.bumps))}; verification: ${JSON.stringify({ local: { summary: verification.local.summary, commands: verification.local.commands }, gpu: { summary: verification.gpu.summary, gpu: verification.gpu.gpu, commands: verification.gpu.commands } })}`,
    { label: `pull-request:${attempt}`, phase: 'Deliver', schema: PR_SCHEMA, effort: 'low' },
  )
  if (!candidate) return result('waiting', { reason: 'PR agent returned nothing; check whether the branch was pushed', branch: workBranch })
  if (candidate.prNumber > 0) { pr = candidate; break }
  if (attempt === 2) return result('waiting', { reason: 'origin/main kept moving; re-run the workflow', branch: workBranch })
  log('main moved since verification; rebasing and verifying once more')
  rebase = await rebaseOntoMain()
  if (!rebase || !rebase.ok) return result('waiting', { reason: 'rebase after main moved did not complete', branch: workBranch })
  verification = await verifyBoth(rebase.headSha)
  ctx.verification = verification
  if (!verifiedHead(verification, rebase.headSha)) return result('waiting', { reason: `re-verification failed on ${rebase.headSha}`, branch: workBranch })
}
ctx.pr = pr
if (pr.headSha !== rebase.headSha) return result('waiting', { reason: `PR head ${pr.headSha} is not the verified head ${rebase.headSha}`, outcome: null })
log(`PR #${pr.prNumber}: checks ${pr.checksPassed ? 'green' : 'NOT green'}`)

const evidenceLine = `${patchedAlerts.length} alert(s) patched, ${unresolvedAll.length} unresolved (list them by alert number and reason); ${overdue.length} alert(s) were already past the ${POLICY_DAYS}-day policy deadline at awareness`

if (!MERGE || !pr.checksPassed) {
  const why = !pr.checksPassed ? 'CI is not green' : 'merge was not authorized in this run'
  ctx.note = await agent(
    `${COMMON}

Task: post a short status comment on PR #${pr.prNumber} (gh pr comment): the sweep run of ${DATE} ${pr.checksPassed ? 'passed local checks, the Linux NVIDIA end-to-end suite, and full CI' : 'passed local checks and the Linux NVIDIA end-to-end suite, but CI is not green'}; ${evidenceLine}; the run leaves the pull request open because ${why}; next human action: ${pr.checksPassed ? `review the diff and evidence, then merge with \`gh pr merge ${pr.prNumber} --rebase --delete-branch --match-head-commit ${pr.headSha}\`` : 'inspect the failing check, fix on the branch, and let the next run continue it'}, then record the Maintain parsehawk release outcome on Issue #${issueNumber}. No logs, no secrets.`,
    { label: 'pr-status', phase: 'Deliver', effort: 'low' },
  )
  return result('pr-open', {
    reason: `pull request open: ${why}`,
    outcome: null,
    patchedAlerts,
    unresolved: unresolvedAll,
    nextHumanStep: pr.checksPassed ? `review PR #${pr.prNumber} and merge it with gh pr merge --rebase --delete-branch --match-head-commit ${pr.headSha}` : `inspect the failing checks on PR #${pr.prNumber}`,
  })
}

// Merge: authorized by args.merge, gated on green CI and the verified head.
const MERGE_SCHEMA = {
  type: 'object',
  properties: { merged: { type: 'boolean' }, mainSha: { type: 'string' }, mergedCommits: { type: 'array', items: { type: 'string' } }, publishRun: { type: 'string' }, publishConclusion: { type: 'string' }, imageTag: { type: 'string' }, imageDigest: { type: 'string' }, notes: { type: 'string' }, endedAt: { type: 'string' } },
  required: ['merged', 'notes', 'endedAt'],
}
const merged = await agent(
  `${COMMON}

Task: merge PR #${pr.prNumber} and read back (Maintain parsehawk release Activity; read ${ACT}/maintain-parsehawk-release.md). Authorization: the dispatcher ${DISPATCHED_BY} passed merge=true for this run; local checks at ${verification.local.sha}, the Linux NVIDIA suite on ${GPU_HOST} at ${verification.gpu.sha}, and full CI passed on head ${pr.headSha}.
1. \`gh pr merge ${pr.prNumber} --repo ${REPO} --rebase --delete-branch --match-head-commit ${pr.headSha}\`; the server refuses if the head moved, in which case return merged=false and say so.
2. \`git fetch origin --prune && git checkout main && git pull --ff-only && git branch -D ${workBranch}\` (AGENTS.md post-merge steps). Return the main SHA and the merged commit SHAs as they landed on main.
3. Publish readback: \`gh run list --repo ${REPO} --workflow publish-image --branch main --limit 1 --json databaseId,url,status,conclusion\`, then \`timeout 1500 gh run watch <id>\`; return the run URL and conclusion. When it succeeded, return imageTag = sha-<first 7 of main SHA> and, if docker is available, its digest from \`docker buildx imagetools inspect ghcr.io/${REPO}:<imageTag>\`.
4. Post one comment on the merged PR (gh pr comment): merged by the sweep run of ${DATE} under ${DISPATCHED_BY}'s authorization; ${evidenceLine}; main SHA, merged commits, publish-image result and image tag or the publish failure; "${rollbackText}"; and the sentence "No version tag or GitHub Release was created; customer installations are not patched by this merge (Software maintenance Policy). The Maintain parsehawk release outcome is recorded by the accountable person on Issue #${issueNumber}." No logs, no secrets.`,
  { label: 'merge-readback', phase: 'Deliver', schema: MERGE_SCHEMA },
)
ctx.merge = merged
const didMerge = !!(merged && merged.merged)
const published = didMerge && merged.publishConclusion === 'success'
return result(didMerge ? 'merged' : 'pr-open', {
  reason: !didMerge ? `merge did not complete: ${(merged && merged.notes) || 'merge agent returned nothing'}` : published ? 'merged to main and image published' : 'merged to main but publish-image did not succeed; the :main image is stale relative to main',
  outcome: null,
  patchedAlerts,
  unresolved: unresolvedAll,
  nextHumanStep: didMerge ? (published ? `record the Maintain parsehawk release outcome on Issue #${issueNumber}; decide separately on a version tag or release` : 'inspect the publish-image run on main, then record the outcome') : `inspect PR #${pr.prNumber} and merge by hand if appropriate`,
})
