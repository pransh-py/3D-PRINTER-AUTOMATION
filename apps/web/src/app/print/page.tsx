import type { Metadata } from "next";
import PrintStation from "./print-station";

export const metadata: Metadata = { title: "Print workspace" };

export default async function PrintPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const material = query.material === "PETG" ? "PETG" : "PLA";
  const colours =
    material === "PETG" ? ["black", "orange"] : ["red", "white", "black"];
  const colour =
    typeof query.colour === "string" && colours.includes(query.colour)
      ? query.colour
      : colours[0];
  return (
    <PrintStation
      key={`${material}:${colour}`}
      initialMaterial={material}
      initialColour={colour}
    />
  );
}
