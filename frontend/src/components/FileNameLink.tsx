import { Link } from "react-router-dom";

/** A compact document link that keeps the extension visible when its name is truncated. */
export function FileNameLink({ name, to }: { name: string; to: string }) {
  const dot = name.lastIndexOf(".");
  const hasExtension = dot > 0 && dot < name.length - 1;
  const stem = hasExtension ? name.slice(0, dot) : name;
  const extension = hasExtension ? name.slice(dot) : "";

  return (
    <Link
      to={to}
      className="link link-primary inline-flex min-w-0 max-w-56 overflow-hidden align-bottom sm:max-w-72 lg:max-w-96 xl:max-w-md"
      aria-label={name}
      title={name}
    >
      <span className="min-w-0 truncate">{stem}</span>
      {extension && <span className="max-w-20 shrink-0 truncate">{extension}</span>}
    </Link>
  );
}
