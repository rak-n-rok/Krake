# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import codecs
import os.path


def read(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, rel_path), 'r') as fp:
        return fp.read()


def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith('__version__'):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    else:
        raise RuntimeError("Unable to find version string.")


# -- Project information -----------------------------------------------------

project = "Krake"
copyright = "2019, Cloud&Heat Technologies GmbH"
author = """
Boris Pilka <boris.pilka@x-works.io>
Chan Yi Lin <chanyi.lin@cloudandheat.com>
Juraj Sloboda <juraj.sloboda@x-works.io>
Kamil <kamil.szabo@x-works.io>
Kamil Szabo <kamil.szabo@ifne.eu>
Lucas Kahlert <lucas.kahlert@cloudandheat.com>
Martin Pilka <martin.pilka@ifne.eu>
Martin Pilka <martin.pilka@x-works.io>
Matej Feder <feder.mato@gmail.com>
Matej Feder <matej.feder@x-works.io>
Matthias Goerens <matthias.goerens@cloudandheat.com>
Orianne Bargain <orianne.bargain@cloudandheat.com>
Paul Seidler <paul.seidler@cloudandheat.com>
Yannic Ahrens <yannic.ahrens@cloudandheat.com>
"""

# The full version, including alpha/beta/rc tags
release = get_version("krake/__about__.py")


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.autosectionlabel",
    "sphinx_rtd_theme",
    "sphinx-prompt",
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# The document name of the "master" document, that is, the document that
# contains the root toctree directive.
master_doc = "index"

# -- ToDo settings --------------------------------------------------------

# If this is True, todo and todolist produce output, else they produce
# nothing. The default is False.
todo_include_todos = True

# If this is True, todo emits a warning for each TODO entries. The default is
# False.
todo_emit_warnings = False


# If this is True, todolist produce output without file path and line, The
# default is False.
todo_link_only = False


# -- Napoleon settings --------------------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True


# -- InterSphinx settings -----------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "aiohttp": ("https://aiohttp.readthedocs.io/en/stable/", None),
    "marshmallow": ("https://marshmallow.readthedocs.io/en/stable/", None),
    "webargs": ("https://webargs.readthedocs.io/en/stable/", None),
    "requests": ("https://requests.readthedocs.io/en/stable/", None),
}


# -- autosectionlabel settings ------------------------------------------------

# True to prefix each section label with the name of the document it is in,
# followed by a colon. For example, index:Introduction for a section called
# Introduction that appears in document index.rst. Useful for avoiding
# ambiguity when the same section heading appears in different documents.
autosectionlabel_prefix_document = True

# If set, autosectionlabel chooses the sections for labeling by its depth. For
# example, when set 1 to autosectionlabel_maxdepth, labels are generated only
# for top level sections, and deeper sections are not labeled. It defaults to
# None (disabled).
autosectionlabel_maxdepth = None

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "sphinx_rtd_theme"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
# html_static_path = ["_static"]
