# AstroAegis — Crew Health Intelligence

A local-first astronaut health monitoring prototype built around the supplied `thresholds.json` and `diagnostic_rules.json`.

## Included
- English dashboard with color-coded status, vital-sign tiles and sensor threshold indicators.
- Multiple astronaut profiles, unique astronaut IDs, profile management and JSON medical-record import.
- Symptom and mission-context selection using click/tap controls.
- Rule-based assessment using the 32 supplied C01–C32 rules.
- Action guidance, escalation warnings, medication references, QTc warnings and mission-SOP caveats from the supplied rules.
- Import updated `diagnostic_rules.json` and `thresholds.json` through the crew sidebar; the active engine reloads immediately.
- Synthetic sensor generation: nominal, mild, critical, chaos and rule-specific scenarios; repeatable seeds; optional live simulation.
- Per-astronaut history and an exploratory personal trend tab.
- Local persistence in `data/state.json` for the browser version; desktop version persists under `~/Library/Application Support/AstroAegis/state.json`.
- Desktop window support through pywebview, with browser fallback.

## Run on macOS
1. Install Python 3.10 or later.
2. Double-click `start_mac.command` to run in a desktop webview when pywebview is installed, otherwise it opens the browser.
3. To create a standalone macOS `.app`, double-click `build_mac_app.command`. It installs pywebview/PyInstaller and builds `dist/AstroAegis.app`.

For a native window without packaging, install pywebview once:

```bash
python3 -m pip install pywebview
```

## Importing astronaut JSON
Use **Import medical JSON** in the crew sidebar and select a JSON object shaped like the supplied mock profile. The importer reads `astronaut_id`, `personal_information`, `medical_history`, and `pre_flight_baseline`. Baseline cardiovascular values are loaded into the initial vital readings; the full medical record is retained in the astronaut profile.

The sample profile `astraunaut_mock_profile.json` can be imported directly.

## Rule and threshold database
- `data/diagnostic_rules.json`: 32 condition rules C01–C32.
- `data/thresholds.json`: sensor/reference thresholds.
- `data/i18n_en.json`: English UI labels.
- `data/i18n_el.json`: original Greek labels retained for reference.

Use **Update rule database** to import a replacement `diagnostic_rules.json` or `thresholds.json`; the app validates the expected top-level schema and reloads the active engine immediately. Keep the source schema intact and test every change before operational use.

## Tests
From this folder:

```bash
python3 tests/test_system.py
```

## Important operational boundary
AstroAegis is a prototype decision-support and training tool, not a validated autonomous medical device. A rule match is a suspected condition, not a definitive diagnosis. Medication references and terrestrial doses are not mission-approved prescriptions. Any treatment, medication, invasive procedure, or high-consequence action must be governed by an approved mission medical SOP and authorized medical oversight. Simulation data must never be mistaken for live sensor data. The trend tab is a simple exploratory extrapolation, not a validated predictive model.
