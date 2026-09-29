import { forwardRef, useId } from "react";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { Icon } from "./Icon";

const CONTROL =
  "w-full rounded-m bg-base-tertiary px-m text-base text-neutral-95 placeholder:text-neutral-40 hairline border-neutral-20 transition-[border-color,box-shadow,background-color] duration-ui ease-ui hover:border-neutral-40 focus:border-brand-line focus:outline-none focus:ring-[3px] focus:ring-brand-alpha-soft disabled:cursor-not-allowed disabled:bg-base-secondary disabled:text-neutral-60";

type FieldShellProps = {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  action?: ReactNode;
};

export function FieldShell({ label, htmlFor, hint, error, children, action }: FieldShellProps) {
  return (
    <div className="flex flex-col gap-xs">
      <div className="flex items-baseline justify-between gap-m">
        <label htmlFor={htmlFor} className="text-sm font-medium text-neutral-80">
          {label}
        </label>
        {action}
      </div>
      {children}
      {error ? (
        <p className="flex items-center gap-xxs text-sm text-danger-strong" role="alert">
          <Icon name="alert" size={13} />
          {error}
        </p>
      ) : hint ? (
        <p className="text-sm text-neutral-60">{hint}</p>
      ) : null}
    </div>
  );
}

export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className"> & {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  action?: ReactNode;
  mono?: boolean;
};

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, action, mono = false, id, ...rest },
  ref,
) {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <FieldShell label={label} htmlFor={fieldId} hint={hint} error={error} action={action}>
      <input
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        {...rest}
        className={`${CONTROL} h-9 ${mono ? "font-mono text-sm" : ""} ${
          error ? "border-danger-line" : ""
        }`}
      />
    </FieldShell>
  );
});

export type TextAreaFieldProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "className"> & {
  label: string;
  hint?: ReactNode;
  error?: string | null;
};

export function TextAreaField({ label, hint, error, id, ...rest }: TextAreaFieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <FieldShell label={label} htmlFor={fieldId} hint={hint} error={error}>
      <textarea
        id={fieldId}
        aria-invalid={error ? true : undefined}
        {...rest}
        className={`${CONTROL} min-h-[72px] resize-y py-s leading-5 ${
          error ? "border-danger-line" : ""
        }`}
      />
    </FieldShell>
  );
}

export type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "className"> & {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
};

export function SelectField({ label, hint, error, id, children, ...rest }: SelectFieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <FieldShell label={label} htmlFor={fieldId} hint={hint} error={error}>
      <div className="relative">
        <select
          id={fieldId}
          aria-invalid={error ? true : undefined}
          {...rest}
          className={`${CONTROL} h-9 cursor-pointer appearance-none pr-xxl ${
            error ? "border-danger-line" : ""
          }`}
        >
          {children}
        </select>
        <span className="pointer-events-none absolute right-m top-1/2 -translate-y-1/2 text-neutral-60">
          <Icon name="chevron-down" size={14} />
        </span>
      </div>
    </FieldShell>
  );
}
