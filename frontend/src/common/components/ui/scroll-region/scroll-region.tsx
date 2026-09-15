import type { ComponentPropsWithRef } from "react";
/** Overflowing data remains scrollable with a keyboard, including in Safari. */
export function ScrollRegion({
  label,
  children,
  className = "",
  ...props
}: ComponentPropsWithRef<"section"> & { label: string }) {
  return (
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focus enables arrow-key scrolling of this named region.
    <section {...props} aria-label={label} tabIndex={0} className={`min-w-0 overflow-auto ${className}`}>
      {children}
    </section>
  );
}
