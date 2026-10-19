export type PrintSettings = Readonly<{
  nozzleDiameterMm: string;
  layerHeightMm: string;
  infillPercent: number;
  supports: boolean;
  wallLoops: number;
  filamentType: string;
}>;

export type PrintSpecification = Readonly<{
  presetCode: string;
  presetLabel: string;
  materialCode: string;
  profileSha256: string;
  colour: string | null;
  settings: PrintSettings;
}>;

export type PrintPreset = Readonly<{
  code: string;
  label: string;
  materialCode: string;
  profileSha256: string;
  colours: readonly string[];
  settings: PrintSettings;
}>;

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

function settings(value: unknown): PrintSettings {
  if (
    !record(value) ||
    typeof value.nozzleDiameterMm !== "string" ||
    typeof value.layerHeightMm !== "string" ||
    !Number.isFinite(Number(value.nozzleDiameterMm)) ||
    Number(value.nozzleDiameterMm) <= 0 ||
    !Number.isFinite(Number(value.layerHeightMm)) ||
    Number(value.layerHeightMm) <= 0 ||
    !Number.isInteger(value.infillPercent) ||
    Number(value.infillPercent) < 0 ||
    Number(value.infillPercent) > 100 ||
    typeof value.supports !== "boolean" ||
    !Number.isInteger(value.wallLoops) ||
    Number(value.wallLoops) < 1 ||
    typeof value.filamentType !== "string" ||
    !value.filamentType.trim()
  ) {
    throw new Error(
      "The service returned invalid print settings. Please refresh.",
    );
  }
  return value as unknown as PrintSettings;
}

export function parsePrintSpecification(
  value: unknown,
): PrintSpecification | null {
  if (value === null || value === undefined) return null;
  if (
    !record(value) ||
    typeof value.presetCode !== "string" ||
    typeof value.presetLabel !== "string" ||
    typeof value.materialCode !== "string" ||
    typeof value.profileSha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(value.profileSha256) ||
    (value.colour !== null && typeof value.colour !== "string")
  ) {
    throw new Error(
      "The service returned an invalid print specification. Please refresh.",
    );
  }
  return {
    presetCode: value.presetCode,
    presetLabel: value.presetLabel,
    materialCode: value.materialCode,
    profileSha256: value.profileSha256,
    colour: value.colour,
    settings: settings(value.settings),
  };
}

export async function listPrintPresets(): Promise<readonly PrintPreset[]> {
  const response = await fetch("/api/v1/print-presets", { cache: "no-store" });
  if (!response.ok)
    throw new Error("Print options could not be loaded. Please try again.");
  const payload: unknown = await response.json();
  if (!record(payload) || !Array.isArray(payload.items))
    throw new Error("The print catalogue returned an invalid response.");
  return payload.items.map((item: unknown) => {
    if (
      !record(item) ||
      typeof item.code !== "string" ||
      typeof item.label !== "string" ||
      typeof item.materialCode !== "string" ||
      typeof item.profileSha256 !== "string" ||
      !/^[a-f0-9]{64}$/.test(item.profileSha256) ||
      !Array.isArray(item.colours) ||
      !item.colours.every((colour: unknown) => typeof colour === "string")
    )
      throw new Error("The print catalogue returned an invalid offering.");
    return {
      code: item.code,
      label: item.label,
      materialCode: item.materialCode,
      profileSha256: item.profileSha256,
      colours: item.colours as string[],
      settings: settings(item.settings),
    };
  });
}
