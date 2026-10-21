"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { printEntry } from "@/lib/print-entry";
import { UiIcon } from "./ui-icon";
import styles from "./site-header.module.css";

export function SiteHeader({
  workspace = false,
  dashboard,
  startHref = printEntry(),
}: {
  workspace?: boolean;
  dashboard?: "buyer" | "owner";
  startHref?: "/get-a-quote" | "/print";
}) {
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const account =
    dashboard === "owner"
      ? { label: "Owner dashboard", href: "/operations" }
      : { label: "My orders", href: "/orders" };
  const links = workspace
    ? [
        { label: "Configure print", href: "/print" },
        { label: "Materials", href: "/#materials" },
        { label: "How it works", href: "/#process" },
      ]
    : [
        { label: "What you can make", href: "/#applications" },
        { label: "Materials", href: "/#materials" },
        { label: "How it works", href: "/#process" },
      ];

  return (
    <header
      className={styles.header}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          setOpen(false);
          menuButton.current?.focus();
        }
      }}
    >
      <a className={styles.skip} href="#main-content">
        Skip to content
      </a>
      <div className={styles.bar}>
        <Link className={styles.brand} href="/" aria-label="PrintFlow 3D home">
          <svg width="30" height="32" viewBox="0 0 30 32" aria-hidden="true">
            <path d="m15 1 14 8v15l-14 8L1 24V9L15 1Z" fill="currentColor" />
            <path
              d="m8 12 7-4 7 4-7 4-7-4Zm0 5 7 4 7-4M8 22l7 4 7-4"
              fill="none"
              stroke="var(--surface)"
              strokeWidth="1.7"
              strokeLinejoin="round"
            />
          </svg>
          <span>
            PrintFlow<span className={styles.dimension}>3D</span>
          </span>
        </Link>
        <nav className={styles.desktopNav} aria-label="Main navigation">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={
                workspace && link.href === "/print" ? "page" : undefined
              }
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className={styles.actions}>
          <Link
            className={styles.account}
            href={account.href}
            aria-current={dashboard ? "page" : undefined}
          >
            {account.label}
          </Link>
          {!workspace && (
            <Link className={styles.cta} href={startHref}>
              Start a print <UiIcon name="arrow-up" />
            </Link>
          )}
          <button
            className={styles.menuButton}
            ref={menuButton}
            type="button"
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            aria-controls="mobile-navigation"
            onClick={() => setOpen(!open)}
          >
            <span />
            <span />
          </button>
        </div>
      </div>
      {open && (
        <nav
          id="mobile-navigation"
          className={styles.mobileNav}
          aria-label="Mobile navigation"
        >
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setOpen(false)}
            >
              {link.label}
              <UiIcon name="arrow" />
            </Link>
          ))}
          <Link
            href={account.href}
            onClick={() => setOpen(false)}
            aria-current={dashboard ? "page" : undefined}
          >
            {account.label}
            <UiIcon name="arrow" />
          </Link>
          <Link href="/#faq" onClick={() => setOpen(false)}>
            Questions & answers
            <UiIcon name="arrow" />
          </Link>
        </nav>
      )}
    </header>
  );
}
