# Contributing

## Development Workflow

1. Create a branch on your local working copy
2. Make code modifications, including tests and documentation
3. Commit and push changes to remote/origin
4. Submit a pull request for merging into main
5. Discuss with the code reviewer if/what changes are needed
6. When all discussions are resolved, the PR will be merged by the reviewer

For setup instructions, tooling commands, and the full validation pipeline, see the
[Developer Documentation](https://kpi-calculator.readthedocs.io/en/latest/dev_documentation/development.html)
(or locally in `doc/dev_documentation/development.rst`).

## Code Quality Guidelines

Quality guidelines serve to improve quality. They should not be busy work nor work against developers.

### Code Review

- Every commit should be created on its own branch and submitted per pull request to be merged with main.
- Every pull request must be reviewed by at least one other developer and all comments must be resolved.
- No linting issues may remain before merging.
- No type checking issues may remain before merging.
- Code reviews are not about distrust. They are about sharing knowledge about the codebase and increasing quality by collaboration.

### Documentation

- Every function must have a docstring explaining what the function does and describing each argument and return type.

### Linting

- Linting maintains a shared quality standard across the codebase.
- Linter rules may only be ignored when approved by the software leads. Silence individual lines with `# noqa: <code>` rather than disabling rules project-wide.

### Type Checking

- Every function must have a return type annotation and fully annotated argument list.
- Type checker rules may only be ignored when approved by the software leads.

### Testing

- Every function should be covered by a unit test where it adds value.
- A unit test should test a meaningful unit of behaviour — not a single line, not an entire module.
- Use mocks to isolate the unit under test where applicable.
- Coverage must remain above 80%. Breaking this threshold requires agreement from the team, not just the author and reviewer.
- Structure every test using the **AAA (Arrange-Act-Assert)** pattern, with each section separated by a blank line and labeled with a `# Arrange`, `# Act`, `# Assert` comment. For tests where act and assert cannot be separated (e.g. `assertRaises`), use `# Act & Assert`.
- Use the **most specific assertion** available for the situation — prefer `assertEqual`, `assertIsInstance`, `assertIsNotNone`, `assertIn` etc. over `assertTrue`/`assertFalse`. Never use bare `assert` statements in test methods; they bypass unittest's error reporting.
- **Extract magic strings** that appear in assertions to module-level constants (e.g. expected KPI names, error messages). This makes refactoring cheaper and assertion intent clearer.
- **Extract shared test fixtures** (e.g. factory functions for domain objects) to module-level helper functions when used across multiple test classes. Avoid duplicating fixture logic between test classes.
- **Extract repeated assertion patterns** to helper methods on the test class (e.g. `_find_distribution_item`, `_get_kpi_count`) to avoid copy-paste in the Assert section.
- Use `tempfile.TemporaryDirectory` as a **context manager** for temporary file tests. Avoid `setUp`/`tearDown` for resources only needed by a single test — allocate them in the test itself instead.
- Avoid the **TOCTOU anti-pattern** in cleanup code: do not check for existence before deleting (e.g. `if path.exists(): rmtree(path)`); operate directly and let errors surface if something is wrong.
- Place imports that are only needed inside a single test method at the top of that method, not at module level, to keep the module's import footprint minimal.

Applying these guidelines to all existing test files is a tracked task — see "Harden Test Suite" item 1 in [`ROADMAP.md`](doc/project_efvc_/kpi_development_documentation/ROADMAP.md).
