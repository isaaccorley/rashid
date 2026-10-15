# Development

Use this guide to set up rashid, run its checks, measure its performance, and inspect its logs. To propose a change, see the [Portolan contributing guide](https://github.com/portolan-sdi/portolan-ops/blob/main/policies/CONTRIBUTING.md).

## Setup

```bash
uv sync
uv run pre-commit install \
  --hook-type pre-commit \
  --hook-type commit-msg \
  --hook-type pre-push
```

The dev dependency group installs with the project. Commits follow
[Conventional Commits](https://www.conventionalcommits.org), enforced by
commitizen on the `commit-msg` hook.

## The two-stage gate

Hooks run in two stages, and CI reproduces both.

```bash
# fast gate, every commit: ruff, ruff-format, codespell,
# actionlint, zizmor, file hygiene
uv run pre-commit run --all-files

# full gate, every push: deptry, mypy (strict), vulture,
# xenon (complexity), import-linter
uv run pre-commit run --all-files --hook-stage pre-push
```

CI runs these with [prek](https://github.com/j178/prek) rather than
pre-commit. Both read the same `.pre-commit-config.yaml`. A clone without
hooks installed still faces the same checks.

## Tests

Tests carry a 90% coverage floor, and pull requests also need 90% on
changed lines.

```bash
uv run pytest                 # full suite
uv run pytest -n auto         # parallelised, as CI runs it
uv run pytest -m unit         # fast, isolated tests only
```

Markers are `unit`, `integration`, and `network`. The `network` tests
probe live servers (the live pass and remote data checks) and skip
themselves when offline; structural and schema validation run against
the closures vendored in `src/rashid/_schemas/`, no network involved. Setting `ENABLE_PRE_PUSH_TESTS=1` adds the fast
tests to the pre-push hook.

## Mutation testing

Coverage measures which lines run. Mutation testing measures whether the
tests notice when those lines change.

```bash
uv run mutmut run
```

CI runs this nightly against the floor in `.mutation-baseline`, currently
72%. Ratchet that number up as the suite improves. Lowering it needs a
justification in the pull request that does so.

## Measuring performance

Use `scripts/profile.py` to measure performance with repeatable inputs. The seeded scenarios in `tests/scenarios.py` generate the same catalogs on every run. Compare the small and large sizes to see how costs grow with catalog size.

```bash
uv run python scripts/profile.py metadata --mode counts
uv run python scripts/profile.py remote --size large --mode time
uv run python scripts/profile.py data --mode mem
uv run python scripts/profile.py metadata --mode import
uv run python scripts/profile.py metadata --size large --mode instr
```

Choose a scenario:

- `metadata` validates collections and items without reading asset bytes.
- `data` reads real GeoParquet and Cloud Optimized GeoTIFF files.
- `remote` serves the `metadata` catalog over local HTTPS and validates it by URL, with the live pass enabled.

Add `--warm` to run the scenario once before measuring, excluding the initial schema load.

Choose a measurement mode:

| Mode | Output | Requirements |
|---|---|---|
| `counts` | Operation counts and stage timings | No extra packages |
| `time` | pyinstrument profile | Loaded automatically with `uv run --with` |
| `mem` | memray profile | Loaded automatically with `uv run --with`; unavailable on Windows |
| `import` | Slowest imports from `python -X importtime` | No extra packages |
| `instr` | Instruction counts from cachegrind | Install `valgrind` first |

The script pins the pyinstrument and memray versions; neither is a rashid dependency. Instruction counts vary less between runs than wall time. Profiler output goes to `.cache/profiles`.

The `counts` output includes every operation counter and the time spent in each stage:

```text
# metadata/small seed=0
json.parses                           147
rules.checks                        1,821
schema.rust_compiles                    3
schema.rust_passes                    103

span              calls      wall ms       cpu ms  peak rss MB
load                  1         14.3         14.3         38.9
rules                 1         23.0         23.0         38.9
structural            1         51.1         51.0         48.8
extensions            1          2.3          2.3         49.1
```

Use this script for performance comparisons. Custom timing loops make results harder to compare.

## Operation counts

Counters are always enabled. `tests/integration/test_operation_counts.py` asserts exact counts for each small scenario and for the large `metadata` scenario, plus a memory ceiling for the large `metadata` scenario. If your change reduces the work performed, update the expected counts in the same pull request.

`tests/unit/test_import_budget.py` checks that `import rashid` and `rashid --help` do not load the geospatial stack, jsonschema, or a profiler. Keep heavy imports inside the functions that need them.

## Logs and timings on any catalog

Place logging and profiling flags before `check`:

```bash
uv run rashid --timings check --json path/to/catalog
uv run rashid -vv check path/to/catalog
uv run rashid --trace trace.json check path/to/catalog
```

- `--timings` adds a `meta` block to JSON reports. Without `--json`, it prints the stage table to stderr.
- `-v` enables `INFO` logs; `-vv` enables `DEBUG` logs. Logs go to stderr, leaving stdout for the report.
- `--trace` writes a Chrome trace that you can open in [Perfetto](https://ui.perfetto.dev).

When calling `validate()` from a library, use these environment variables:

| Variable | Effect |
|---|---|
| `RASHID_LOG` | Sets the stderr log level: `debug`, `info`, `warning`, or `error`. |
| `RASHID_LOG_FILE` | Writes every log record to a file as one JSON object per line. |
| `RASHID_TIMINGS` | Set to `1` to record stage timings, or `mem` to also record the tracemalloc peak. |
| `RASHID_TRACE` | Writes a Chrome trace to the specified path at exit. |

## Performance pull requests

For a `perf:` pull request, include before-and-after measurements under `## Verification`. State the scenario name and size, and include at least one of:

- Operation counts from `--mode counts`, with updated expectations in `tests/integration/test_operation_counts.py`.
- A timing block from `--mode counts` or `--mode time`.
- An instruction count from `--mode instr`.

## CI

CI logic is defined in
[portolan-ops](https://github.com/portolan-sdi/portolan-ops) as a
reusable workflow, and `.github/workflows/ci.yml` here is a thin caller.
Change the shared floor there, not here. `norms/ci.md` in that repo
covers how a change there is synced to this repo.

`security-audit.yml` stays local. It opens a tracking issue when
pip-audit finds a vulnerability and closes it when the audit goes clean.

## Releasing

Commitizen reads the commits since the last tag and picks the version.

```bash
git checkout main && git pull
git switch -c release/vX.Y.Z
uv run cz bump --changelog
git tag -d "vX.Y.Z"
git push -u origin release/vX.Y.Z
```

`cz bump` rewrites `pyproject.toml`, relocks `uv.lock` through a
pre-bump hook, writes `CHANGELOG.md`, commits as `bump:`, and tags.
Delete the local tag: `publish.yml` tags the merged commit itself, so a
tag on the branch commit points at the wrong one. Pass `--increment
PATCH` to override the computed version, which is what past releases
have done — `major_version_zero` keeps breaking changes off the major
but still bumps the minor for a `feat`.

**Squash-merge the release pull request.** `publish.yml` runs only when the
head commit message starts with `bump:`, and a merge commit reads
`Merge pull request #N from ...`, so the run skips with no error
anywhere and nothing reaches PyPI. Squashing puts the `bump:` title on
`main` and the workflow tags, builds, publishes, and creates the GitHub
release. If a release does merge the wrong way, recover with `gh
workflow run publish.yml --ref main`, which reads the version from
`pyproject.toml` rather than from the commit message.

Branch protection rejects a direct push to `main` without bypass rights,
so the pull request is the reliable route.

## Spec fixtures

`SPEC_REF` records the portolan-spec commit the vendored fixtures came
from. Re-vendor against a checkout of the spec:

```bash
uv run python scripts/vendor_spec_fixtures.py --spec ../portolan-spec
```

`spec-sync.yml` runs this nightly and opens a pull request when the spec
moves. Read that pull request's test run before merging it. A red
`test_schema_uri_invariant` means rashid needs a code change rather than a
fixture refresh.
