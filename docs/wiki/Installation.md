# Installation

## Requirements

| | |
|---|---|
| Python | 3.11 or newer |
| Chromium | installed by Playwright, not your desktop browser |
| Disk | a few hundred MB for Chromium, plus your screenshots |
| Network | only to your own product, and to a model if you enable the writer |

Verba runs entirely on your machine. No project content is uploaded anywhere
unless you configure a model, and then only the text and images that model is
asked about.

## Install

```bash
pip install "git+https://github.com/GiladBronshtein/verba.git#egg=verba-docs[assist]"
playwright install chromium
```

The `[assist]` extra pulls in the model client. Leave it off and everything
still works except the writing, the picture checks and selector healing:

```bash
pip install "git+https://github.com/GiladBronshtein/verba.git#egg=verba-docs"
```

## From a clone

For development, or if you want the demo product and the example document:

```bash
git clone https://github.com/GiladBronshtein/verba.git
cd verba
pip install -e ".[assist]"
playwright install chromium
python tools/selftest.py
```

## In a virtual environment

Recommended, and required on distributions that mark the system Python as
externally managed:

```bash
python3 -m venv ~/.venvs/verba
source ~/.venvs/verba/bin/activate
pip install "git+https://github.com/GiladBronshtein/verba.git#egg=verba-docs[assist]"
playwright install chromium
```

## Checking the install

```bash
verba --help          # or: python3 -m verba --help
```

Both forms work. `python3 -m verba` is the safe one when several Pythons are on
the machine, because it uses the interpreter you name.

## PDF output

PDF is rendered through the same Chromium that does the crawling, so there is
no LaTeX, no wkhtmltopdf and no separate install. If `playwright install
chromium` succeeded, `verba build --pdf` works.

## Fonts

The document is set in whatever your theme names, and falls back when a face is
missing. `verba fonts` reports what the outputs will actually be set in on this
machine, which is worth running once before you argue with a colleague about
kerning.

## Upgrading

```bash
pip install --upgrade "git+https://github.com/GiladBronshtein/verba.git#egg=verba-docs[assist]"
```

Your project under `content/` is data, not code. Upgrading the engine does not
touch it. New rules may report findings your document did not have before,
which is the point of them.
