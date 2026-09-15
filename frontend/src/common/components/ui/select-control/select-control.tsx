import { ChevronDownIcon } from "@heroicons/react/20/solid";
import { forwardRef, type SelectHTMLAttributes } from "react";
export const SelectControl = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function SelectControl({ className = "", children, ...props }, ref) {
    return (
      <span className="relative block min-w-0 max-w-full">
        <select ref={ref} className={`select select-managed-caret peer w-full ${className}`} {...props}>
          {children}
        </select>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-px end-px z-10 grid w-10 place-items-center rounded-e-[calc(var(--radius-field)-1px)] bg-base-100 text-base-content peer-disabled:bg-base-200 peer-disabled:text-base-content/40"
        >
          <ChevronDownIcon className="size-4" />
        </span>
      </span>
    );
  },
);
