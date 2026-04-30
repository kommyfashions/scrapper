export default function PageHeader({ title, subtitle, right, testid }) {
  return (
    <div
      className="flex flex-wrap items-end justify-between gap-4 border-b border-[#2A2A2A] px-8 py-6"
      data-testid={testid || "page-header"}
    >
      <div>
        <div className="section-label mb-1">/ {title}</div>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-white">
          {subtitle}
        </h1>
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}
