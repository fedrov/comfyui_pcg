# Contributing

Thanks for taking the time to contribute. Bug reports with a minimal workflow are the most useful thing you can send.

## Reporting a bug

Open an issue with:

- what you did, what you expected and what happened (a screenshot of the graph helps);
- the smallest workflow `.json` that reproduces it;
- ComfyUI version, OS, and how you installed this pack;
- for behaviour that differs from Houdini: the Houdini node and parameters you compared against.

## Development setup

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/fedrov/comfyui_pcg.git
cd comfyui_pcg
python -m pip install -r requirements.txt scipy manifold3d fonttools
npm install                      # only for the frontend test suites
python tests/run_tests.py --js   # all suites except the ones that need a running ComfyUI
```

The tests do not need ComfyUI: `tests/fakecomfy.py` stubs the few ComfyUI modules the nodes import.

## Conventions

- **Never break saved workflows.** ComfyUI stores widget values by position, so new widgets go at the *end* of
  `INPUT_TYPES`, and their default must reproduce the old behaviour.
- **Tests come with the change.** Prefer analytic checks (a value you can derive by hand) over snapshots, and add a
  negative control that proves the check can fail.
- **Docs stay in sync.** Node prose lives in `docs/_data/nodes/*.json`; after changing a node run
  `python docs/build_docs.py`. `tests/test_docs.py` fails if a node or parameter is undocumented or the generated pages
  are stale.
- Code, comments and UI text are in English.
- The heavy production-workflow suite (`tests/test_prod_workflows.py`) needs several GB of RAM; run it on its own.

## Pull requests

Keep a PR to one topic, describe the behaviour change, and mention which suites you ran. By submitting a pull request
you agree that your contribution is licensed under the Apache License 2.0.
