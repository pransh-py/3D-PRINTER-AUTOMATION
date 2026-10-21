"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SiteHeader } from "@/components/site-header";
import { PrintSpecificationSummary } from "@/components/quotes/print-specification-summary";
import { getCurrentUserWithRefresh, type AuthenticatedUser } from "@/lib/auth-api";
import { admitPresentation, clearPresentationBed, listPresentationQueue, rejectPresentation, type PresentationEntry, type PresentationQueue } from "@/lib/presentation-api";
import styles from "./presentation-workspace.module.css";

const status: Record<string,string>={waiting:"Waiting for owner",approved:"In work queue",claimed:"Preparing",starting:"Starting print",printing:"Printing",completed:"Printed",needs_attention:"Operator attention required",rejected:"Not admitted",cancelled:"Cancelled",stopped:"Stopped",refused:"Needs configuration review"};
const money=(value:number)=>new Intl.NumberFormat("en-IN",{style:"currency",currency:"INR"}).format(value/100);
const terminal=new Set(["completed","rejected","cancelled","stopped","refused"]);

export function PresentationWorkspace({owner=false}:{owner?:boolean}) {
  const router=useRouter();
  const [user,setUser]=useState<AuthenticatedUser|null>(null);
  const [queue,setQueue]=useState<PresentationQueue|null>(null);
  const [error,setError]=useState("");
  const [refreshError,setRefreshError]=useState("");
  const [pending,setPending]=useState("");
  const [notice,setNotice]=useState("");
  const [tab,setTab]=useState<"waiting"|"work"|"history">(owner?"waiting":"work");
  const [authChecked,setAuthChecked]=useState(false);
  const refresh=useCallback(async()=>{const data=await listPresentationQueue();setQueue(data);setError("");},[]);
  useEffect(()=>{
    let active=true;
    void getCurrentUserWithRefresh(document.cookie).then(value=>{
      if(!active)return;
      if((value.role==="owner")!==owner){router.replace(value.role==="owner"?"/operations":"/orders");return;}
      setUser(value);
    }).catch(()=>{if(active)setError("Please sign in to see your print queue.");}).finally(()=>{if(active)setAuthChecked(true);});
    return()=>{active=false;};
  },[owner,router]);
  useEffect(()=>{
    if(!user)return;
    let active=true;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try{const data=await listPresentationQueue();if(active){setQueue(data);setRefreshError("");}}
      catch(caught){if(active)setRefreshError(caught instanceof Error?caught.message:"Queue refresh failed.");}
      if(active)timer=setTimeout(()=>void poll(),3000);
    };
    void poll();return()=>{active=false;clearTimeout(timer);};
  },[user]);
  async function action(row:PresentationEntry,kind:"admit"|"reject"|"clear") {
    if(pending)return;
    let reason="";
    if(kind==="reject") {reason=window.prompt("Reason for not admitting this model:")?.trim()??"";if(!reason)return;}
    if(kind==="clear"&&!window.confirm(`Start ${row.filenames.join(", ")} when the printer is ready?\n\nOperator: confirm the finished part is removed, plate installed and clear, the 0.4 mm nozzle and selected filament/IFS slot are correct, the model settings reviewed, and someone is supervising. This clearance is for this model only.`))return;
    setPending(row.id);setError("");setNotice("");
    try {
      if(kind==="admit"){await admitPresentation(row);setNotice("Model admitted to the work queue.");}
      if(kind==="reject")await rejectPresentation(row,reason);
      if(kind==="clear"){await clearPresentationBed(row);setNotice("Bed clearance recorded. The service will send this model once.");}
      await refresh();
    }catch(caught){setError(caught instanceof Error?caught.message:"The queue could not be updated.");}
    finally{setPending("");}
  }
  const items=queue?.items??[];
  const waiting=items.filter(row=>row.status==="waiting");
  const work=items.filter(row=>row.status!=="waiting"&&!terminal.has(row.status)).sort((a,b)=>(a.approvedAt??"").localeCompare(b.approvedAt??"")||a.id.localeCompare(b.id));
  const history=items.filter(row=>terminal.has(row.status));
  const visible=owner?(tab==="waiting"?waiting:tab==="work"?work:history):items;
  return <><SiteHeader presentation dashboard={owner?"owner":"buyer"}/><main className={styles.page} id="main-content">
    <header className={styles.heading}><div><p>FREE PRESENTATION PRINTING</p><h1>{owner?"Your print desk.":"Your models, in motion."}</h1>
      <p>{owner?"Admit waiting models, then keep the work queue moving.":"See when your model is admitted, prepared and printed."}</p></div>
      <Link className={styles.primary} href={owner?"/account":"/get-a-quote"}>{owner?"Account & operator MFA":"Upload a model →"}</Link></header>
    {!authChecked?<p>Checking your account…</p>:!user?<p><Link href="/sign-in">Sign in to continue</Link></p>:<>
      <div className={styles.station}><strong>Printer · {queue?.station.state??"checking"}</strong>
        <span>{queue?.station.state==="offline"?"Requests stay queued until the local printer service reconnects.":queue?.station.activeEntryId?"A model is in progress. The next plate needs removal and fresh clearance.":"The service sends the next admitted model after owner bed clearance."}</span></div>
      {owner&&<nav className={styles.tabs} aria-label="Print desk"><button aria-pressed={tab==="waiting"} onClick={()=>setTab("waiting")}>Waiting list ({waiting.length})</button><button aria-pressed={tab==="work"} onClick={()=>setTab("work")}>Work queue ({work.length})</button><button aria-pressed={tab==="history"} onClick={()=>setTab("history")}>History ({history.length})</button></nav>}
      {notice&&<p role="status">{notice}</p>}
      {!queue?<p>Loading print queue…</p>:!visible.length?<p className={styles.empty}>{owner?"No models in this list yet.":"Get an estimate and submit your first model to the waiting list."}</p>:<div className={styles.entries}>{visible.map(row=><article className={styles.entry} key={row.id} id={`print-${row.id}`}>
        <div className={styles.entryHead}><h2>{row.filenames.join(", ")}</h2><span>{status[row.status]}</span></div>
        <PrintSpecificationSummary value={row.specification}/>
        <dl className={styles.facts}><div><dt>Estimated print time</dt><dd>{Math.ceil(row.durationSeconds/60)} min</dd></div><div><dt>Reference printing cost</dt><dd>{money(row.referenceCostPaise)}</dd></div><div><dt>This presentation</dt><dd>Free</dd></div></dl>
        {row.status==="printing"&&<p>Printing · {Math.floor(row.progressBps/100)}%<progress max={10000} value={row.progressBps} aria-label="Print progress"/></p>}
        {row.reason&&<p role="status">{row.reason.replaceAll("_"," ")}</p>}
        {owner&&row.status==="waiting"&&<div className={styles.actions}><button className={styles.primary} disabled={Boolean(pending)} onClick={()=>void action(row,"admit")}>Admit to work queue</button><button disabled={Boolean(pending)} onClick={()=>void action(row,"reject")}>Decline</button></div>}
        {owner&&row.status==="approved"&&queue.station.nextEntryId===row.id&&<div className={styles.actions}><button className={styles.primary} disabled={Boolean(pending)||queue.station.state!=="ready"||Boolean(queue.station.activeEntryId)||queue.station.clearedEntryId===row.id} onClick={()=>void action(row,"clear")}>{queue.station.clearedEntryId===row.id?"Waiting for automatic start…":"Plate clear · allow next print"}</button><small>{queue.station.state==="offline"?"Connect the printer to continue.":"Remove the previous part before allowing the next print."}</small></div>}
        {!owner&&row.status==="waiting"&&<p>Submitted. The owner can admit your model without another quotation step.</p>}
      </article>)}</div>}
    </>}{(error||refreshError)&&<p className={styles.error} role="alert">{error||refreshError} {user&&<button onClick={()=>void refresh().then(()=>setRefreshError("")).catch(()=>{})}>Retry</button>}</p>}
  </main></>;
}
