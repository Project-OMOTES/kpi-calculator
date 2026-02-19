# Configuration file for the Sphinx documentation builder.

import warnings

# sphinx_autodoc_typehints uses a deprecated Sphinx internal API (set_application).
# The warning is harmless and will be fixed upstream; suppress it until then.
warnings.filterwarnings(
    "ignore",
    message=".*set_application.*is deprecated",
    category=DeprecationWarning,
)

project = "KPI Calculator"
copyright = "2023-2026, Nieuwe Warmte Nu Design Toolkit"
author = "Jesus Andres Rodriguez Sarasty"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",   # source links + populates py-modindex
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinx_autodoc_typehints",
]

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/pandas-docs/stable", None),
    "numpy": ("https://numpy.org/doc/stable", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "project_efvc_"]

html_theme = "furo"
html_static_path = ["_static"]
html_logo = "_static/NWN_logo_color_RGB.png"
