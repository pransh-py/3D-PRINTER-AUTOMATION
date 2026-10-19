"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { SiteHeader } from "@/components/site-header";
import { UiIcon } from "@/components/ui-icon";
import {
  DEFAULT_MODEL_OPTIONS,
  swatchColour,
  type ModelOptions,
  type ModelStats,
} from "@/lib/model-options";
import styles from "./station.module.css";

const ModelPreview = dynamic(
  () => import("@/components/quotes/model-preview"),
  { ssr: false },
);
type Material = "PLA" | "PETG";
type RateCard = {
  material_rate_paise_per_gram: number;
  machine_rate_paise_per_hour: number;
};
type SliceEstimate = {
  currency: "INR";
  rates: RateCard;
  material_paise: number;
  machine_paise: number;
  total_paise: number;
};
const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
});
const money = (paise: number) => rupees.format(paise / 100);
type Job = {
  id: string;
  phase: string;
  message: string;
  options: {
    client_token: string;
    filename: string;
    material: string;
    colour: string;
    layer_height: string;
    infill: number;
    quantity: number;
  };
  progress: number;
  filament_mg?: number;
  duration_seconds?: number;
  package_sha256?: string;
  estimate?: SliceEstimate | null;
};
type Station = {
  token: string;
  enabled: boolean;
  bedType: string | null;
  pricing: RateCard | null;
  message: string;
  stock: Record<Material, string[]>;
  profiles: Record<
    Material,
    { available: boolean; approved: boolean; printableColours: string[] }
  >;
  printer: { state: string; firmware: string; progress: number } | null;
  jobs: Job[];
};
const ACTIVE = new Set([
  "uploading",
  "validating",
  "slicing",
  "starting",
  "awaiting_start",
  "printing",
  "needs_attention",
]);
const INFILLS = [10, 15, 20, 30, 40, 50, 60, 70, 80, 90];
const STOCK: Record<Material, string[]> = {
  PLA: ["red", "white", "black"],
  PETG: ["black", "orange"],
};

