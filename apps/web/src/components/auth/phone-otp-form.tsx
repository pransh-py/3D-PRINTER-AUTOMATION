"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { AuthApiError, requestPhoneCode, toIndianMobileE164, verifyPhoneCode, type PhoneChallenge } from "@/lib/auth-api";
import { roleHome } from "@/lib/dashboard-api";
import styles from "./auth-form.module.css";

export function PhoneOtpForm({ mode }: { mode: "signup" | "login" }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<PhoneChallenge | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missingAccount, setMissingAccount] = useState(false);
  const [resendAt, setResendAt] = useState(0);
  const [expiresAt, setExpiresAt] = useState(0);
  const [clock, setClock] = useState(0);
  const codeField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!resendAt && !challenge) return;
    const timer = window.setInterval(() => {
      const now = Date.now();
      setClock(now);
      if ((!challenge && now >= resendAt) || (challenge && now >= expiresAt)) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [resendAt, challenge, expiresAt]);
  useEffect(() => { if (challenge) codeField.current?.focus(); }, [challenge]);
  const remaining = Math.max(0, Math.ceil((resendAt - clock) / 1000));
  const expired = !!challenge && clock >= expiresAt;

  function showError(caught: unknown) {
    setError(caught instanceof AuthApiError ? caught.message : "Verification could not be completed. Please try again.");
    setMissingAccount(caught instanceof AuthApiError && caught.status === 404);
    if (caught instanceof AuthApiError && caught.retryAfterSeconds) {
      setClock(Date.now());
      setResendAt(Date.now() + caught.retryAfterSeconds * 1000);
    }
  }

  async function sendCode(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const canonical = toIndianMobileE164(phone);
    if (!canonical) { setError("Enter your 10-digit Indian mobile number or include +91."); return; }
    setPending(true); setError(null); setMissingAccount(false);
    try {
      const issued = await requestPhoneCode({ phone: canonical, purpose: mode,
        ...(mode === "signup" ? { displayName: name.trim() } : {}) });
      const now = Date.now();
      setChallenge(issued); setCode(""); setClock(now);
      setResendAt(now + issued.resendAfterSeconds * 1000);
      setExpiresAt(now + issued.expiresInSeconds * 1000);
    } catch (caught) { showError(caught); }
    finally { setPending(false); }
  }

  async function submitCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!challenge) return;
    setPending(true); setError(null); setMissingAccount(false);
    try {
      const user = await verifyPhoneCode(challenge.challenge, code.trim());
      setCode(""); setChallenge(null);
      router.replace(roleHome(user.role)); router.refresh();
    } catch (caught) { showError(caught); setPending(false); }
  }

  return (
    <div className={styles.form}>
      <p className={styles.help}>Use your WhatsApp number. No email link or buyer password is needed.</p>
      {!challenge ? (
        <form className={styles.form} onSubmit={sendCode}>
          {mode === "signup" ? <div className={styles.field}>
            <label className={styles.label} htmlFor="phone-display-name">Your name</label>
            <input className={styles.input} id="phone-display-name" autoComplete="name" required
              maxLength={100} value={name} onChange={event => setName(event.target.value)} disabled={pending} />
          </div> : null}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="whatsapp-number">WhatsApp number</label>
            <input className={styles.input} id="whatsapp-number" type="tel" inputMode="tel"
              autoComplete="tel" placeholder="+91 90000 00001" required maxLength={24}
              value={phone} onChange={event => setPhone(event.target.value)} disabled={pending}
              aria-describedby="phone-proof-help" />
          </div>
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
          <button className={styles.submit} type="submit" disabled={pending || remaining > 0}>
            {pending ? "Requesting code…" : remaining > 0 ? `Try again in ${remaining}s` : "Send WhatsApp code"}
          </button>
        </form>
      ) : (
        <form className={styles.form} onSubmit={submitCode}>
          <p className={styles.success} role="status">Check WhatsApp for the code for the number ending {toIndianMobileE164(phone)?.slice(-4)}.</p>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="whatsapp-code">Six-digit code</label>
            <input ref={codeField} className={styles.input} id="whatsapp-code" type="text"
              inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6}
              required value={code} onChange={event => setCode(event.target.value)} disabled={pending || expired} />
          </div>
          {expired ? <p className={styles.help}>This code has expired. Request another code below.</p> : null}
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
          {missingAccount ? <Link className={styles.inlineLink} href="/sign-up">Create your buyer account</Link> : null}
          <button className={styles.submit} type="submit" disabled={pending || expired || code.length !== 6}>
            {pending ? "Verifying…" : "Verify and continue"}
          </button>
          <button className={styles.secondaryButton} type="button" disabled={pending || remaining > 0}
            onClick={() => void sendCode()}>{remaining > 0 ? `Resend in ${remaining}s` : "Resend code"}</button>
          <button className={styles.secondaryButton} type="button" disabled={pending} onClick={() => {
            setChallenge(null); setCode(""); setError(null); setResendAt(0); setMissingAccount(false);
          }}>Change number</button>
        </form>
      )}
      <p id="phone-proof-help" className={styles.help}>We’ll send a sign-in code via WhatsApp. Follow order updates in your dashboard.</p>
    </div>
  );
}
