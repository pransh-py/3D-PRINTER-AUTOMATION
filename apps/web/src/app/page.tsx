import Link from "next/link";

const processSteps = [
  {
    number: "01",
    title: "Upload your model",
    body: "Send an STL, 3MF, OBJ, or STEP file through your private account.",
  },
  {
    number: "02",
    title: "Review the quote",
    body: "We analyse material and print time, then the owner confirms the final price.",
  },
  {
    number: "03",
    title: "Pay and track",
    body: "Pay by UPI after approval and follow your order from queue to delivery.",
  },
];

const capabilities = [
  "Functional prototypes",
  "Replacement parts",
  "Student projects",
  "Custom gifts",
  "Single and small batches",
  "Pickup and India-wide shipping",
];

export default function Home() {
  return (
    <main>
      <section className="hero-shell">
        <nav className="site-nav" aria-label="Main navigation">
          <a className="wordmark" href="#top" aria-label="xxx home">
            xxx<span>.</span>
          </a>
          <div className="nav-links">
            <a href="#services">Services</a>
            <a href="#process">Process</a>
            <a href="#contact">Contact</a>
          </div>
          <div className="nav-actions">
            <Link className="text-link" href="/sign-in">
              Sign in
            </Link>
            <Link className="button button-small" href="/get-a-quote">
              Get a quote
            </Link>
          </div>
        </nav>

        <div className="hero" id="top">
          <div className="eyebrow">3D PRINTING · CHENNAI</div>
          <h1>
            Your model,
            <br />
            made <em>real.</em>
          </h1>
          <p className="hero-copy">
            Upload a design, receive a clear reviewed quote, and let us print it
            on our FlashForge AD5X. From one-off ideas to small production runs.
          </p>
          <div className="hero-actions">
            <Link className="button" href="/get-a-quote">
              Upload a model <span aria-hidden="true">↗</span>
            </Link>
            <a className="secondary-link" href="#process">
              See how it works <span aria-hidden="true">↓</span>
            </a>
          </div>
          <div className="hero-proof" aria-label="Service highlights">
            <div>
              <strong>4</strong>
              <span>supported model formats</span>
            </div>
            <div>
              <strong>₹</strong>
              <span>transparent reviewed pricing</span>
            </div>
            <div>
              <strong>IN</strong>
              <span>pickup and pan-India shipping</span>
            </div>
          </div>
        </div>
        <div className="hero-object" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="printed-form">
            <span />
            <span />
            <span />
            <span />
          </div>
          <p>BUILT LAYER BY LAYER</p>
        </div>
      </section>

      <section className="section services" id="services">
        <div className="section-heading">
          <p className="section-kicker">WHAT WE MAKE</p>
          <h2>Ideas deserve a physical form.</h2>
          <p>
            Precision FDM printing for creators, engineers, students, and
            businesses—without confusing pricing or back-and-forth.
          </p>
        </div>
        <div className="capability-grid">
          {capabilities.map((capability, index) => (
            <article key={capability}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <h3>{capability}</h3>
            </article>
          ))}
        </div>
      </section>

      <section className="section process" id="process">
        <div className="section-heading light">
          <p className="section-kicker">A SIMPLE PROCESS</p>
          <h2>From file to finished part.</h2>
        </div>
        <div className="process-grid">
          {processSteps.map((step) => (
            <article key={step.number}>
              <span>{step.number}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section closing" id="contact">
        <p className="section-kicker">START YOUR PRINT</p>
        <h2>Have a model ready?</h2>
        <p>
          Create a quote request now. We will analyse the model and confirm the
          final price before you pay anything.
        </p>
        <Link className="button" href="/get-a-quote">
          Get a quote <span aria-hidden="true">↗</span>
        </Link>
      </section>

      <footer>
        <a className="wordmark" href="#top">
          xxx<span>.</span>
        </a>
        <p>3D printing in Chennai · Pickup, delivery, and shipping across India</p>
        <p>© {new Date().getFullYear()} xxx</p>
      </footer>
    </main>
  );
}
