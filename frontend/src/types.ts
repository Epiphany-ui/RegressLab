export interface Metrics {
  n: number
  a: number
  b: number
  c: number
  d: number
  old_accuracy: number | null
  new_accuracy: number | null
  accuracy_drop: number | null
  negative_flip_rate: number | null
  positive_flip_rate: number | null
  old_correct_regression_rate: number | null
  old_macro_f1: number | null
  new_macro_f1: number | null
  per_label_support: Record<string, number>
}

export interface Coverage {
  expected_count: number
  legal_count: number
  missing_count: number
  invalid_count: number
  failed_count: number
  ratio: number | null
}

export interface AnalysisSummary {
  id: string
  name: string
  created_at: string
  fixture_only: boolean
  old_model_name: string
  new_model_name: string
  discovery_count: number
  negative_flips: number
  accuracy_drop: number | null
}

export interface Analysis {
  id: string
  name: string
  created_at: string
  fixture_only: boolean
  status: string
  old_model: { name: string; run_id: string; provenance_status: string; identity_verified: boolean }
  new_model: { name: string; run_id: string; provenance_status: string; identity_verified: boolean }
  dataset: {
    label_vocab: string[]
    counts: Record<string, number>
    row_count: number
    component_count: number
    content_sha256: string
    labelset_sha256: string
    source?: { source_url: string; version: string; license: string }
  }
  coverage: { old: Coverage; new: Coverage }
  metrics: { discovery: Metrics; confirmation: Metrics | null }
  confusion_changes: {
    cells: { gold_label: string; prediction_label: string; old_count: number; new_count: number; delta: number }[]
    total_nonzero: number
    truncated: boolean
  }
  slices: {
    rank: number
    predicate: { all: { feature: string; op: string; value: string | number | boolean }[] }
    discovery: Metrics
    status: string
    confirmation: Metrics | null
  }[]
  candidate_set_hash: string
  evidence_mode: string
  verdict: string
  summary_reason: string
  content_sha256: string
  limitations: string[]
}

export type Outcome = 'all' | 'negative_flip' | 'positive_flip' | 'both_correct' | 'both_wrong'

export interface Sample {
  sample_id: string
  text: string
  gold_label: string
  old_prediction_label: string
  new_prediction_label: string
  outcome: Outcome
  features: Record<string, string | number | boolean>
}

export interface CasePage {
  items: Sample[]
  total: number
  page: number
  page_size: number
}

export interface Health {
  status: string
  mode: string
  version: string
  limits: { max_rows: number; max_file_bytes: number }
  capabilities: string[]
}
