import type { ReactNode } from "react";
/** Form group (§11): label above the control; help and error text keep the §15 rhythm through the `field` utility. */
export function Field({
  id,
  label,
  labelAction,
  required,
  className = "",
  children,
}: {
  id?: string;
  label: ReactNode;
  labelAction?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const fieldLabel = (
    <label className="label" htmlFor={id}>
      {label}
      {required && <span aria-hidden> *</span>}
    </label>
  );
  return (
    <div className={`field ${className}`}>
      {labelAction ? (
        <div className="field-label-row flex items-center gap-2">
          {fieldLabel}
          {labelAction}
        </div>
      ) : (
        fieldLabel
      )}
      {children}
    </div>
  );
}
