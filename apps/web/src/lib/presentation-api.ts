import { getCurrentUserWithRefresh, readCsrfCookie } from "./auth-api.ts";
import { parsePrintSpecification, type PrintSpecification } from "./print-specification.ts";
import type { QuoteRequest } from "./quote-api.ts";

export type PresentationEntry = {
  id: string; requestId: string; status: string; version: number; filenames: string[];
  referenceCostPaise: number; durationSeconds: number; specification: PrintSpecification | null;
  submittedAt: string; approvedAt: string | null; progressBps: number; reason: string | null; free: true;
};
export type PresentationQueue = {
  items: PresentationEntry[]; free: true;
  station: { state: "ready" | "busy" | "offline"; activeEntryId: string | null; nextEntryId: string | null; clearedEntryId: string | null };
};
const states = new Set(["waiting","approved","claimed","starting","printing","completed","needs_attention","rejected","cancelled","stopped","refused"]);
const record = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === "object" && !Array.isArray(value));
const id = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);

export function parsePresentationEntry(value: unknown): PresentationEntry {
  if (!record(value) || !id(value.id) || !id(value.requestId) || typeof value.status !== "string" || !states.has(value.status)
    || !Number.isInteger(value.version) || Number(value.version)<1 || !Array.isArray(value.filenames) || !value.filenames.every(v=>typeof v==="string")
    || !Number.isInteger(value.referenceCostPaise) || Number(value.referenceCostPaise)<0
    || !Number.isInteger(value.durationSeconds) || Number(value.durationSeconds)<=0
    || !Number.isInteger(value.progressBps) || Number(value.progressBps)<0 || Number(value.progressBps)>10000
    || value.free!==true || typeof value.submittedAt!=="string" || (value.approvedAt!==null && typeof value.approvedAt!=="string")
    || (value.reason!==null && typeof value.reason!=="string")) throw new Error("The print queue returned invalid information. Refresh and try again.");
  return {...value, specification:parsePrintSpecification(value.specification)} as PresentationEntry;
}

async function request(path: string, body?: object, canRefresh = true): Promise<unknown> {
  const headers: Record<string,string> = {Accept:"application/json"};
  if (body) {
    const token=readCsrfCookie(document.cookie);
    if (!token) throw new Error("Please sign in again before changing the print queue.");
    headers["X-CSRF-Token"]=token;headers["Content-Type"]="application/json";
  }
  const response=await fetch(`/api/v1/presentation${path}`,{method:body?"POST":"GET",headers,body:body?JSON.stringify(body):undefined,credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(15000)});
  if (response.status === 401 && canRefresh) {
    await getCurrentUserWithRefresh(document.cookie);
    return request(path, body, false);
  }
  const value:unknown=await response.json();
  if (!response.ok) throw new Error(record(value)&&typeof value.detail==="string"?value.detail:"The print queue could not be updated. Please try again.");
  return value;
}

export async function listPresentationQueue(): Promise<PresentationQueue> {
  const data=await request("/entries");
  if (!record(data)||!Array.isArray(data.items)||data.free!==true||!record(data.station)||!["ready","busy","offline"].includes(String(data.station.state))
    || !["activeEntryId","nextEntryId","clearedEntryId"].every(key=>data.station && record(data.station) && (data.station[key]===null||id(data.station[key])))) throw new Error("The station status is unavailable. Refresh to try again.");
  return {items:data.items.map(parsePresentationEntry),free:true,station:data.station as PresentationQueue["station"]};
}

export async function joinPresentationQueue(quote: QuoteRequest) {
  if (!quote.latestEstimate) throw new Error("Wait for the measured estimate before submitting.");
  return parsePresentationEntry(await request("/entries",{requestId:quote.id,estimateId:quote.latestEstimate.id,expectedVersion:quote.version}));
}

export async function admitPresentation(entry: PresentationEntry) {
  return parsePresentationEntry(await request(`/entries/${entry.id}/admit`,{expectedVersion:entry.version}));
}

export async function rejectPresentation(entry: PresentationEntry, reason: string) {
  return parsePresentationEntry(await request(`/entries/${entry.id}/reject`,{expectedVersion:entry.version,reason}));
}

export async function clearPresentationBed(entry: PresentationEntry) {
  await request(`/entries/${entry.id}/clearance`,{expectedVersion:entry.version,bedClear:true,materialLoaded:true,nozzleChecked:true,areaClear:true,artifactReviewed:true});
}
