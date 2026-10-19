import type { PrintSpecification } from "@/lib/print-specification";

export function PrintSpecificationSummary({
  value,
}: {
  value: PrintSpecification | null | undefined;
}) {
  if (!value) return null;
  const options = value.settings;
  return (
    <div aria-label="Selected print specification">
      <p>
        <strong>{value.presetLabel}</strong> · {options.filamentType}
        {value.colour ? ` · ${value.colour}` : " · colour confirmed by owner"}
      </p>
      <p>
        {options.layerHeightMm} mm layers · {options.infillPercent}% infill ·{" "}
        {options.wallLoops} walls
        {" · "}
        {options.supports ? "Supports enabled" : "No supports"}
        {" · "}
        {options.nozzleDiameterMm} mm nozzle
      </p>
    </div>
  );
}
