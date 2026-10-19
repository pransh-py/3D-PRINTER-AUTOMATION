"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { UiIcon } from "./ui-icon";
import styles from "@/app/home.module.css";

const MATERIALS = {
  PLA: {
    name: "The everyday starting point.",
    description:
      "For prototypes, display models and the first version of an idea. Start with PLA when form and detail come first.",
    uses: "Concept models, desk objects, fit checks",
    colours: ["red", "white", "black"],
    image: "/images/printflow-parts.png",
    alt: "Illustrative printed forms: a bracket, a vase and an architectural model",
  },
  PETG: {
    name: "For your functional ideas.",
    description:
      "For practical parts that need a tougher material. Choose PETG for your next functional prototype, with the right profile for the job.",
    uses: "Brackets, housings, practical prototypes",
    colours: ["black", "orange"],
    image: "/images/printed-bracket.png",
    alt: "Illustrative black printed structural bracket with visible layer lines",
  },
};
const COLOURS: Record<string, string> = {
  red: "#c92e26",
  white: "#fafaf7",
  black: "#262825",
  orange: "#f46526",
};

export function MaterialExplorer() {
  const [material, setMaterial] = useState<keyof typeof MATERIALS>("PLA");
  const [colour, setColour] = useState("red");
  const selected = MATERIALS[material];
  return (
    <div className={styles.materialExplorer}>
      <div className={styles.materialImage} data-reveal>
        <Image
          key={selected.image}
          src={selected.image}
          alt={selected.alt}
          width={1536}
          height={1024}
          sizes="(max-width: 780px) 100vw, 52vw"
        />
        <span>FDM · Layer by layer</span>
      </div>
      <div className={styles.materialContent} data-reveal>
        <div
          className={styles.materialTabs}
          role="group"
          aria-label="Explore printing materials"
        >
          {(["PLA", "PETG"] as const).map((type) => (
            <button
              key={type}
              type="button"
              aria-pressed={material === type}
              onClick={() => {
                setMaterial(type);
                setColour(MATERIALS[type].colours[0]);
              }}
            >
              {type}
              <UiIcon name="arrow-up" />
            </button>
          ))}
        </div>
        <h3>{selected.name}</h3>
        <p>{selected.description}</p>
        <dl className={styles.materialFacts}>
          <div>
            <dt>Good for</dt>
            <dd>{selected.uses}</dd>
          </div>
          <div>
            <dt>Available colours</dt>
            <dd>{selected.colours.join(", ")}</dd>
          </div>
        </dl>
        <div
          className={styles.colourPicker}
          role="group"
          aria-label={`${material} colour`}
        >
          {selected.colours.map((name) => (
            <button
              key={name}
              type="button"
              aria-label={`${material} ${name}`}
              aria-pressed={colour === name}
              onClick={() => setColour(name)}
            >
              <span style={{ backgroundColor: COLOURS[name] }} />
              {name}
              <span className={styles.colourCheck}>
                {colour === name && <UiIcon name="check" />}
              </span>
            </button>
          ))}
        </div>
        <Link
          className={styles.textLink}
          href={`/print?material=${material}&colour=${colour}`}
        >
          Print with {material}
          <UiIcon name="arrow" />
        </Link>
      </div>
    </div>
  );
}
