import type { Project, StarterFile } from '@/types/api'

export type AuditStatus = 'pass' | 'warning' | 'blocked'

export interface AuditFinding {
  id: string
  category: string
  title: string
  status: AuditStatus
  detail: string
  action?: string
  step?: string
  file?: string
}

const byPath = (files: StarterFile[]) => new Map(files.map((file) => [file.path, file.content]))

export function runReproducibilityAudit(project: Project, files: StarterFile[]): AuditFinding[] {
  const content = byPath(files)
  const methods = project.steps.methods.chosen
  const experiments = project.steps.experiments.items
  const mainExperiments = experiments.filter((item) => item.kind === 'main')
  const ablations = experiments.filter((item) => item.kind === 'ablation')
  const findings: AuditFinding[] = []

  findings.push({
    id: 'question', category: 'Research design', title: 'Research question',
    status: project.question.trim() ? 'pass' : 'blocked',
    detail: project.question.trim() ? `Saved question: “${project.question.trim()}”` : 'Write and save a focused research question before treating this as a runnable study.',
    action: 'Edit research question', step: 'questions',
  })
  findings.push({
    id: 'hypothesis', category: 'Research design', title: 'Testable hypothesis',
    status: project.hypothesis.trim() ? 'pass' : 'blocked',
    detail: project.hypothesis.trim() ? `Saved hypothesis: “${project.hypothesis.trim()}”` : 'State what outcome you expect and how you will measure it.',
    action: 'Add hypothesis', step: 'gaps',
  })

  for (const [id, key, label, step] of [
    ['dataset', 'datasets', 'Dataset', 'methods'],
    ['baseline', 'baselines', 'Comparison baseline', 'methods'],
    ['metric', 'metrics', 'Evaluation metric', 'methods'],
  ] as const) {
    const selected = methods[key]
    findings.push({
      id, category: 'Research design', title: label,
      status: selected.length ? 'pass' : 'warning',
      detail: selected.length ? `Selected: ${selected.join(', ')}.` : `No ${label.toLowerCase()} selected yet. Choose one so the experiment can be interpreted against a defined reference.`,
      action: 'Review methods', step,
    })
  }

  findings.push({
    id: 'main-experiment', category: 'Research design', title: 'Primary experiment',
    status: mainExperiments.length ? 'pass' : 'blocked',
    detail: mainExperiments.length ? `${mainExperiments.length} primary experiment(s) planned: ${mainExperiments.map((item) => item.title).join('; ')}.` : 'Plan a primary comparison that can answer the research question.',
    action: 'Plan experiments', step: 'experiments',
  })
  findings.push({
    id: 'ablation', category: 'Research design', title: 'Ablation or mechanism check',
    status: ablations.length ? 'pass' : 'warning',
    detail: ablations.length ? `${ablations.length} ablation(s) planned: ${ablations.map((item) => item.title).join('; ')}.` : 'No ablation is planned. Add one if you need to show which part of the approach causes a result.',
    action: 'Add an ablation', step: 'experiments',
  })

  let config: Record<string, unknown> | null = null
  const rawConfig = content.get('config.json')
  if (rawConfig) {
    try {
      const parsed: unknown = JSON.parse(rawConfig)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) config = parsed as Record<string, unknown>
    } catch {
      // A malformed or user-edited configuration is reported as a finding below.
    }
  }
  findings.push({
    id: 'config', category: 'Reproducibility', title: 'Experiment configuration',
    status: config ? 'pass' : 'blocked',
    detail: config ? 'config.json parses as valid JSON.' : 'config.json is missing or invalid JSON; the runner cannot reliably load the experiment settings.',
    action: 'Inspect config.json', file: 'config.json', step: 'code',
  })

  const split = typeof config?.split === 'string' ? config.split : ''
  findings.push({
    id: 'split', category: 'Reproducibility', title: 'Evaluation split',
    status: split && split.toLowerCase() !== 'test' ? 'pass' : split ? 'blocked' : 'warning',
    detail: split ? (split.toLowerCase() === 'test' ? 'The configured split is “test”. Keep test data untouched until the final evaluation.' : `The configuration records “${split}” as its split.`) : 'No evaluation split is recorded in config.json.',
    action: 'Review config.json', file: 'config.json', step: 'code',
  })

  const seeds = Array.isArray(config?.seeds) ? config.seeds : []
  findings.push({
    id: 'seeds', category: 'Reproducibility', title: 'Repeated random seeds',
    status: seeds.length >= 3 ? 'pass' : seeds.length > 0 ? 'warning' : 'blocked',
    detail: seeds.length >= 3 ? `${seeds.length} seeds configured (${seeds.join(', ')}).` : seeds.length ? `Only ${seeds.length} seed(s) configured. Use at least three to expose run-to-run variation.` : 'No seeds are configured; run-to-run variation will not be measured.',
    action: 'Review config.json', file: 'config.json', step: 'code',
  })

  const runner = content.get('run_experiments.py') ?? ''
  const hasSeedLoop = /for\s+seed\s+in\s+seeds\s*:/m.test(runner)
  const writesCsv = /results\.csv/.test(runner)
  findings.push({
    id: 'runner', category: 'Reproducibility', title: 'Repeatable result output',
    status: hasSeedLoop && writesCsv ? 'pass' : 'warning',
    detail: hasSeedLoop && writesCsv ? 'The runner iterates over configured seeds and writes a results.csv artifact.' : 'Could not confirm both a seed loop and results.csv output in the current runner file.',
    action: 'Inspect run_experiments.py', file: 'run_experiments.py', step: 'code',
  })

  const requirements = content.get('requirements.txt')
  const dependencyLines = (requirements ?? '').split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith('#'))
  const pinnedDependencies = dependencyLines.length > 0 && dependencyLines.every((line) => /^[A-Za-z0-9_.-]+(?:\[[^\]]+\])?==\S+(?:\s*;.*)?$/.test(line))
  findings.push({
    id: 'dependencies', category: 'Reproducibility', title: 'Pinned dependencies',
    status: pinnedDependencies ? 'pass' : 'warning',
    detail: pinnedDependencies ? `${dependencyLines.length} dependencies use pinned versions.` : 'Dependencies are not all pinned to exact versions. A lock file or exact pins make environment recreation more reliable.',
    action: 'Pin package versions', file: 'requirements.txt', step: 'code',
  })

  const tests = content.get('test_pipeline.py')
  findings.push({
    id: 'tests', category: 'Execution checks', title: 'Pipeline tests included',
    status: tests && /def\s+test_/m.test(tests) ? 'pass' : 'warning',
    detail: tests && /def\s+test_/m.test(tests) ? 'The starter includes Python tests. This audit checks that the file is present; it does not run the tests.' : 'No test functions were found in test_pipeline.py.',
    action: 'Inspect test_pipeline.py', file: 'test_pipeline.py', step: 'code',
  })

  const importedRuns = (project.steps.experiments.result_analyses ?? []).length + (project.steps.experiments.prediction_analyses ?? []).length
  findings.push({
    id: 'results', category: 'Evidence', title: 'Experiment outputs',
    status: importedRuns ? 'pass' : 'warning',
    detail: importedRuns ? `${importedRuns} imported result analysis record(s) are saved to this project.` : 'No experiment output has been imported yet. Planned experiments and synthetic mechanism stress tests are not completed research results.',
    action: 'Review experiment results', step: 'experiments',
  })

  const drafted = Object.entries(project.steps.code.drafts).filter(([, draft]) => draft.status === 'drafted')
  if (drafted.length) {
    findings.push({
      id: 'generated-draft', category: 'Evidence', title: 'Generated code status', status: 'warning',
      detail: `${drafted.map(([name]) => name).join(', ')} contains model-generated code. It remains unverified until reviewed and run by you.`,
      action: 'Review generated code', step: 'code',
    })
  }

  return findings
}