export default function PrintStation({
  initialMaterial = "PLA",
  initialColour = "red",
}: {
  initialMaterial?: Material;
  initialColour?: string;
}) {
  const [station, setStation] = useState<Station | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [material, setMaterial] = useState<Material>(initialMaterial);
  const [colour, setColour] = useState(initialColour);
  const [layer, setLayer] = useState("0.2");
  const [infill, setInfill] = useState(20);
  const [quantity, setQuantity] = useState(1);
  const [supports, setSupports] = useState(false);
  const [model, setModel] = useState<ModelOptions>(DEFAULT_MODEL_OPTIONS);
  const [rotation, setRotation] = useState({ x: "0", y: "0" });
  const [stats, setStats] = useState<ModelStats | null>(null);
  const [step, setStep] = useState(0);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const submission = useRef<{ token: string; payload: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async () => {
    const response = await fetch("/api/printer/status", { cache: "no-store" });
    if (!response.ok)
      throw new Error(
        "The local print service is offline. You can preview and configure your model; slicing is available when it reconnects.",
      );
    const next: Station = await response.json();
    if (
      next.jobs.some(
        (job) =>
          job.phase === "failed" &&
          job.options.client_token === submission.current?.token,
      )
    )
      submission.current = null;
    setStation(next);
    setConnectionError("");
  }, []);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        await refresh();
      } catch (error) {
        if (!disposed)
          setConnectionError(
            error instanceof Error ? error.message : "Station disconnected.",
          );
      }
      if (!disposed) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [refresh]);
  const onStats = useCallback(
    (value: ModelStats | null) => setStats(value),
    [],
  );
  const active = station?.jobs.find((job) => ACTIVE.has(job.phase));
  const latest = station?.jobs[0];
  const outsideBuildVolume = Boolean(
    stats?.dimensionsMm.some((dimension) => dimension > 220),
  );
  const available = Boolean(
    station?.profiles[material]?.available && station?.bedType,
  );
  const physical = Boolean(
    station?.enabled &&
      station?.profiles[material]?.printableColours?.includes(colour),
  );
  const printerReady =
    station?.printer && ["ready", "completed"].includes(station.printer.state);

  function selectFile(candidate?: File) {
    if (!candidate) return;
    if (
      !/\.(stl|obj)$/i.test(candidate.name) ||
      candidate.size < 1 ||
      candidate.size > 100 * 1024 * 1024
    ) {
      setMessage(
        "Choose an STL or OBJ model between 1 byte and 100 MiB. CAD assemblies and pre-sliced files are not accepted here.",
      );
      return;
    }
    setFile(candidate);
    setStats(null);
    setReady(false);
    setMessage("");
    submission.current = null;
  }

  async function submit(printNow: boolean) {
    if (!file || !station || busy || active || outsideBuildVolume) return;
    setBusy(true);
    setMessage("Checking model integrity and uploading…");
    try {
      const bytes = await file.arrayBuffer();
      const digest = Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        (value) => value.toString(16).padStart(2, "0"),
      ).join("");
      const base = {
        filename: file.name,
        size: file.size,
        source_sha256: digest,
        material,
        colour,
        layer_height: layer,
        infill,
        quantity,
        supports,
        model,
        print_now: printNow,
        readiness_confirmed: printNow && ready,
      };
      const fingerprint = JSON.stringify(base);
      if (!submission.current || submission.current.payload !== fingerprint)
        submission.current = {
          token: crypto.randomUUID(),
          payload: fingerprint,
        };
      const optionsHeader = JSON.stringify({
        ...base,
        client_token: submission.current.token,
      }).replace(
        /[^\x20-\x7e]/g,
        (value) => `\\u${value.charCodeAt(0).toString(16).padStart(4, "0")}`,
      );
      const response = await fetch("/api/printer/jobs", {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Station-Token": station.token,
          "X-Print-Options": optionsHeader,
        },
        body: bytes,
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "The station rejected these settings.",
        );
      setMessage(
        "Model received. Follow the live job below; do not submit it again.",
      );
      setReady(false);
      await refresh();
    } catch (error) {
      setMessage(
        (error instanceof Error ? error.message : "Connection lost.") +
          " Check the job list before retrying. An uncertain physical start is never resent.",
      );
      void refresh().catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  async function resolve(job: Job) {
    if (
      !station ||
      !window.confirm(
        "Have you inspected the printer, stopped/resolved the job at its screen, and removed everything from the bed? This will NOT resend the job.",
      )
    )
      return;
    try {
      const response = await fetch(`/api/printer/jobs/${job.id}/resolve`, {
        method: "POST",
        headers: {
          "X-Station-Token": station.token,
          "X-Bed-Clear-Confirmed": "true",
        },
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "Resolve the printer at its screen first.",
        );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Resolution failed.");
    }
  }

  const labels = [
    "Print quality",
    "Material & colour",
    "Infill & supports",
    station?.enabled ? "Review & print" : "Review & slice",
  ];
  const values = [
    `${layer} mm · 0.4 mm nozzle`,
    `${material} · ${colour}`,
    `${infill}% · supports ${supports ? "on" : "off"}`,
    `${quantity} ${quantity === 1 ? "copy" : "copies"} · one plate`,
  ];

  return (
    <div className={styles.shell}>
      <SiteHeader workspace />
      <main className={styles.page} id="main-content" data-ui>
        <div className={styles.title}>
          <div>
            <h1>Make it your own.</h1>
            <p>Your model, your material, your next print.</p>
          </div>
          <span
            className={styles.connection}
            data-connected={Boolean(station?.printer) && !connectionError}
          >
            {station?.printer && !connectionError
              ? `AD5X · ${station.printer.state}`
              : "AD5X · not connected"}
          </span>
        </div>
        {connectionError && (
          <div role="status" className={styles.connectionNotice}>
            <span className={styles.statusDot} />
            <p>{connectionError}</p>
            <button
              type="button"
              onClick={() => void refresh().catch(() => {})}
            >
              Reconnect <UiIcon name="arrow" />
            </button>
          </div>
        )}
        <div className={styles.columns}>
          <section
            aria-label="Model preview and orientation"
            className={styles.modelColumn}
          >
            <div className={styles.panelHeading}>
              <h2>Your model</h2>
              <span>STL / OBJ · up to 100 MiB</span>
            </div>
            <div
              className={styles.preview}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                selectFile(event.dataTransfer.files[0]);
              }}
            >
              {file ? (
                <ModelPreview
                  file={file}
                  options={model}
                  colour={swatchColour(colour)}
                  onStats={onStats}
                />
              ) : (
                <div className={styles.empty}>
                  <div className={styles.uploadIcon}>
                    <UiIcon name="upload" />
                  </div>
                  <h3>A little file. A real possibility.</h3>
                  <p>Drop your STL or OBJ here.</p>
                  <button
                    type="button"
                    className={styles.browse}
                    onClick={() => input.current?.click()}
                  >
                    Choose a model
                    <UiIcon name="arrow-up" />
                  </button>
                  <span>220 × 220 × 220 mm build volume</span>
                </div>
              )}
            </div>
            <input
              ref={input}
              id="model-upload"
              type="file"
              accept=".stl,.obj"
              hidden
              onChange={(event) => selectFile(event.target.files?.[0])}
            />
            {file && (
              <button
                type="button"
                className={styles.upload}
                onClick={() => input.current?.click()}
              >
                <UiIcon name="file" />
                Replace model
                <UiIcon name="arrow-up" />
              </button>
            )}
            <p className={styles.hint}>
              STL / OBJ · up to 100 MiB · stored on this computer only
            </p>
            {outsideBuildVolume && (
              <p className={styles.notice} role="alert">
                This model is {stats!.dimensionsMm.map((n) => n.toFixed(2)).join(" × ")} mm.
                The AD5X build volume is 220 × 220 × 220 mm. If your file contains
                several parts, export them individually. Otherwise resize it in
                CAD or check the file units before slicing.
              </p>
            )}
            <fieldset className={styles.units}>
              <legend>File unit</legend>
              {(["mm", "inch"] as const).map((unit) => (
                <label key={unit}>
                  <input
                    type="radio"
                    name="unit"
                    value={unit}
                    checked={model.sourceUnit === unit}
                    onChange={() => {
                      setModel({ ...model, sourceUnit: unit });
                      setReady(false);
                    }}
                  />
                  {unit === "mm" ? "Millimetres" : "Inches"}
                </label>
              ))}
            </fieldset>
            <div className={styles.rotation}>
              <span>Rotation</span>
              <label>
                X{" "}
                <input
                  aria-label="X rotation in degrees"
                  type="number"
                  min={-180}
                  max={180}
                  step={1}
                  value={rotation.x}
                  onChange={(event) =>
                    setRotation({ ...rotation, x: event.target.value })
                  }
                />
              </label>
              <label>
                Y{" "}
                <input
                  aria-label="Y rotation in degrees"
                  type="number"
                  min={-180}
                  max={180}
                  step={1}
                  value={rotation.y}
                  onChange={(event) =>
                    setRotation({ ...rotation, y: event.target.value })
                  }
                />
              </label>
              <button
                type="button"
                onClick={() => {
                  const x = Number(rotation.x),
                    y = Number(rotation.y);
                  if (
                    ![x, y].every(
                      (v) => Number.isInteger(v) && v >= -180 && v <= 180,
                    ) ||
                    rotation.x === "" ||
                    rotation.y === ""
                  ) {
                    setMessage(
                      "Use whole-degree rotations between −180 and 180.",
                    );
                    return;
                  }
                  setModel({ ...model, rotationX: x, rotationY: y });
                  setReady(false);
                  setMessage("");
                }}
              >
                Apply
              </button>
            </div>
            <dl className={styles.stats}>
              <div>
                <dt>Model dimensions</dt>
                <dd>
                  {stats
                    ? stats.dimensionsMm.map((n) => n.toFixed(2)).join(" × ") +
                      " mm"
                    : "Upload a model"}
                </dd>
              </div>
              <div>
                <dt>Enclosed mesh volume*</dt>
                <dd>{stats ? `${stats.volumeCm3.toFixed(2)} cm³` : "—"}</dd>
              </div>
              <div>
                <dt>Print time, filament & price</dt>
                <dd>Estimated after slicing</dd>
              </div>
            </dl>
            <p className={styles.hint}>
              *Geometric approximation for closed meshes—not filament usage.
              Applied units and rotation are used by the slicer.
            </p>
          </section>
          <section
            className={styles.configuration}
            aria-label="Print configuration"
          >
            <div className={styles.configHeading}>
              <h2>Print settings</h2>
              <p>FlashForge AD5X · 0.4 mm nozzle · one plate</p>
            </div>
            <div className={styles.accordion}>
              {labels.map((label, index) => (
                <section key={label}>
                  <h3>
                    <button
                      type="button"
                      aria-expanded={step === index}
                      aria-controls={`step-${index}`}
                      onClick={() => setStep(index)}
                    >
                      <span className={styles.stepIcon}>
                        <UiIcon
                          name={
                            index === 0
                              ? "layers"
                              : index === 3
                                ? "check"
                                : "cube"
                          }
                        />
                      </span>
                      <span>
                        {label}
                        <small>{values[index]}</small>
                      </span>
                      <b>{step === index ? "−" : "+"}</b>
                    </button>
                  </h3>
                  <div
                    id={`step-${index}`}
                    hidden={step !== index}
                    className={styles.step}
                  >
                    {index === 0 && (
                      <fieldset>
                        <legend>Layer height</legend>
                        {[
                          ["0.2", "Standard", "Everyday parts"],
                          ["0.15", "Fine", "A balanced finish"],
                          ["0.1", "Detailed", "Finer layers, longer print"],
                        ].map(([value, name, detail]) => (
                          <label className={styles.choice} key={value}>
                            <input
                              type="radio"
                              name="layer"
                              checked={layer === value}
                              onChange={() => {
                                setLayer(value);
                                setReady(false);
                              }}
                            />
                            <span>
                              {value} mm · {name}
                              <small>{detail}</small>
                            </span>
                          </label>
                        ))}
                      </fieldset>
                    )}
                    {index === 1 && (
                      <div>
                        {(["PLA", "PETG"] as Material[]).map((type) => (
                          <div className={styles.material} key={type}>
                            <div>
                              <strong>{type}</strong>
                              <small>
                                {type === "PLA"
                                  ? "Prototypes & display parts"
                                  : "Tougher functional parts"}
                                {station && !station.profiles[type]?.available
                                  ? " · profile not configured"
                                  : ""}
                              </small>
                            </div>
                            <div className={styles.swatches}>
                              {(station?.stock[type] ?? STOCK[type]).map(
                                (name) => (
                                  <button
                                    type="button"
                                    key={name}
                                    aria-label={`${type} ${name}`}
                                    aria-pressed={
                                      material === type && colour === name
                                    }
                                    title={`${type} · ${name}`}
                                    style={{
                                      background: swatchColour(name),
                                      color:
                                        name === "white" || name === "orange"
                                          ? "#242724"
                                          : "#ffffff",
                                    }}
                                    onClick={() => {
                                      setMaterial(type);
                                      setColour(name);
                                      setReady(false);
                                    }}
                                  >
                                    {material === type && colour === name && (
                                      <UiIcon name="check" />
                                    )}
                                  </button>
                                ),
                              )}
                            </div>
                          </div>
                        ))}
                        <p className={styles.hint}>
                          Selected: {material} — {colour}. Only your confirmed
                          filament options are shown.
                        </p>
                      </div>
                    )}
                    {index === 2 && (
                      <>
                        <fieldset>
                          <legend>Infill density</legend>
                          <div className={styles.infill}>
                            {INFILLS.map((value) => (
                              <label key={value}>
                                <input
                                  type="radio"
                                  name="infill"
                                  checked={infill === value}
                                  onChange={() => {
                                    setInfill(value);
                                    setReady(false);
                                  }}
                                />
                                {value}%
                              </label>
                            ))}
                          </div>
                        </fieldset>
                        <label className={styles.check}>
                          <input
                            type="checkbox"
                            checked={supports}
                            onChange={(event) => {
                              setSupports(event.target.checked);
                              setReady(false);
                            }}
                          />
                          Generate supports for overhangs
                        </label>
                        <p className={styles.hint}>
                          More infill increases internal density. Supports and
                          wall settings come from the reviewed process profile.
                        </p>
                      </>
                    )}
                    {index === 3 && (
                      <>
                        <dl className={styles.summary}>
                          <div>
                            <dt>Build plate</dt>
                            <dd>{station?.bedType ?? "Not configured"}</dd>
                          </div>
                          <div>
                            <dt>Model</dt>
                            <dd>{file?.name ?? "No file selected"}</dd>
                          </div>
                          <div>
                            <dt>Print</dt>
                            <dd>
                              {material} · {colour} · {layer} mm · {infill}%
                            </dd>
                          </div>
                          <div>
                            <dt>Supports</dt>
                            <dd>{supports ? "On" : "Off"}</dd>
                          </div>
                        </dl>
                        <label className={styles.quantity}>
                          Quantity{" "}
                          <input
                            type="number"
                            min={1}
                            max={10}
                            step={1}
                            value={quantity}
                            onChange={(event) => {
                              setQuantity(Number(event.target.value));
                              setReady(false);
                            }}
                          />
                        </label>
                        <p className={styles.hint}>
                          Copies are arranged on a single plate. Multiple plates
                          and automatic back-to-back prints are not supported.
                        </p>
                        <p className={styles.notice}>
                          {physical
                            ? "Printer starts enabled. This action can heat and move the printer."
                            : "Slicing-only mode. No printer commands will be sent."}
                        </p>
                        {physical && (
                          <label className={styles.check}>
                            <input
                              type="checkbox"
                              checked={ready}
                              onChange={(event) =>
                                setReady(event.target.checked)
                              }
                            />
                            I checked the bed is clear, the 0.4 mm nozzle and
                            selected filament/IFS mapping are correct, and
                            someone is supervising the printer.
                          </label>
                        )}
                        <button
                          type="button"
                          className={styles.primary}
                          disabled={
                            !file ||
                            !station ||
                            Boolean(connectionError) ||
                            !available ||
                            outsideBuildVolume ||
                            busy ||
                            Boolean(active) ||
                            !Number.isInteger(quantity) ||
                            quantity < 1 ||
                            quantity > 10 ||
                            (physical && (!ready || !printerReady))
                          }
                          onClick={() => void submit(physical)}
                        >
                          {busy
                            ? "Uploading…"
                            : physical
                              ? "Slice & print automatically →"
                              : station?.pricing
                                ? "Slice & estimate →"
                                : "Slice model →"}
                        </button>
                        {physical && (
                          <button
                            type="button"
                            className={styles.secondary}
                            disabled={
                              !file ||
                              outsideBuildVolume ||
                              busy ||
                              Boolean(active) ||
                              !available ||
                              Boolean(connectionError)
                            }
                            onClick={() => void submit(false)}
                          >
                            Slice only · do not print
                          </button>
                        )}
                        {!available && (
                          <p role="status" className={styles.hint}>
                            Configure a matching {material} base profile and the
                            build-plate type locally first.
                          </p>
                        )}
                      </>
                    )}
                    {index < 3 && (
                      <div className={styles.stepNav}>
                        {index > 0 && (
                          <button
                            type="button"
                            onClick={() => setStep(index - 1)}
                          >
                            Previous
                          </button>
                        )}
                        <button
                          type="button"
                          className={styles.next}
                          onClick={() => setStep(index + 1)}
                        >
                          Next →
                        </button>
                      </div>
                    )}
                  </div>
                </section>
              ))}
            </div>
            <p className={styles.hint}>
              {station?.message ?? "Connecting to the local station…"}
            </p>
            {message && (
              <p className={styles.notice} role="status">
                {message}
              </p>
            )}
          </section>
        </div>
        <section className={styles.jobs} aria-label="Print activity">
          <div className={styles.jobHeading}>
            <h2>Estimates & print activity</h2>
            <span>Saved on this computer</span>
          </div>
          {station?.pricing && (
            <p className={styles.hint}>
              Current rates: {money(station.pricing.material_rate_paise_per_gram)}/g
              {" "}of filament + {money(station.pricing.machine_rate_paise_per_hour)}/hour
              {" "}of printing. Prices use the sliced filament and time for your full quantity.
            </p>
          )}
          {!latest ? (
            <div className={styles.emptyActivity}>
              <UiIcon name="layers" />
              <div>
                <h3>
                  {station
                    ? "Your next print starts here."
                    : "Print history is unavailable."}
                </h3>
                <p>
                  {station
                    ? "Your sliced files and print progress will appear here."
                    : "Connect the local print service to see your saved jobs."}
                </p>
              </div>
              <span>{station ? "No jobs yet" : "Not connected"}</span>
            </div>
          ) : (
            station?.jobs.slice(0, 5).map((job) => (
              <article key={job.id} className={styles.job}>
                <div>
                  <span className={styles.phase}>
                    {job.phase.replaceAll("_", " ")}
                  </span>
                  <h3>{job.options.filename}</h3>
                  <p>
                    {job.message === "model_outside_build_volume"
                      ? "This model exceeds the AD5X's 220 × 220 × 220 mm build volume. Export individual parts from a multi-part layout, resize in CAD, or check the file units."
                      : job.message}
                  </p>
                  <small>
                    {job.options.material} · {job.options.colour} ·{" "}
                    {job.options.layer_height} mm · {job.options.infill}% ·{" "}
                    {job.options.quantity}{" "}
                    {job.options.quantity === 1 ? "copy" : "copies"}
                    {job.filament_mg
                      ? ` · ${(job.filament_mg / 1000).toFixed(2)} g`
                      : ""}
                    {job.duration_seconds
                      ? ` · ${Math.ceil(job.duration_seconds / 60)} min (slicer estimate)`
                      : ""}
                  </small>
                  {job.estimate && (
                    <>
                      <dl className={styles.costBreakdown}>
                        <div>
                          <dt>Filament · {money(job.estimate.rates.material_rate_paise_per_gram)}/g</dt>
                          <dd>{money(job.estimate.material_paise)}</dd>
                        </div>
                        <div>
                          <dt>Printing · {money(job.estimate.rates.machine_rate_paise_per_hour)}/hr</dt>
                          <dd>{money(job.estimate.machine_paise)}</dd>
                        </div>
                        <div className={styles.costTotal}>
                          <dt>Estimated total</dt>
                          <dd>{money(job.estimate.total_paise)}</dd>
                        </div>
                      </dl>
                      <p className={styles.hint}>
                        Material and print time estimate. Additional services, tax and delivery are not included.
                      </p>
                    </>
                  )}
                  {job.phase === "printing" && (
                    <progress
                      aria-label="Printer progress"
                      value={job.progress}
                      max={1}
                    />
                  )}
                </div>
                <div className={styles.jobActions}>
                  {job.package_sha256 && (
                    <>
                      <a href={`/api/printer/jobs/${job.id}/gcode`}>
                        Download G-code · ZMOD
                      </a>
                      <a href={`/api/printer/jobs/${job.id}/package`}>
                        Download sliced 3MF
                      </a>
                    </>
                  )}
                  {job.phase === "needs_attention" && (
                    <button type="button" onClick={() => void resolve(job)}>
                      I inspected & cleared the printer
                    </button>
                  )}
                </div>
              </article>
            ))
          )}
        </section>
        <footer className={styles.footer}>
          <span>Local network only. No cloud print service.</span>
          <span>
            Use the printer’s screen to pause, cancel or stop a physical print.
          </span>
        </footer>
      </main>
    </div>
  );
}
