"use client";

import dynamic from "next/dynamic";
import { useCallback, useRef, useState, type FormEvent } from "react";
import { UiIcon } from "@/components/ui-icon";
import { canOrientModel } from "@/lib/configured-model";
import { swatchColour, type ModelOptions, type ModelStats } from "@/lib/model-options";
import type { PrintPreset, PrintSettings } from "@/lib/print-specification";
import styles from "@/app/print/station.module.css";
import extra from "./custom-print-builder.module.css";

const ModelPreview = dynamic(() => import("./model-preview"), { ssr: false });
const money = (paise: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(paise / 100);
type Delivery = "pickup" | "local_delivery" | "shipping";
type Props = {
  files: readonly File[]; onFiles: (files: readonly File[]) => void;
  onRemove: (index: number) => void;
  presets: readonly PrintPreset[]; preset?: PrintPreset;
  onPreset: (code: string) => void; colour: string; onColour: (colour: string) => void;
  quantity: string; onQuantity: (quantity: string) => void;
  delivery: Delivery; onDelivery: (delivery: Delivery) => void;
  notes: string; onNotes: (notes: string) => void;
  model: ModelOptions; onModel: (model: ModelOptions) => void;
  pending: boolean; estimating: boolean; prepared: boolean;
  estimatePaise: number | null; error: string | null; status: string;
  presentation?: boolean; queued?: boolean; durationSeconds?: number | null;
  catalogueLoading: boolean; catalogueError: string | null;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function CustomPrintBuilder(props: Props) {
  const { files, preset, presets, model, pending } = props;
  const [open, setOpen] = useState(0);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [stats, setStats] = useState<ModelStats | null>(null);
  const [rotation, setRotation] = useState({ x: "0", y: "0" });
  const [modelError, setModelError] = useState("");
  const upload = useRef<HTMLInputElement>(null);
  const onStats = useCallback((value: ModelStats | null) => setStats(value), []);
  const currentFile = files[previewIndex] ?? files[0];
  const canOrient = files.length > 0 && files.every(canOrientModel);
  const outside = Boolean(stats?.dimensionsMm.some(value => value > 220));
  const materialPresets = presets.filter(item => item.materialCode === preset?.materialCode);
  const layers = [...new Set(materialPresets.map(item => item.settings.layerHeightMm))].sort((a, b) => Number(b) - Number(a));
  const infills = [...new Set(materialPresets.map(item => item.settings.infillPercent))].sort((a, b) => a - b);
  const materials = [...new Set(presets.map(item => item.materialCode))];
  const matchingPreset = (change: Partial<PrintSettings>) => materialPresets.find(item =>
    item.settings.layerHeightMm === (change.layerHeightMm ?? preset?.settings.layerHeightMm) &&
    item.settings.infillPercent === (change.infillPercent ?? preset?.settings.infillPercent) &&
    item.settings.supports === (change.supports ?? preset?.settings.supports));
  function choose(change: Partial<PrintSettings>) {
    const match = matchingPreset(change);
    if (match) props.onPreset(match.code);
  }
  const labels = ["Print quality", "Material & colour", "Infill & supports", "Review & estimate"];
  const summaries = [
    preset ? `${preset.settings.layerHeightMm} mm · ${preset.settings.nozzleDiameterMm} mm nozzle` : "Choose print quality",
    preset ? `${preset.settings.filamentType} · ${props.colour}` : "Choose material",
    preset ? `${preset.settings.infillPercent}% · supports ${preset.settings.supports ? "on" : "off"}` : "Choose infill",
    `${props.quantity} ${props.quantity === "1" ? "copy" : "copies"}`,
  ];
  function selectFiles(next: readonly File[]) {
    if (pending || !next.length) return;
    setPreviewIndex(0); setStats(null); setRotation({ x: "0", y: "0" }); setModelError("");
    props.onFiles(next);
  }
  return <form className={`${styles.columns} ${extra.builder}`} onSubmit={props.onSubmit} noValidate>
    <section className={styles.modelColumn} aria-label="Model preview and orientation">
      <div className={styles.panelHeading}><h2>Your model</h2><span>Up to 100 MiB per file</span></div>
      <div className={styles.preview} onDragOver={event => event.preventDefault()}
        onDrop={event => { event.preventDefault(); selectFiles(Array.from(event.dataTransfer.files)); }}>
        {currentFile ? <ModelPreview file={currentFile} options={model} colour={swatchColour(props.colour)} onStats={onStats} /> :
          <div className={styles.empty}><div className={styles.uploadIcon}><UiIcon name="upload" /></div>
            <h3>A little file. A real possibility.</h3><p>Drop your models here.</p>
            <button className={styles.browse} type="button" onClick={() => upload.current?.click()}>Choose a model <UiIcon name="arrow-up" /></button>
            <span>220 × 220 × 220 mm build volume</span></div>}
      </div>
      <input ref={upload} type="file" accept={props.presentation ? ".stl,.obj" : ".stl,.obj,.3mf,.step,.stp"} multiple={!props.presentation} hidden disabled={pending}
        onChange={event => { selectFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
      {files.length > 0 && <button className={styles.upload} type="button" disabled={pending} onClick={() => upload.current?.click()}>
        <UiIcon name="file" /> Replace models <UiIcon name="arrow-up" /></button>}
      <p className={styles.hint}>{props.presentation ? "STL / OBJ · one model per queue submission · free presentation print" : "STL, OBJ, 3MF, STEP / STP · up to 5 files"} · preview for STL / OBJ up to 16 MiB</p>
      {files.length > 0 && <ul className={extra.files}>{files.map((file, index) => <li key={`${file.name}-${index}`}>
        <span>{file.name}<small>{(file.size / 1048576).toFixed(1)} MiB</small></span>
        <button type="button" disabled={pending} aria-pressed={currentFile === file} onClick={() => { setPreviewIndex(index); setStats(null); }}>Preview</button>
        <button type="button" disabled={pending} onClick={() => { props.onRemove(index); setPreviewIndex(0); setStats(null); }}>Remove</button>
      </li>)}</ul>}
      <fieldset className={styles.units} disabled={pending || !canOrient}><legend>File unit</legend>
        {(["mm", "inch"] as const).map(unit => <label key={unit}><input type="radio" name="model-unit" value={unit}
          checked={model.sourceUnit === unit} onChange={() => props.onModel({ ...model, sourceUnit: unit })} />{unit === "mm" ? "Millimetres" : "Inches"}</label>)}
      </fieldset>
      <div className={styles.rotation}><span>Rotation</span>{(["x", "y"] as const).map(axis => <label key={axis}>{axis.toUpperCase()} <input
        aria-label={`${axis.toUpperCase()} rotation in degrees`} type="number" min={-180} max={180} step={1} disabled={pending || !canOrient}
        value={rotation[axis]} onChange={event => setRotation({ ...rotation, [axis]: event.target.value })} /></label>)}
        <button type="button" disabled={pending || !canOrient} onClick={() => {
          const x = Number(rotation.x), y = Number(rotation.y);
          if (!rotation.x || !rotation.y || ![x, y].every(value => Number.isInteger(value) && value >= -180 && value <= 180)) {
            setModelError("Use whole-degree rotations between −180 and 180."); return;
          }
          props.onModel({ ...model, rotationX: x, rotationY: y }); setModelError("");
        }}>Apply</button></div>
      {modelError && <p className={styles.notice} role="alert">{modelError}</p>}
      {outside && <p className={styles.notice} role="alert">This model exceeds the 220 × 220 × 220 mm build volume. Check its units or orientation.</p>}
      <dl className={styles.stats}><div><dt>Model dimensions</dt><dd>{stats ? `${stats.dimensionsMm.map(value => value.toFixed(2)).join(" × ")} mm` : "Upload a previewable model"}</dd></div>
        <div><dt>Enclosed mesh volume*</dt><dd>{stats ? `${stats.volumeCm3.toFixed(2)} cm³` : "—"}</dd></div>
        <div><dt>Print time, filament & price</dt><dd>Estimated after slicing</dd></div></dl>
      <p className={styles.hint}>*Geometric approximation for closed meshes. Units and applied X/Y rotation are included in the uploaded mesh. Other formats use their existing millimetre orientation.</p>
    </section>
    <section className={styles.configuration} aria-label="Print configuration">
      <div className={styles.configHeading}><h2>Print settings</h2><p>FlashForge AD5X · {preset?.settings.nozzleDiameterMm ?? "0.4"} mm nozzle</p></div>
      {props.catalogueLoading && <p role="status">Loading print options…</p>}
      {props.catalogueError && <p className={styles.notice} role="alert">{props.catalogueError}</p>}
      <div className={styles.accordion}>{labels.map((label, index) => <section key={label}>
        <h3><button type="button" aria-expanded={open === index} aria-controls={`custom-step-${index}`} onClick={() => setOpen(index)}>
          <span className={styles.stepIcon}><UiIcon name={index === 0 ? "layers" : index === 3 ? "check" : "cube"} /></span>
          <span>{label}<small>{summaries[index]}</small></span><b aria-hidden="true">{open === index ? "−" : "+"}</b></button></h3>
        <div id={`custom-step-${index}`} className={styles.step} hidden={open !== index}>
          {index === 0 && <fieldset disabled={pending}><legend>Layer height</legend>{layers.map(layer => <label className={styles.choice} key={layer}>
            <input type="radio" name="layer-height" value={layer} checked={preset?.settings.layerHeightMm === layer}
              disabled={!matchingPreset({ layerHeightMm: layer })} onChange={() => choose({ layerHeightMm: layer })} />
            <span>{Number(layer) === 0.2 ? "Standard" : Number(layer) === 0.15 ? "Fine" : "Detailed"}<small>{layer} mm layers</small></span></label>)}</fieldset>}
          {index === 1 && <div>{materials.map(material => {
            const offering = presets.find(item => item.materialCode === material)!;
            return <div className={styles.material} key={material}><div><strong>{offering.settings.filamentType}</strong><small>Choose your colour</small></div>
              <div className={styles.swatches}>{offering.colours.map(name => <button type="button" key={name} disabled={pending}
                title={`${offering.settings.filamentType} · ${name}`} aria-label={`${offering.settings.filamentType} ${name}`}
                aria-pressed={preset?.materialCode === material && props.colour === name}
                style={{ background: swatchColour(name), color: name === "white" ? "#242724" : "white" }}
                onClick={() => {
                  const next = presets.find(item => item.materialCode === material && item.settings.layerHeightMm === preset?.settings.layerHeightMm &&
                    item.settings.infillPercent === preset?.settings.infillPercent && item.settings.supports === preset?.settings.supports) ?? offering;
                  props.onPreset(next.code); props.onColour(name);
                }}>{preset?.materialCode === material && props.colour === name && <UiIcon name="check" />}</button>)}</div></div>;
          })}</div>}
          {index === 2 && <fieldset disabled={pending}><legend>Infill density</legend><select className={extra.select} aria-label="Infill density"
            value={preset?.settings.infillPercent ?? ""} onChange={event => choose({ infillPercent: Number(event.target.value) })}>
            {infills.map(value => <option key={value} value={value} disabled={!matchingPreset({ infillPercent: value })}>{value}%</option>)}</select>
            <label className={styles.choice}><input type="checkbox" checked={preset?.settings.supports ?? false}
              disabled={!matchingPreset({ supports: !preset?.settings.supports })} onChange={event => choose({ supports: event.target.checked })} />
              <span>Generate supports<small>For overhangs and unsupported details</small></span></label>
            <p className={styles.hint}>Speeds, temperatures and walls use the configured print profile.</p></fieldset>}
          {index === 3 && <>
            <dl className={styles.summary}><div><dt>Models</dt><dd>{files.length ? files.map(file => file.name).join(", ") : "No file selected"}</dd></div>
              <div><dt>Print</dt><dd>{preset ? `${preset.settings.filamentType} · ${props.colour} · ${preset.settings.layerHeightMm} mm · ${preset.settings.infillPercent}%` : "—"}</dd></div>
              <div><dt>Supports</dt><dd>{preset?.settings.supports ? "On" : "Off"}</dd></div></dl>
            <label className={styles.quantity}>Quantity<input aria-label="Quantity" type="number" min={1} max={props.presentation ? 1 : 100} step={1} value={props.quantity}
              disabled={pending} onChange={event => props.onQuantity(event.target.value)} /></label>
            {!props.presentation && <label className={extra.field}>Fulfilment<select value={props.delivery} disabled={pending} onChange={event => props.onDelivery(event.target.value as Delivery)}>
              <option value="pickup">Pickup</option><option value="local_delivery">Local delivery</option><option value="shipping">Pan-India shipping</option></select></label>}
            <label className={extra.field}>Requirements (optional)<textarea maxLength={1000} value={props.notes} disabled={pending} onChange={event => props.onNotes(event.target.value)} /></label>
            <div className={extra.estimate} aria-live="polite"><span>{props.presentation ? "Reference printing cost" : "Estimated total"}</span><strong>{props.estimatePaise !== null ? money(props.estimatePaise) : "—"}</strong>
              <span>Estimated print time</span><strong>{props.durationSeconds ? `${Math.ceil(props.durationSeconds / 60)} min` : "—"}</strong>
              <p>{props.estimating ? "Slicing your model to calculate its cost and print time…" : props.presentation ? "This presentation print is free. Submit your model to the owner waiting list after reviewing its estimate." : props.estimatePaise !== null ? "Print estimate for your selected quantity. Delivery and any additional services are confirmed in the final quotation." : "Get an estimate to see the price for these settings."}</p></div>
            <button className={styles.primary} type="submit" disabled={pending || props.estimating || !files.length || !preset || outside}>
              {pending ? "Submitting…" : props.estimating ? "Calculating estimate…" : props.prepared ? props.presentation ? props.queued ? "View waiting list →" : "Submit to waiting list →" : "View your request →" : "Get estimate →"}</button>
            <p className={styles.hint}>{props.presentation ? "Owner admission adds your model to the work queue." : "Review your final quotation before accepting and paying."}</p>
          </>}
          {index < 3 && <div className={styles.stepNav}><button type="button" className={styles.next} onClick={() => setOpen(index + 1)}>Continue <UiIcon name="arrow" /></button></div>}
        </div>
      </section>)}</div>
      {props.error && <p className={styles.notice} role="alert">{props.error}</p>}
      {props.status && <p className={styles.hint} role="status">{props.status}</p>}
    </section>
  </form>;
}
