import type { ReactNode } from "react";
import { Search } from "lucide-react";

export function PageHeading({ eyebrow = "Research workspace", title, description, actions }: { eyebrow?: string; title: string; description: ReactNode; actions?: ReactNode }) {
  return <header className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1><div className="page-description">{description}</div></div>{actions}</header>;
}
export function SearchField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="search-field"><span className="sr-only">{label}</span><Search size={17} aria-hidden="true" /><input type="search" value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} /></label>;
}
export function EmptyState({ title, description, action }: { title: string; description: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted">No results</p><h2 className="text-lg font-semibold text-ink">{title}</h2><div className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-muted">{description}</div>{action && <div className="mt-5">{action}</div>}</div>;
}
