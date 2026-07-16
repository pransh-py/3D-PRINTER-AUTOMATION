import Link from "next/link";

import styles from "./auth-form.module.css";

type AuthShellLink = {
  label: string;
  href: string;
};

type AuthShellProps = Readonly<{
  kicker: string;
  title: string;
  description: string;
  children: React.ReactNode;
  footerLinks?: AuthShellLink[];
}>;

export function AuthShell({
  kicker,
  title,
  description,
  children,
  footerLinks = [],
}: AuthShellProps) {
  return (
    <main className={styles.shell}>
      <Link className={styles.wordmark} href="/" aria-label="xxx home">
        xxx<span>.</span>
      </Link>
      <section className={styles.card}>
        <p className={styles.kicker}>{kicker}</p>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.description}>{description}</p>
        {children}
        {footerLinks.length > 0 && (
          <nav className={styles.footerLinks} aria-label="Account options">
            {footerLinks.map((link) => (
              <Link key={link.href} className={styles.footerLink} href={link.href}>
                {link.label}
              </Link>
            ))}
          </nav>
        )}
      </section>
    </main>
  );
}
