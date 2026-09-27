# LLM Red Team Workbench

LLM Red Team Workbench is a local tool for authorized internal LLM security
testing. Its current mutation workflow generates reproducible character,
segmentation, Unicode, and encoding variations without submitting them to an
LLM endpoint. The project is designed to grow into broader test campaigns,
evidence capture, scoring, and reporting.

The primary workflow is: “I have one prompt and want multiple variations to
try.” Run `llm-redteam` with no arguments to open the local web app, paste a
prompt, select a profile and intensity, and generate 25 balanced cases. The
sortable results table provides per-row raw and fully encoded copy actions.
Select a row to open its inspection modal with transformation metadata and
Unicode code-point details.

Intensity controls the share of eligible character positions transformed:
Low is approximately 15%, Medium 40%, High 75%, and Max 100%. Techniques that
operate on whole strings or specific character classes retain those semantics.

Choose `Custom Techniques` to select an exact set of technique families, or
`Custom Chain` to apply one ordered sequence of two or three transforms. Custom
selections are embedded in the run's audit metadata but are not saved as named
TOML profiles.

The web app loads no remote assets and defaults to `127.0.0.1`. It remembers
its light or dark theme in browser-local storage. The `?` menu documents every
profile, intensity, and technique. Use Focus or `Ctrl+M` to expand the results
workspace; `Esc` restores the normal layout.

> Prompt content and generated cases are retained in local audit bundles until
> explicitly deleted. Treat bundles and clipboard history as sensitive data.

## Install

LLM Red Team Workbench requires Python 3.11 or newer.

```shell
pipx install llm-redteam-workbench
llm-redteam
```

Use a different local port or avoid opening a browser automatically with:

```shell
llm-redteam web --port 9000
llm-redteam web --no-browser
```

For temporary review from another machine, bind an external interface and
explicitly allow the hostname or IP used in the browser:

```shell
llm-redteam web --host 0.0.0.0 --allowed-host 192.0.2.10 --no-browser
```

Remote mode does not add authentication. Keep it behind a firewall or VPN and
do not expose it directly to the public internet.

The terminal interface remains available through `llm-redteam tui`.

For development:

```shell
python -m pip install -e '.[dev]'
playwright install chromium
pytest
```

The Chromium installation is required for the browser interaction tests.

## CLI

Use stdin for sensitive prompts so they do not appear in shell history or
process listings:

```shell
printf '%s' 'Review this internal prompt' | llm-redteam generate - --count 25
```

Generate JSONL for another test harness:

```shell
llm-redteam generate 'Review this prompt' \
  --profile unicode --seed 42 --format jsonl --output ./runs
```

Other commands:

```shell
llm-redteam techniques
llm-redteam profiles
llm-redteam verify ./runs/RUN_ID
llm-redteam report ./runs/RUN_ID
llm-redteam runs list
llm-redteam runs show RUN_ID
llm-redteam runs delete RUN_ID
```

`generate` accepts repeated `--technique` options, `--profile`, `--profile-file`,
`--intensity`, `--count`, and `--all`. Normal runs are limited to a 100 KB input,
10,000 cases, 1 MB per case, and a projected 250 MB bundle. `--override-limits`
raises only the bundle soft limit; a 1 GB projected hard limit remains.

## Built-in profiles and techniques

Profiles are versioned TOML files. `baseline` balances all families,
`unicode` focuses on confusables and alternate character forms, `encoding`
focuses on mixed and partial encodings, and `comprehensive` adds compatible
two- and three-stage chains alongside single transforms. `chained` emits only
two- and three-technique pipelines, with no single-technique cases.

In both interactive interfaces, `Custom Techniques` generates single-transform
cases from a chosen set. `Custom Chain` provides three ordered selectors: steps
1 and 2 are required, while step 3 is optional. The generator applies that
exact two- or three-stage pipeline for every case; it does not permute the
selected steps. Both custom configuration sections can be collapsed.

The built-in catalog includes leetspeak, curated Greek/Cyrillic homoglyphs,
mathematical Unicode styles, full-width forms, zero-width insertion, whitespace
and punctuation fragmentation, random casing, separators, reversal, Base64,
mixed and selective hex, URL percent encoding, combining marks, normalization,
HTML numeric entities, and Unicode escape forms.

List effective profiles and their resolved settings with:

```shell
llm-redteam profiles
llm-redteam profiles --format json
```

Custom profiles are resolved in this order:

1. `--profile-file`
2. `.prompt-mutator/profiles/NAME.toml` in the current project
3. the platform user configuration directory
4. built-in profiles

The fully resolved profile is embedded in the audit bundle.

## Audit bundles

Every run writes:

- `run.json` with configuration, versions, seed, status, and counts
- `inputs.jsonl` with the original prompt once
- `cases.jsonl.gz` with generated cases and complete pipeline provenance
- `diagnostics.json` with skipped candidates and sanitized failures
- `events.log` without prompt content
- `report.html`, a self-contained searchable escaped report
- `manifest.json` with SHA-256 hashes for every bundle file

Use `llm-redteam verify` to detect missing, changed, or unexpected files.
Reports describe generation coverage only; they do not claim a prompt succeeded,
was blocked, or exposed a vulnerability.

## Extensions

Extensions are installed Python packages and are never loaded merely because
they are present. Register a callable under the `prompt_mutator.transforms`
entry-point group:

```toml
[project.entry-points."prompt_mutator.transforms"]
"acme:custom" = "acme_prompt_mutator:transform"
```

The callable receives `(prompt, random_generator, intensity)` and returns
`prompt_mutator.transforms.Mutation`. Enable it explicitly:

```shell
llm-redteam generate 'test prompt' --enable-extension 'acme:custom'
```

The package name and version are recorded in the resolved profile. Audit
bundles and arbitrary file paths are never treated as executable extensions.

## Security boundary

LLM Red Team Workbench is offline and performs no telemetry, endpoint submission,
semantic jailbreak generation, or content moderation. Inputs are treated as
opaque text. NUL, ANSI escape, bidi-control, unpaired-surrogate, and oversized
outputs are rejected or skipped. Use it only on systems you own or are
authorized to test.
