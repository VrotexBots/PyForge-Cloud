PYFORGE VISION AI STUDIO — FULL ENGINE UPGRADE
================================================

PURPOSE
This is an additive upgrade to the existing PyForge Vision AI Studio. It does NOT replace the PyForge dashboard or its overall interface. The installer adds controls inside the existing Reference Review and App Preview pages, adds one backend router, and modifies only main.py and dashboard_v2/index.html (with backups).

INCLUDED
- OpenAI-compatible vision model configuration from the owner-only Vision Studio page.
- Secure local provider-key storage (provider.json, file mode 0600); the key is never returned by status endpoints.
- Screenshot analysis: layout, navigation, palette, typography, components, spacing, responsive rules, interactions and accessibility.
- Reference-anchored initial reconstruction and targeted editing; clarification questions when an instruction is ambiguous.
- Original reference images remain immutable.
- Versioned AI edits and edit history.
- Voice recording, transcription, transcript saved as an instruction, and original audio recording saved privately per design.
- Interactive code editor with sandboxed live preview and click-to-select visual element inspection / CSS adjustment.
- Screenshot fidelity comparison against the original reference (requires a screenshot captured from the generated preview).
- AI-generated frontend plus a separate generated FastAPI backend source.
- Automatic structural checks, Python syntax checks, and JavaScript syntax checks when Node.js is installed.
- AI repair workflow for recorded test failures.
- PWA package: HTML, CSS, JS, manifest, service worker and SVG icon.
- Downloadable PWA ZIP after passing tests.
- Explicit publish action to copy a tested app into the selected PyForge project without overwriting existing files.
- Android Studio/Gradle WebView project source ZIP; attempts debug APK compilation only if Gradle and ANDROID_HOME are available.

INSTALL ON TERMUX
1. Copy this ZIP from Downloads to ~/PyForge:
   cp ~/storage/downloads/PyForge_Vision_AI_Studio_Full_Upgrade.zip ~/PyForge/
2. Extract it into the dedicated install folder:
   mkdir -p ~/PyForge/vision_full_install
   unzip -o ~/PyForge/PyForge_Vision_AI_Studio_Full_Upgrade.zip -d ~/PyForge/vision_full_install
3. Run the installer:
   cd ~/PyForge/vision_full_install
   python installer.py
4. The installer reports the timestamped backups and validates Python syntax. It modifies only main.py and dashboard_v2/index.html and adds vision_studio/advanced.py.
5. Restart the API using the existing PyForge supervisor's controlled recovery process. Do not replace the supervisor or Backup Guardian.
6. Sign in to the existing PyForge dashboard, open Vision AI Studio → Reference Review, and enter the provider settings.

AI PROVIDER CONFIGURATION
You must supply your own API key from a provider that supports the OpenAI-compatible Chat Completions vision format and audio transcription endpoint. The default values are:
  Base URL: https://api.openai.com/v1
  Vision/chat model: gpt-4o-mini
  Audio model: whisper-1

The key is saved locally in ~/PyForge/storage/vision_studio/engine/provider.json with owner-only permissions. Never paste it into ChatGPT or share it. Provider usage may incur charges; check the provider's current pricing and account limits.

WORKFLOW
1. Image Upload: select the actual PyForge project, create/select a design, upload the original screenshot.
2. Reference Review: configure provider, analyze the screenshot, then enter an instruction such as “Reconstruct this screenshot faithfully” to generate the initial editable draft. Further commands are targeted changes.
3. App Preview & Download: review/edit HTML/CSS/JS, use visual element selection, preview, build frontend and Python backend, run tests, optionally ask AI to repair failures, then download PWA or explicitly publish to the selected project.
4. Android: create Android project source. If the server has Android SDK, JDK and Gradle correctly configured, the endpoint attempts a debug APK build. Otherwise it provides the source ZIP for Android Studio/Gradle build elsewhere.

IMPORTANT LIMITS — READ BEFORE DEPLOYMENT
- The AI model is genuinely connected only after a valid provider key is saved and the provider accepts the selected models. This package cannot supply paid API credentials.
- “Faithful” is an explicit AI instruction and can be checked with screenshot comparison, but no model can guarantee pixel-perfect reconstruction. Inspect and approve the result.
- Automatic tests are structural and syntax checks, not a full browser end-to-end or security audit. Node.js enables the JavaScript syntax check. Generated apps need human review before public release.
- Generated backend code is a model-produced starting point. Review authentication, database persistence, permissions, input validation, CORS and secrets before exposing it publicly.
- The visual preview runs generated JavaScript in a sandboxed iframe. Still treat generated code as untrusted.
- Android project source generation is included; an APK is not guaranteed on a Termux phone without Android SDK, JDK and compatible Gradle tooling.
- No existing projects are automatically modified during build. The separate Publish action copies a tested build into projects/<selected-project>/pyforge_vision_apps/<design-id> and refuses to overwrite an existing destination.
