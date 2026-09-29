import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const BASE =
  "relative inline-flex select-none items-center justify-center gap-xs whitespace-nowrap font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-ui ease-ui focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40 active:translate-y-[0.5px]";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-brand text-white shadow-flat hover:bg-brand-secondary active:bg-brand disabled:hover:bg-brand",
  secondary:
    "hairline border-neutral-20 bg-base-tertiary text-neutral-95 hover:bg-base-secondary active:bg-base-secondary-alt disabled:hover:bg-base-tertiary",
  ghost: "text-neutral-80 hover:bg-neutral-8 hover:text-neutral-95 active:bg-neutral-12",
  danger:
    "hairline border-danger-line bg-transparent text-danger-strong hover:bg-danger-surface active:bg-danger-chip",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-7 rounded-full px-m text-sm",
  md: "h-8 rounded-full px-l text-base",
  lg: "h-10 rounded-full px-xl text-md",
};

type CommonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  block?: boolean;
  children?: ReactNode;
  className?: string;
};

export type ButtonProps = CommonProps & ButtonHTMLAttributes<HTMLButtonElement>;

export function buttonClasses({
  variant = "primary",
  size = "md",
  block = false,
  className = "",
}: CommonProps): string {
  return [BASE, VARIANTS[variant], SIZES[size], block ? "w-full" : "", className]
    .filter(Boolean)
    .join(" ");
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, block, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={rest.type ?? "button"}
      {...rest}
      disabled={rest.disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, block, className })}
    >
      {loading ? <Spinner size={size === "lg" ? 15 : 13} /> : null}
      {children}
    </button>
  );
});

type LinkButtonProps = CommonProps & {
  to: string;
  "aria-label"?: string;
};

export function LinkButton({ to, children, ...rest }: LinkButtonProps) {
  return (
    <Link to={to} className={buttonClasses(rest)} aria-label={rest["aria-label"]}>
      {children}
    </Link>
  );
}

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
  active?: boolean;
  className?: string;
};

export function IconButton({
  label,
  children,
  active = false,
  className = "",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={rest["aria-pressed"] ?? (active || undefined)}
      {...rest}
      className={[
        "inline-flex h-7 w-7 items-center justify-center rounded-m transition-colors duration-ui ease-ui",
        active
          ? "bg-neutral-16 text-neutral-95"
          : "text-neutral-60 hover:bg-neutral-8 hover:text-neutral-95",
        "active:bg-neutral-16 disabled:cursor-not-allowed disabled:opacity-40",
        className,
      ].join(" ")}
    >
      {children}
    </button>
  );
}
