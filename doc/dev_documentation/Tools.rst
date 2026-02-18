Tools & IDE's
===================================================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:


There are numerous IDE's for developing python applications,  but we
will focus on two: Visual Studio Code and PyCharm

General
-------
Python code can be writtin using any text editor. However, we've chosen the following tools to support us:

- **Black** for code formatting
- **Flake8** for code linting
- **MyPy** for typehints/typeChecking
- **pytest** for unit testing
-

PyCharm
-------





VS Code
-------

The following extensions should be installed:

* https://marketplace.visualstudio.com/items?itemName=ms-python.python
* https://marketplace.visualstudio.com/items?itemName=ms-python.flake8
* https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter
* https://marketplace.visualstudio.com/items?itemName=matangover.mypy

settings.json for vscode:

.. code-block:: JSON

   {
   "python.analysis.typeCheckingMode": "basic",
   "[python]": {
      "editor.defaultFormatter": "ms-python.black-formatter"
   },
   "python.formatting.provider": "black",
   "mypy.runUsingActiveInterpreter": true,
   }




Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
