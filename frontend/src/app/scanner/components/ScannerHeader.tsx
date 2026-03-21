interface ScannerHeaderProps {
  tagline: string;
}

export function ScannerHeader({ tagline }: ScannerHeaderProps) {
  return (
    <div className="space-y-1">
      <h1 className="text-xl font-semibold">Scanner</h1>
      <p className="text-sm text-muted-foreground">{tagline}</p>
    </div>
  );
}
