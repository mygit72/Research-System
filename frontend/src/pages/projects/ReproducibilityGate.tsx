import { useState } from 'react'
import { AlertTriangle, CheckCircle2, CircleX, Download, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { reportFilename, saveBlob } from '@/lib/reports'
import type { Project, StarterFile } from '@/types/api'
import { auditMarkdown, countAuditStatuses, runReproducibilityAudit, type AuditFinding, type AuditStatus } from './reproducibilityAudit'

const STATUS_LABEL: Record<AuditStatus, string> = { pass: 'Passed', warning: 'Review', blocked: 'Blocked' }
const STATUS_STYLE: Record<AuditStatus, string> = {
  pass: 'text-success',
  warning: 'text-warning',
  blocked: 'text-error',
}
const STATUS_ICON = {
  pass: CheckCircle2,
  warning: AlertTriangle,
  blocked: CircleX,
}

export function ReproducibilityGate({ project, files }: { project: Project; files: StarterFile[] }) {
  const [showAudit, setShowAudit] = useState(false)
  const findings = showAudit ? runReproducibilityAudit(project, files) : []
  const counts = countAuditStatuses(findings)
  const groups = [...new Set(findings.map((finding) => finding.category))]

  return (
    <section aria-labelledby="reproducibility-gate-title" className="rounded-xl border border-border bg-surface p-4 sm:p-5">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
            <ShieldCheck className="size-5" aria-hidden />
          </span>
          <div>
            <p className="text-caption font-medium tracking-wide text-primary uppercase">Research engineering preflight</p>
            <h3 id="reproducibility-gate-title" className="mt-1 text-h3 text-text">Reproducibility Gate</h3>
            <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
              Check whether the research plan and generated runner are ready for a reproducible experiment. Findings come from saved project data and starter files, with a fix for each gap.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {showAudit && (
            <Button
              variant="secondary"
              onClick={() => saveBlob(
                new Blob([auditMarkdown(project, findings)], { type: 'text/markdown;charset=utf-8' }),
                reportFilename(`${project.title} reproducibility audit`, 'md'),
              )}
            >
              <Download className="size-4" aria-hidden /> Export audit
            </Button>
          )}
          <Button onClick={() => setShowAudit((visible) => !visible)}>
            <ShieldCheck className="size-4" aria-hidden /> {showAudit ? 'Hide audit' : 'Run preflight'}
          </Button>
        </div>
      </header>

      {showAudit && (
        <div className="mt-5 space-y-5 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-2" role="status" aria-live="polite">
            <span className="text-small font-semibold text-text">Preflight summary</span>
            <Badge tone="success">{counts.pass} passed</Badge>
            <Badge tone="warning">{counts.warning} to review</Badge>
            {counts.blocked > 0 && <Badge tone="error">{counts.blocked} blocked</Badge>}
          </div>

          {groups.map((category) => (
            <section key={category} aria-label={category}>
              <h4 className="mb-2 text-small font-semibold text-text">{category}</h4>
              <ul className="space-y-2">
                {findings.filter((finding) => finding.category === category).map((finding) => (
                  <FindingRow key={finding.id} finding={finding} projectId={project.id} />
                ))}
              </ul>
            </section>
          ))}

          <p className="rounded-md border border-warning/30 bg-warning/5 p-3 text-caption leading-relaxed text-muted">
            Static checks only: this preflight does not execute code, validate dataset licenses or correctness, or prove a research claim. Run the starter tests and experiments in your environment before reporting results.
          </p>
        </div>
      )}
    </section>
  )
}

function FindingRow({ finding, projectId }: { finding: AuditFinding; projectId: string }) {
  const Icon = STATUS_ICON[finding.status]
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-surface-muted p-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex min-w-0 items-start gap-2">
        <Icon className={`mt-0.5 size-4 shrink-0 ${STATUS_STYLE[finding.status]}`} aria-hidden />
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-small font-medium text-text">
            {finding.title}
            <span className={`text-caption ${STATUS_STYLE[finding.status]}`}>{STATUS_LABEL[finding.status]}</span>
            {finding.file && <code className="rounded bg-surface px-1.5 py-0.5 text-caption text-muted">{finding.file}</code>}
          </p>
          <p className="mt-1 text-small leading-relaxed text-muted">{finding.detail}</p>
        </div>
      </div>
      {finding.action && finding.step && (
        <Link
          to={`/projects/${projectId}?step=${finding.step}`}
          className="shrink-0 self-start text-caption font-medium text-primary hover:underline sm:ml-4"
        >
          {finding.action}
        </Link>
      )}
    </li>
  )
}
