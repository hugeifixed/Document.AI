import { CheckIcon } from "@heroicons/react/20/solid";

const steps = [
  { status: "queued", label: "Waiting for worker" },
  { status: "analyzing", label: "Reading examples" },
  { status: "generating", label: "Drafting fields" },
] as const;

type Stage = (typeof steps)[number]["status"];

export function GenerationProgress({ stage, hasExamples }: { stage: Stage; hasExamples: boolean }) {
  const active = steps.findIndex((step) => step.status === stage);
  const detail = {
    queued: "Your request is queued. Processing will start when a worker is ready.",
    analyzing: hasExamples
      ? "Checking the layout and reading every page or sheet in your examples."
      : "Reviewing the goal before drafting fields.",
    generating: "Preparing field suggestions and validating the workflow JSON.",
  }[stage];

  return (
    <output className="block rounded-box border border-base-300 bg-(--color-blue-soft) p-4" aria-live="polite">
      <div className="flex items-start gap-3">
        <span className="loading loading-spinner loading-sm mt-0.5 shrink-0 text-primary motion-reduce:animate-none" aria-hidden="true" />
        <div className="min-w-0">
          <p className="font-semibold">Generating proposal</p>
          <p className="mt-1 text-sm text-secondary text-pretty">{detail}</p>
        </div>
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-3" aria-label="Generation stages">
        {steps.map((step, index) => (
          <li key={step.status} aria-current={index === active ? "step" : undefined}
            className={`flex min-h-10 items-center gap-2 rounded-lg border px-3 py-2 text-sm ${index === active ? "border-(--border-interactive) bg-base-100 font-medium" : "border-base-300"}`}>
            {index < active
              ? <CheckIcon className="size-4 shrink-0 text-primary" aria-hidden="true" />
              : <span className="w-4 shrink-0 text-center tabular-nums text-secondary" aria-hidden="true">{index + 1}</span>}
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-caption text-secondary">You can leave this page and resume the proposal later.</p>
    </output>
  );
}
