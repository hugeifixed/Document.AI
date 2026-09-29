export type PlaygroundType = "extract_structured" | "extract_unstructured" | "unbundle_classify_extract";
export type ProposedField = {
  name: string;
  description: string;
  type: "string" | "number" | "integer" | "date" | "boolean" | "currency" | "percent" | "identifier" | "enum" | "list";
  required: boolean;
  observed: boolean;
  sample_index: number | null;
  unit: number | null;
  source_label: string;
  variable_rows: boolean;
  guidance: string;
  enum_values: string[];
};
export type ProposedDocument = {
  key: string;
  name: string;
  description: string;
  distinguishing_evidence: string;
  continuation_characteristics: string;
  fields: ProposedField[];
};
export type PlaygroundProposal = { workflow_type: PlaygroundType; documents: ProposedDocument[] };
export type PlaygroundSession = {
  id: string;
  project: string;
  expires_at: string;
  last_activity_at: string;
  status: "ready" | "queued" | "analyzing" | "generating" | "complete" | "failed";
  goal: string;
  workflow_type: PlaygroundType | "";
  error_code: string;
  error_message: string;
  samples: { id: string; document_id: string | null; filename: string; units: number; source_kind: "dataset" | "temporary" }[];
  proposal: PlaygroundProposal | Record<string, never>;
  config: Record<string, unknown> | null;
  usage: { input_tokens: number; cached_input_tokens: number; output_tokens: number };
};
export type PlaygroundSessionSummary = Pick<PlaygroundSession, "id" | "status" | "goal" | "workflow_type" | "expires_at" | "last_activity_at">;
