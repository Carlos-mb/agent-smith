# Model comparison — backing data

Backing data for [`BENCHMARK_REPORT.md`](../../../BENCHMARK_REPORT.md). Each
directory is one model id (with `/` and `:` replaced by `_`), and under it one
directory per task holding that run's `solution.json` and moulinette output.

All runs here are from 15 September 2026, one per model × task. The eighth
model, `gemini-3.5-flash-lite`, has its runs in the parent directory
(14 September). The ninth, `codestral-2508`, has its report runs in
`../ablation/observation_stop/`, because they belong to section 5.4 as well.
The ablations are in `../ablation/`.

The runs recorded here the previous afternoon, while Google's endpoint was
returning HTTP 503 almost continuously, were replaced by these reruns.
