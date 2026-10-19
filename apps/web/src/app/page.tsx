import Image from "next/image";
import Link from "next/link";
import styles from "./home.module.css";

export default function Home() {
  return (
    <main className={styles.home} id="top">
      <nav className={styles.nav} aria-label="Main navigation">
        <Link className={styles.brand} href="/" aria-label="PrintFlow 3D home">
          <span className={styles.mark} aria-hidden="true">P</span>
          PrintFlow <span>3D</span>
        </Link>
        <div className={styles.links}>
          <a href="#services">Services</a>
          <a href="#process">Process</a>
          <a href="#contact">Contact</a>
        </div>
        <div className={styles.actions}>
          <Link href="/sign-in">Sign in</Link>
          <Link className={styles.primary} href="/get-a-quote">Get a quote</Link>
        </div>
      </nav>
      <section className={styles.hero} aria-labelledby="hero-title">
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>3D printing, thoughtfully managed</p>
          <h1 id="hero-title">Your next idea.<br />Made tangible.</h1>
          <p className={styles.lead}>
            Private model uploads, reviewed quotations and a clear path from your design to a finished part.
          </p>
          <div className={styles.heroActions}>
            <Link className={styles.primary} href="/get-a-quote">Get a quote</Link>
            <a className={styles.secondary} href="#process">Explore the process</a>
          </div>
        </div>
        <figure className={styles.heroVisual}>
          <Image src="/images/printflow-parts.png"
            alt="Illustrative FDM printed bracket, sculptural vase and architectural model"
            width={1536} height={1024} sizes="(max-width: 760px) 100vw, 52vw" preload />
          <figcaption>Illustrative forms. Every submitted model receives its own review.</figcaption>
        </figure>
      </section>
      <section className={styles.formats} aria-label="Supported model formats">
        <p>Start with the file you already have</p>
        <strong>STL</strong><strong>3MF</strong><strong>OBJ</strong><strong>STEP / STP</strong>
        <span>Private by default</span>
      </section>
      <section className={styles.services} id="services">
        <div className={styles.serviceIntro}>
          <h2>Built for the parts<br />you actually need.</h2>
          <p>Bring a functional prototype, a student project or a custom design.
            We review the geometry and production requirements before confirming a quotation.</p>
        </div>
        <div className={styles.serviceDetails}>
          <article><h3>Functional prototypes</h3>
            <p>Review fit and form with a physical part before committing to your next iteration.</p></article>
          <article><h3>Models and custom forms</h3>
            <p>Turn architectural studies, learning projects and original designs into physical objects.</p></article>
          <article><h3>Small batches</h3>
            <p>Specify quantities and review a quotation that keeps material, machine time and fulfilment visible.</p></article>
        </div>
      </section>
      <section className={styles.process} id="process">
        <h2>A clear process.<br />A reviewed result.</h2>
        <ol>
          <li><h3>Upload your model</h3>
            <p>Sign in and submit supported source files. Files remain private and enter validation before analysis.</p></li>
          <li><h3>Review your quotation</h3>
            <p>Analysis informs the estimate. The owner reviews the requirements and issues the final quotation for you to accept.</p></li>
          <li><h3>Pay and follow progress</h3>
            <p>Server-confirmed payment releases the order to the queue. Follow preparation, quality checks and fulfilment in your account.</p></li>
        </ol>
      </section>
      <section className={styles.contact} id="contact">
        <div><h2>Your project stays<br />in the conversation.</h2>
          <p>Keep model files, quotation decisions and order updates together in your protected account.</p></div>
        <Link className={styles.primary} href="/orders">View your orders</Link>
      </section>
      <footer className={styles.footer}>
        <Link className={styles.brand} href="/">PrintFlow <span>3D</span></Link>
        <p>Secure quotation and production management</p>
        <p>© {new Date().getFullYear()} PrintFlow 3D</p>
      </footer>
    </main>
  );
}
