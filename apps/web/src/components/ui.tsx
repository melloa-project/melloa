import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { LoaderCircle, type LucideIcon } from "lucide-react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  readonly tone?: "primary" | "secondary" | "ghost" | "danger";
  readonly size?: "sm" | "md" | "icon";
  readonly loading?: boolean;
};

export function Button({
  tone = "secondary",
  size = "md",
  loading = false,
  className = "",
  disabled,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`button button-${tone} button-${size} ${className}`}
      disabled={disabled === true || loading}
      {...props}
    >
      {loading ? <LoaderCircle aria-hidden="true" className="spin" size={16} /> : null}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  icon: Icon,
  ...props
}: Omit<ButtonProps, "children" | "size"> & { readonly label: string; readonly icon: LucideIcon }) {
  return (
    <Button aria-label={label} size="icon" title={label} {...props}>
      <Icon aria-hidden="true" size={18} />
    </Button>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  readonly children: ReactNode;
  readonly tone?: "neutral" | "positive" | "warning" | "danger" | "info" | "violet";
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`card ${className}`} {...props} />;
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  readonly eyebrow?: string;
  readonly title: string;
  readonly description?: string;
  readonly action?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        {eyebrow === undefined ? null : <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description === undefined ? null : <p className="section-description">{description}</p>}
      </div>
      {action === undefined ? null : <div className="section-action">{action}</div>}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  readonly icon: LucideIcon;
  readonly title: string;
  readonly description: string;
  readonly action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><Icon aria-hidden="true" size={22} /></span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function LoadingState({ label = "Loading private records" }: { readonly label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle aria-hidden="true" className="spin" size={20} />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({
  title = "This view is unavailable",
  message,
  action,
}: {
  readonly title?: string;
  readonly message: string;
  readonly action?: ReactNode;
}) {
  return (
    <Card className="error-state" role="alert">
      <h2>{title}</h2>
      <p>{message}</p>
      {action}
    </Card>
  );
}

export function Metric({
  label,
  value,
  detail,
}: {
  readonly label: string;
  readonly value: ReactNode;
  readonly detail?: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail === undefined ? null : <small>{detail}</small>}
    </div>
  );
}

export function Modal({
  open,
  title,
  description,
  onClose,
  children,
}: {
  readonly open: boolean;
  readonly title: string;
  readonly description?: string;
  readonly onClose: () => void;
  readonly children: ReactNode;
}) {
  if (!open) {
    return null;
  }
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        aria-labelledby="modal-title"
        aria-modal="true"
        className="modal"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2 id="modal-title">{title}</h2>
            {description === undefined ? null : <p>{description}</p>}
          </div>
          <Button aria-label="Close dialog" onClick={onClose} size="icon" tone="ghost">×</Button>
        </div>
        {children}
      </section>
    </div>
  );
}
