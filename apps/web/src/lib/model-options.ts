export type ModelOptions = Readonly<{
  sourceUnit: "mm" | "inch";
  rotationX: number;
  rotationY: number;
}>;
export const DEFAULT_MODEL_OPTIONS: ModelOptions = {
  sourceUnit: "mm",
  rotationX: 0,
  rotationY: 0,
};
export type ModelStats = Readonly<{
  dimensionsMm: readonly [number, number, number];
  volumeCm3: number;
}>;

export function swatchColour(name: string | null): string {
  const colours: Record<string, string> = {
    white: "#f5f5f0",
    black: "#24282b",
    red: "#ce3434",
    orange: "#df6e31",
  };
  return colours[(name ?? "").toLowerCase()] ?? "#b7c1c5";
}
