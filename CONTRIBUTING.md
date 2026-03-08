# Contributing to TrailVideoCut

Thanks for your interest in contributing!

## Development setup

```bash
git clone https://github.com/aegeavaz/trailvideocut.git
cd trailvideocut
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[ui,dev]"
```

## Running tests

```bash
pytest
```

## Code style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check .
ruff format .
```

Configuration is in `pyproject.toml` (target: Python 3.10, line length: 100).

## Pull request process

1. Fork the repository and create a feature branch from `main`
2. Make your changes and ensure tests pass
3. Run `ruff check .` and `ruff format .` before committing
4. Open a pull request against `main` with a clear description of the change

## Reporting issues

Use the [issue templates](https://github.com/aegeavaz/trailvideocut/issues/new/choose) for bug reports and feature requests.
