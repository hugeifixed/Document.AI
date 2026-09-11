import { ArrowRightIcon } from "@heroicons/react/20/solid";
import { Link } from "react-router-dom";
import type { JourneyAction } from "@/journey/guidance";

export function JourneyCue({ action, className = "" }: { action: JourneyAction; className?: string }) {
  return (
    <Link to={action.to} className={`callout-warm ${className}`}>
      <span className="min-w-0 flex-1">
        <span className="block text-caption font-semibold uppercase tracking-wide">Recommended next step</span>
        <span className="mt-1 block font-semibold text-base-content">{action.title}</span>
        <span className="reading-copy mt-1 block text-sm">{action.description}</span>
      </span>
      <span className="inline-flex shrink-0 items-center gap-2 font-semibold text-base-content">
        {action.label}
        <span aria-hidden="true" className="grid size-7 place-items-center rounded-full bg-base-100 elevation-raised">
          <ArrowRightIcon className="size-4" />
        </span>
      </span>
    </Link>
  );
}
