# CoolCorridor deployment guide

> Merge update: numerical results and packaging below describe the pre-merge release. See [merge resolution](merge_resolution.md) for the current `a64cdcf` integration, recalculated Planner and routing results, active correction bundle and deployment snapshot. Previous browser/cloud evidence does not verify this merged build.

Prepared 21 October 2026. **Nothing has been published.** Commit, push, merge,
account authorization, app creation and visibility changes require user approval.
Use the accompanying [readiness evidence](deployment_readiness.md) and
[three-minute demo](hackathon_demo.md).

## Recommended target

Use **Streamlit Community Cloud**, subject to repository-owner access and the
post-approval Linux/cloud smoke test. The application uses Streamlit directly,
has no database or persistent sensor process, and reads a small frozen dataset.
The existing exact pins installed successfully in a fresh Windows Python 3.13.5
environment; all 45 dependency wheels also resolved for CPython 3.13 manylinux
x86_64. Linux execution has not been performed on this machine.

Community Cloud runs Linux, recognizes root `requirements.txt`, and lets the
owner select Python under Advanced settings. Choose **Python 3.13 explicitly**;
do not accept a different default or silently relax package pins.
[Official dependency guidance](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies),
[deployment settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

Private GitHub repositories are supported, but the deploying person needs repo
admin permissions and must authorize private-repository access. Organization
access may require the organization owner. These account permissions have not
been verified or changed. A private repository does not need to be made public.
[Official GitHub access requirements](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account).

An app created from a private repository initially inherits private visibility.
The owner must approve either invited-judge access or a public demo app. The
current documentation allows one private app at a time; check the owner's
available slot. App visibility and repository visibility are separate decisions.
[Official sharing guidance](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app).

## Byte-preserving runtime

**Cloud entrypoint: `streamlit_app.py`, not `app.py`.** The latter remains the
unchanged development app. Correction provenance validates exact source/data
bytes; ordinary Windows-to-Linux Git checkout can change line endings and make
the raw checkout fail that validation.

`deployment_package.py` builds a deterministic ZIP from an explicit 24-file
allowlist. The ZIP contains the real app, required Python modules, six source
data files, simulator config, correction pointer and the five active correction
artifacts. It excludes historical versions/results, tests, buildings, caches,
virtual environments, Git metadata, screenshots, personal files and secrets.
`.gitattributes` marks deployment ZIPs binary so Git preserves their bytes.

`streamlit_app.py` validates the external package manifest, ZIP SHA-256, exact
membership and every member's size/hash. It extracts to a version directory
under the operating system's temporary storage, rechecks extracted bytes and
executes the packaged real app. The original correction reader then checks its
own provenance, all 1,491 links × 13 hours and source labels. No sensor generation,
correction generation or canonical-data replacement occurs at startup.

The temporary extraction may disappear on a cloud restart; the tracked ZIP is
the durable input. It is safe to reconstruct the same verified bytes. Corrupt
existing extractions fail explicitly instead of being silently repaired.
Windows publication retries transient directory sharing failures for at most
1.4 seconds; persistent errors remain visible. No ignored `cache/` file is a
runtime dependency.

This release is frozen. Editing checkout `app.py` does not change the packaged
app. After a reviewed runtime change, explicitly build into a **new unused**
directory, validate it and replace the deployment pointer/package only as a
reviewed release operation. Never regenerate a different heat model on a host
merely to make a hash check pass.

## Required deployment files

The exact ZIP filename, SHA-256, 24 member paths and byte sizes are recorded in
`deployment/package_manifest.json` and [deployment_readiness.md](deployment_readiness.md).
A minimal cloud checkout needs:

```text
streamlit_app.py
deployment_package.py
requirements.txt
requirements-person3-lock.txt
.streamlit/config.toml
deployment/package_manifest.json
deployment/coolcorridor-7e60744e872603ce7e33.zip
```

`deployment_check.py` is additionally required for smoke verification and the
Docker alternative. `deployment/results_summary.json` and the documentation are
review/demo artifacts, not app dependencies. Keep `.gitattributes` in the release
repository to protect ZIP bytes. Ordinary full-repository deployment is also
fine: the runtime still uses only this reviewed package.

Dependencies are fully pinned through `requirements.txt` →
`requirements-person3-lock.txt`. Do not substitute the unpinned Person 2 file.
Pyogrio wheels bundle GDAL, so no source GDAL build or `packages.txt` was added.
Wheel availability is not proof of Linux dynamic-library compatibility; verify
the deployed Linux process before sharing a URL.
[Pyogrio installation documentation](https://pyogrio.readthedocs.io/en/latest/install.html).

No API key, token or `secrets.toml` is required. Do not set
`COOLCORRIDOR_DATA_DIR` for this app: all tabs must read the same extracted
bundle. `.env` and `.streamlit/secrets.toml` are ignored, and the package allowlist
cannot include them. Local telemetry is disabled in the supplied config; host
policies may override configuration. CARTO tiles are external browser requests.

## Verify locally

From the repository root in PowerShell:

```powershell
# Inspect/verify the existing package; does not build or regenerate anything.
.venv\Scripts\python.exe -B deployment_package.py

# Read-only packaged-model checks and real four-tab rendering in AppTest.
.venv\Scripts\python.exe -B deployment_check.py --app-test

# Test the exact cloud entrypoint in a real browser.
.venv\Scripts\python.exe -B -m streamlit run streamlit_app.py --server.address=127.0.0.1 --server.port=8501
```

Stop an existing server using port 8501 first, or use another local port. Open
http://127.0.0.1:8501. AppTest checks application outputs; it does not render WebGL.
Use browser checks for basemap streets, paths, markers and charts.

Fresh environment, without changing `.venv`:

```powershell
python -m venv cache/deployment-clean-venv-new
cache\deployment-clean-venv-new\Scripts\python.exe -B -m pip install --only-binary=:all: -r requirements.txt
cache\deployment-clean-venv-new\Scripts\python.exe -B -m pip check
cache\deployment-clean-venv-new\Scripts\python.exe -B deployment_check.py --app-test
```

The new directory must be unused. Runtime does not require this test environment
or any other cache artifact. Required full source suite:

```powershell
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

For an explicitly reviewed new package, the build command is:

```powershell
.venv\Scripts\python.exe -B deployment_package.py --build --output deployment-new-review
```

It refuses to overwrite a manifest. Compare all new hashes and model results
before approving a release. Do not run `simulate_sensors.py`,
`heat_model/run_all.py`, model writers or canonical-output exports during
deployment.

## Publish only after approval

1. Review the complete uncommitted integration and deployment diff. Confirm
   the branch remains `integration-fixes-all-modules`, approve the chosen runtime
   ZIP and obtain explicit approval to commit/push. No merge is required just
   to deploy a reviewed branch.
2. The authorized repository owner commits/pushes the reviewed files to
   `HRChiam/coolcorridor`, ensuring the binary ZIP and package manifest are
   included. Preserve the reviewed integration source/tests and active raw
   correction artifacts for the development app, even though the production
   entrypoint can run from the minimal file set. Do not upload `cache/`, `.venv/`,
   personal browser profiles or secrets.
3. The owner signs in to Community Cloud, authorizes private repo/organization
   access and confirms admin permission and app-slot availability.
4. Create app: repository `HRChiam/coolcorridor`, approved branch
   `integration-fixes-all-modules`, entrypoint **`streamlit_app.py`**.
5. Advanced settings: choose **Python 3.13**. No app secrets are needed. Leave
   security/CORS/XSRF defaults intact. Approve the app visibility separately;
   never make the repository public merely to share the demo.
6. Only after explicit deployment approval, press Deploy. Review installation
   logs: all pinned versions must remain satisfied, with no unexpected source
   GDAL builds. Missing wheels/version conflicts are deployment blockers;
   do not silently downgrade libraries or regenerate heat.
7. On the actual cloud instance, run/read logs from `deployment_check.py` where
   terminal access is available, or verify its equivalent outputs through all
   four tabs. Confirm the active correction version and SIMULATED labels,
   no baseline fallback, 1,491 links, real routes, eight sensors and the 15-link
   RM99,920 plan. A health endpoint alone proves the server is up, not model readiness.
8. Verify CARTO tiles and WebGL in the judges' actual browser/network, desktop
   and a mobile viewport. Confirm `/_stcore/health` returns
   success. Repeat sensor faults and preview; verify no data was written.
9. Warm the app before the demonstration. Record the URL and target-cloud test
   evidence before distributing it to judges. Confirm private-app invitations
   or approved public visibility from a signed-out browser.

Community Cloud may throttle resources or restart processes; memory caches are
not durable. Keep the local packaged app as a demo fallback. Local timings are
not a cloud performance promise.
[Resource guidance](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).

## Container alternative

If owner/private-app constraints or measured cloud startup/resource limits make
Community Cloud unsuitable, use the supplied Dockerfile on an approved container
host with HTTPS and WebSocket support. It installs only pinned binary wheels,
verifies the same package, runs as a non-root user and honors `PORT`. Choose a
tested image digest and capacity after measuring the real Linux instance.
The Docker image was **not built or run here** because Docker/WSL are unavailable.

Commands for a later approved local/container test:

```bash
docker build -t coolcorridor:review .
docker run --rm -p 8501:8501 coolcorridor:review
docker run --rm coolcorridor:review python -B deployment_check.py --app-test
```

No container registry, paid service or deployment was created.
[Official Streamlit Docker guide](https://docs.streamlit.io/deploy/tutorials/docker).
