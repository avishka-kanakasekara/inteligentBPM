type BrandLogoProps = {
  variant?: "full" | "mark";
  className?: string;
};

export function BrandLogo({ variant = "full", className }: BrandLogoProps) {
  const src = variant === "mark" ? "/logo-mark.png" : "/logo.png";
  return <img className={className ?? "brand-logo"} src={src} alt="Intelligent BPM" />;
}
