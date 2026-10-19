import Image from "next/image";
import Link from "next/link";
import { SiteHeader } from "@/components/site-header";
import { MaterialExplorer } from "@/components/home-interactions";
import { UiIcon } from "@/components/ui-icon";
import styles from "./home.module.css";

const QUESTIONS = [
  [
    "What files can I upload?",
    "The local print workspace accepts STL and OBJ files up to 100 MiB. You can preview files up to 16 MiB, choose millimetres or inches, and adjust orientation before slicing.",
  ],
  [
    "How do I choose a material?",
    "PLA is a starting point for prototypes and display models. PETG suits many functional prototypes. Choose from the configured profiles and confirmed colours; suitability for your specific use still needs review.",
  ],
  [
    "Can I see the time and material needed?",
    "Yes. After slicing, the workspace shows the print duration and filament use reported by OrcaSlicer. These depend on your actual model and selected settings.",
  ],
  [
    "Will uploading start the printer?",
    "Uploading prepares your model. Physical starts are disabled by default and require a commissioned printer, reviewed profiles and an operator’s readiness confirmation for each job.",
  ],
  [
    "Can I print more than one copy?",
    "You can arrange up to ten copies on a single build plate, provided they fit. Someone must remove the finished parts and prepare the bed before the next print.",
  ],
];

