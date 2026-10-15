# Development

This guide covers how to measure rashid and how to read what it logs. See
the [contributing guide](contributing.md) for setup, tests, and CI.

## Measuring performance

A performance claim needs a number from a fixed input. The seeded
scenarios in `tests/scenarios.py` build the same catalog every time, at a
small and a large size. Comparing the two runs shows whether a cost grows
with the catalog. `scripts/profile.py` runs one scenario and measures it:

```bash
uv run python scripts/profile.py metadata --mode counts
uv run python scripts/profile.py remote --size large \
  --mode time
uv run python scripts/profile.py data --mode mem
uv run python scripts/profile.py metadata --mode import
uv run python scripts/profile.py metadata --size large \
  --mode instr
```

The `metadata` scenario validates collections and items without reading
asset bytes. `data` reads real GeoParquet and Cloud Optimized GeoTIFF
files. `remote` serves the `metadata` tree over a local HTTPS server and
validates it by URL, with the live pass on. `--warm` runs once before the
measured run, which leaves out the one-time schema load.

The `counts` mode needs no extra package. It prints every operation
counter and the time spent in each stage:

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

The `time` mode runs pyinstrument and `mem` runs memray. Both load through
`uv run --with` at the pinned version in the script, so neither is a
dependency of rashid. memray does not run on Windows. `import` lists the
slowest imports from `python -X importtime`. The `instr` mode counts
instructions with cachegrind. Install `valgrind` before you use it. An
instruction count changes much less between runs than wall time.
Profiler output goes to `.cache/profiles`.

Do not write your own timing loop. A reviewer cannot compare numbers from
two different loops.

## Operation counts

Counters are always on, and tests assert their exact values. The tests in
`tests/integration/test_operation_counts.py` fix the counts for each small
scenario and a memory ceiling for the large one. A change that does less
work updates those numbers in the same pull request.

`tests/unit/test_import_budget.py` fails when `import rashid` or
`rashid --help` loads the geospatial stack, jsonschema, or a profiler.
Keep heavy imports inside the function that needs them.

## Logs and timings on any catalog

Put these flags before `check`. They write to stderr, and stdout keeps the
report alone.

```bash
uv run rashid --timings check --json path/to/catalog
uv run rashid -vv check path/to/catalog
uv run rashid --trace trace.json check path/to/catalog
```

`--timings` adds a `meta` block to `--json` output, or prints the stage
table to stderr. `-v` and `-vv` write `INFO` and `DEBUG` log records.
`--trace` writes a Chrome trace, which <https://ui.perfetto.dev> opens.

The environment variables do the same for a library caller of
`validate()`:

| Variable | Effect |
|---|---|
| `RASHID_LOG` | `debug`, `info`, `warning`, or `error`. Records at that level go to stderr. |
| `RASHID_LOG_FILE` | Writes every record as one JSON object per line. |
| `RASHID_TIMINGS` | `1` records stage timings. `mem` also records the tracemalloc peak. |
| `RASHID_TRACE` | Writes a Chrome trace to the path at exit. |

## Performance pull requests

A `perf:` pull request pastes one of these in `## Verification`, before
and after, with the scenario name and size:

- A counter change from `--mode counts`, with the updated exact count in
  `tests/integration/test_operation_counts.py`.
- A timing block from `--mode counts` or `--mode time`.
- An instruction count from `--mode instr`.
