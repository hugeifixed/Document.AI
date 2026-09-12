import { ArrowRightIcon } from "@heroicons/react/20/solid";
import { Link } from "react-router-dom";
import type { JourneyAction } from "@/journey/guidance";

export function JourneyCue({ action, className = "" }: { action: JourneyAction; className?: string }) {
  return (
    <aside
      aria-label="Next step"
      className={`flex flex-col gap-3 rounded-box border border-s-4 border-base-300 border-s-(--color-orange-ink) bg-base-100 px-4 py-3 sm:flex-row sm:items-center ${className}`}
    >
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-base-content">Next: {action.title}</p>
        <p className="reading-copy mt-0.5 text-sm text-secondary">{action.description}</p>
      </div>
      <Link to={action.to} className="btn btn-primary btn-sm shrink-0 self-start sm:self-center">
        {action.label}
        <ArrowRightIcon aria-hidden="true" className="size-4" />
      </Link>
    </aside>
  );
}
