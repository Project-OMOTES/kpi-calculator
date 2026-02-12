# Configuration file for the Sphinx documentation builder.

project = "KPI Calculator"
copyright = "2023-2026, Nieuwe Warmte Nu Design Toolkit"
author = "Jesus Andres Rodriguez Sarasty"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinx_autodoc_typehints",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/pandas-docs/stable", None),
    "numpy": ("https://numpy.org/doc/stable", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "project_efvc_"]

html_theme = "furo"
html_static_path = []