export default function Home() {
  return (
    <div className={styles.home} id="top">
      <SiteHeader />
      <main id="main-content">
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroCopy}>
            <h1 id="hero-title">
              Your file.
              <br />
              Made{" "}
              <span className={styles.pictureWord}>
                <Image
                  src="/images/printed-bracket.png"
                  alt=""
                  width={1448}
                  height={1086}
                  sizes="150px"
                />
              </span>{" "}
              real.
            </h1>
            <p className={styles.lead}>
              3D printing for the things you imagine.
              <br className={styles.desktopBreak} /> From a first prototype to a
              form all your own.
            </p>
            <div className={styles.heroActions}>
              <Link className={styles.primary} href="/print">
                Start a print
                <UiIcon name="arrow-up" />
              </Link>
              <a className={styles.textLink} href="#process">
                See how it works
                <UiIcon name="arrow" />
              </a>
            </div>
            <p className={styles.uploadNote}>
              <UiIcon name="file" /> Bring your STL or OBJ. We’ll take it from
              there.
            </p>
          </div>
          <figure className={styles.heroVisual}>
            <div className={styles.imageShutter}>
              <Image
                src="/images/printed-knot.png"
                alt="An illustrative orange printed knot with tactile, visible filament layers"
                width={1536}
                height={1024}
                sizes="(max-width: 780px) 100vw, 55vw"
                preload
              />
            </div>
          </figure>
        </section>

        <section className={styles.intro} aria-labelledby="intro-title">
          <h2 id="intro-title" data-reveal>
            A little file.
            <br />A lot of potential.
          </h2>
          <div data-reveal>
            <p>
              That part on your screen? It could be a prototype for your next
              test, a model for your next presentation, or something that
              doesn’t exist anywhere else.
            </p>
            <p>
              PrintFlow brings your model, material and print settings into one
              straightforward workspace.
            </p>
          </div>
        </section>

        <section
          className={styles.applications}
          id="applications"
          aria-labelledby="applications-title"
        >
          <div className={styles.sectionHead}>
            <h2 id="applications-title" data-reveal>
              What will you make?
            </h2>
            <p data-reveal>
              A practical part. A new perspective.
              <br />A reason to keep making.
            </p>
          </div>
          <div className={styles.applicationGrid}>
            <article data-reveal>
              <Link
                href="/print"
                className={styles.applicationImage}
                aria-label="Start a functional prototype"
              >
                <Image
                  src="/images/printed-bracket.png"
                  alt="Illustrative black FDM mounting bracket with structural ribs and screw holes"
                  width={1448}
                  height={1086}
                  sizes="(max-width: 780px) 100vw, 58vw"
                />
                <span className={styles.imageAction}>
                  <UiIcon name="arrow-up" />
                </span>
              </Link>
              <div>
                <h3>Make it work.</h3>
                <p>
                  Brackets, housings and prototypes.
                  <br />
                  Put your next iteration in your hands.
                </p>
              </div>
            </article>
            <article className={styles.architecture} data-reveal>
              <Link
                href="/print"
                className={styles.applicationImage}
                aria-label="Start an architectural or display model"
              >
                <Image
                  src="/images/printed-house.png"
                  alt="Illustrative white architectural house model showing fine FDM layers"
                  width={1448}
                  height={1086}
                  sizes="(max-width: 780px) 100vw, 42vw"
                />
                <span className={styles.imageAction}>
                  <UiIcon name="arrow-up" />
                </span>
              </Link>
              <div>
                <h3>Make it seen.</h3>
                <p>
                  Architectural studies, display pieces and
                  <br className={styles.desktopBreak} /> ideas that deserve
                  another dimension.
                </p>
              </div>
            </article>
          </div>
        </section>

        <section
          className={styles.materials}
          id="materials"
          aria-labelledby="materials-title"
        >
          <div className={styles.sectionHead}>
            <h2 id="materials-title" data-reveal>
              Meet your materials.
            </h2>
            <p data-reveal>
              PLA and PETG. Pick your colour.
              <br />
              Find a starting point for your part.
            </p>
          </div>
          <MaterialExplorer />
        </section>

        <section
          className={styles.process}
          id="process"
          aria-labelledby="process-title"
        >
          <div className={styles.processIntro} data-reveal>
            <h2 id="process-title">
              A simpler path
              <br />
              to a real thing.
            </h2>
            <p>
              Keep your idea in focus.
              <br />
              The workspace handles the details.
            </p>
            <Link className={styles.lightButton} href="/print">
              Open print workspace
              <UiIcon name="arrow-up" />
            </Link>
          </div>
          <ol className={styles.processList}>
            <li data-reveal>
              <UiIcon name="upload" />
              <div>
                <h3>Bring your model.</h3>
                <p>
                  Upload an STL or OBJ. Explore the preview and check its size
                  and orientation.
                </p>
              </div>
            </li>
            <li data-reveal>
              <UiIcon name="layers" />
              <div>
                <h3>Make it your own.</h3>
                <p>
                  Choose a material, colour and layer height. Set the infill,
                  supports and number of copies.
                </p>
              </div>
            </li>
            <li data-reveal>
              <UiIcon name="cube" />
              <div>
                <h3>Slice. Review. Print.</h3>
                <p>
                  See the slicer’s time and filament estimate. A prepared
                  printer and operator confirmation come before any physical
                  start.
                </p>
              </div>
            </li>
          </ol>
        </section>

        <section
          className={styles.questions}
          id="faq"
          aria-labelledby="questions-title"
        >
          <div data-reveal>
            <h2 id="questions-title">
              Before the
              <br />
              first layer.
            </h2>
            <p>
              A few things you might
              <br />
              be wondering about.
            </p>
          </div>
          <div className={styles.questionList}>
            {QUESTIONS.map(([question, answer]) => (
              <details key={question} data-reveal>
                <summary>
                  {question}
                  <UiIcon name="chevron" />
                </summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </section>

        <section className={styles.closing} aria-labelledby="closing-title">
          <h2 id="closing-title" data-reveal>
            Your next idea
            <br />
            starts with a file.
          </h2>
          <div data-reveal>
            <p>
              Open the workspace.
              <br />
              See what you can make.
            </p>
            <Link className={styles.primary} href="/print">
              Let’s make it real
              <UiIcon name="arrow-up" />
            </Link>
          </div>
        </section>
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerTop}>
          <p>3D printing, made in Chennai.</p>
          <nav aria-label="Footer navigation">
            <Link href="/print">Print workspace</Link>
            <Link href="/get-a-quote">Request a quote</Link>
            <Link href="/orders">My orders</Link>
            <a href="#top">
              Back to top
              <UiIcon name="arrow-up" />
            </a>
          </nav>
        </div>
        <Link
          href="/"
          className={styles.footerWordmark}
          aria-label="PrintFlow 3D home"
        >
          PrintFlow<span>3D</span>
        </Link>
        <div className={styles.footerBottom}>
          <span>© {new Date().getFullYear()} PrintFlow 3D</span>
          <span>Printed-part imagery is illustrative.</span>
          <span>One idea at a time.</span>
        </div>
      </footer>
    </div>
  );
}
