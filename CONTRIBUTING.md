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
