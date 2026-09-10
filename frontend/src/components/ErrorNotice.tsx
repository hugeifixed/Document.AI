import { ExclamationTriangleIcon } from "@heroicons/react/20/solid";

export function ErrorNotice({ message, onRetry, id }: { message: string; onRetry?: () => void; id?: string }) {
  return (
    <div id={id} role="alert" className="alert alert-error alert-vertical sm:alert-horizontal text-left">
      <ExclamationTriangleIcon className="size-5 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 break-words">{message}</span>
      {onRetry && <button type="button" className="btn btn-sm btn-outline" onClick={onRetry}>Retry</button>}
    </div>
  );
}
