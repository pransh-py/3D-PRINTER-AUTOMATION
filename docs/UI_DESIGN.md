# PrintFlow interface redesign

20 October 2026. Local repository implementation. The design-only review below preceded
the later Windows/WSL and physical-printer work recorded in
[Windows local testing](WINDOWS_LOCAL_TESTING.md).

## Direction and references

The redesign keeps Next.js, CSS modules, the bundled Geist font, and the existing printing and business services. Design tooling is not required to build or run the application.

References studied:

- [Craftcloud](https://craftcloud3d.com/): a prominent upload entry point and a model → material → next-action structure. Its page content was retrieved; browser access to this reference was declined.
- [Weerg](https://www.weerg.com/): large physical-part imagery, visible action buttons, material navigation and a clear production process. The rendered first screen was inspected.
- [Sculpteo](https://www.sculpteo.com/en/): explanations of materials, file preparation, and questions before uploading.
- [Xometry](https://www.xometry.com/capabilities/3d-printing-service/): a clear model-upload action and capability information that helps visitors decide what to do next.

These inform the information hierarchy. No competitor copy, photographs, testimonials, logos, prices, lead times or certifications were copied.

The homepage direction is **The sentence is the layout**, seed **43990036**, because a tangible printed part can sit inside the sentence “Your file. Made real.” The inline bracket and large orange knot make the file-to-object transition visible. The original direction sheet is `.local/design/taste/direction.json`. The printing screen uses **Framed sheet**, seed **1688501930**, with an inset working surface, quiet controls and a model canvas. Its sheet is `.local/design/app/direction.json`. Existing orange and neutral brand colours were refined, and Geist was retained.

The live element is the material explorer: choose PLA or PETG and a confirmed colour, then carry those selections into `/print`. Only valid material/colour combinations are accepted from the URL. This does not commission a profile or authorize printing.

## Subject inventory and content argument

The design is grounded in PrintFlow's actual constraints: Chennai, a single AD5X, STL/OBJ input, 100 MiB upload limit, 16 MiB interactive-preview limit, millimetres/inches, X/Y orientation, a 0.4 mm nozzle, three layer heights, confirmed PLA and PETG stock, one build plate, up to ten copies, and real slicer measurements. No business rates, production history or customer statistics have been invented.

The page follows these claims and evidence:

1. A digital file can become a tangible object: printed-part illustrations and an immediate print-workspace action.
2. Models have practical and visual uses: distinct bracket and architectural-model images.
3. Material is a deliberate choice: an interactive PLA/PETG comparison and the confirmed colour combinations.
4. The workflow has understandable stages: upload, configure, slice/review/print.
5. Visitors can understand the limits before starting: full answers about files, materials, metrics and physical starts.
6. A clear next action remains available: workspace links, quotation access and the existing order area.

## Implemented surfaces

- Responsive shared navigation with a mobile menu, skip link and accessible controls.
- New homepage with application imagery, material exploration, process, FAQ and a large wordmark close.
- A new print-workspace shell around the existing model preview, units, rotations, quality, infill, supports, quantity, dispatch checks, downloads and job activity.
- Explicit offline state and reconnect control. A disconnected service is not presented as a ready printer or an empty saved history.
- Light appearance by default, with the existing dark-appearance control retained.
- Image entrance, gentle image motion and native scroll reveals, with a reduced-motion fallback and readable content without JavaScript.
- The station-mode root now shows the homepage; `/print` remains the working screen. The printer proxy remains restricted to explicit station mode.

The public business workflow and its authentication, quotation, payment and order contracts remain intact. The design-only work did not change the Unix-specific launcher; the subsequent Windows setup runs it inside Ubuntu WSL, as documented in the local testing guide.

## Image provenance

The following new project assets were generated with the built-in image-generation tool. They are illustrative sample forms, not evidence of completed customer work. A small footer note identifies the imagery as illustrative. Existing `printflow-parts.png` is also retained and described as illustrative.

| Asset under `apps/web/public/images` | Prompt brief | Placement |
| --- | --- | --- |
| `printed-knot.png` | Photorealistic vermilion-orange FDM sculptural knot; interlocking rounded loops; visible layer lines; pale grey seamless ground; three-quarter studio light; no text, logos or equipment. | Main hero |
| `printed-bracket.png` | Matte charcoal FDM mounting bracket with triangular ribs, shaft hole and mounting holes; visible layers; pale grey studio ground; no text or branding. | Inline headline image, functional-use section, PETG illustration |
| `printed-house.png` | White FDM architectural maquette with stepped volumes, deep openings and a small staircase; visible layers; grey studio ground; no people or branding. | Architecture/display section |

No external stock photographs or video were imported for these generated assets. Product imagery remains illustrative and is not a calibrated representation of a particular material profile.

## Verification and visual review boundary

The initial page was inspected at 1440, 768 and 390 px; its measurements and screenshots are in `.local/design/before`. An intermediate redesigned page was also captured at all three widths under `.local/design/after`, before browser access was blocked. Its measured hero occupied two lines at every width, used the loaded Geist font, and had no horizontal overflow or broken images. It contained five image elements using four distinct assets.

### Review of the captured intermediate version

ROUND 1

Seen in one second: a printing service with a direct action and a large physical object.

Idea (one sentence): PrintFlow's file-to-object workflow becomes a sentence with a printed part inside it.

Live thing: material and colour choices that lead into the print workspace.

Layout words by section: hero=sentence plus object / applications=offset images / materials=working selector / process=instructional split / FAQ=expandable answers / close=short invitation / footer=wordmark.

Scores: no final visual scores claimed. The captured intermediate meter reported three failures and four warnings; the final corrected version could not be re-inspected.

Caps applied: the intermediate motion failure prevents treating that version as accepted under Taste's visual gate.

Top three problems and changes:

1. The initial render followed the system's dark appearance rather than the intended light direction (`after/desktop-fold.jpg`). The final document defaults to light and retains the explicit dark toggle.
2. Colour-choice inset shadows failed the flat-control rule. They were replaced with a visible selection outline; the white swatch retains a necessary edge for contrast.
3. The caption was misread as an eyebrow on narrow screens, and the scripted reveals did not register as intended. The caption was removed, and the final source uses native scroll animations with reduced-motion support.

The final page and app source pass Taste's static lint without failures. The retained page swatch-edge warning is justified by the need to distinguish white filament from the paper surface; the app's `padStart(2, "0")` warning is required SHA-256 byte encoding, not decorative index numbering. Final browser interaction tests and a final zero-failure Taste render are **not verified**. A saved browser permission blocks `http://127.0.0.1:3100`, including after the user approved local preview checks in chat. This was not worked around with another browser or protocol.

Code checks passed: TypeScript, ESLint (one pre-existing account-navigation warning), all 41 existing frontend unit tests, and the optimized Next.js builds in both ordinary and station mode. The accent was also checked numerically for readable white button text in both appearances. Browser file upload, mobile-menu interaction, final light/dark rendering and real service/printer integration need a permitted local browser session. No real print was started, no production PrintFlow service was contacted and no production payment was enabled.

## Local review

From the repository root, run:

```powershell
npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3100
```

Open `http://127.0.0.1:3100` for the homepage or `/print` for the configurator. This frontend-only preview intentionally reports the unavailable print service; local model preview and configuration do not require a fake printer response. The real station is launched through the existing tools on a supported operating system, on its configured loopback ports. The agent's temporary development server was stopped after code verification.
