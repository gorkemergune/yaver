// Colour per block / event kind (left border + dot), Dayframe-like calm palette.
const KIND_COLORS: Record<string, string> = {
  class: "#0ea5e9",
  lab: "#8b5cf6",
  sport: "#10b981",
  work: "#f59e0b",
  other: "#64748b",
  exam: "#e11d48",
  quiz: "#f97316",
  makeup: "#14b8a6",
  meeting: "#6366f1",
  deadline: "#dc2626",
  hackathon: "#d946ef",
};

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? "#64748b";
}