export function auditMarkdown(project: Project, findings: AuditFinding[], generatedAt = new Date()): string {
  const counts = countAuditStatuses(findings)
  return [
    `# Reproducibility preflight: ${project.title}`,
    '',
    `Generated: ${generatedAt.toISOString()}`,
    '',
    `**${counts.pass} passed · ${counts.warning} needs attention · ${counts.blocked} blocked**`,
    '',
    '## Research question',
    '',
    project.question || '_Not written yet._',
    '',
    '## Hypothesis',
    '',
    project.hypothesis || '_Not written yet._',
    '',
    ...findings.flatMap((finding) => [
      `## ${finding.status === 'pass' ? 'PASS' : finding.status === 'warning' ? 'REVIEW' : 'BLOCKED'} · ${finding.title}`,
      '',
      `**${finding.category}** — ${finding.detail}`,
      ...(finding.file ? ['', `File: \`${finding.file}\``] : []),
      '',
    ]),
    '## Scope',
    '',
    'This is a static preflight of saved project fields and starter files. It does not execute code, verify dataset licenses or correctness, or establish that a research claim is true.',
    '',
  ].join('\n')
}

export function countAuditStatuses(findings: AuditFinding[]) {
  return findings.reduce(
    (counts, finding) => ({ ...counts, [finding.status]: counts[finding.status] + 1 }),
    { pass: 0, warning: 0, blocked: 0 },
  )
}
