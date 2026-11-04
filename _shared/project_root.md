# `<PROJECT_ROOT>` Resolution Rule (shared — read, do not paste)

1. The plugin/installer directory (any folder named `agentic-dlc*`) is **never** `<PROJECT_ROOT>`.
   Never create `resources/`, `specs/`, `backlog/`, `design/`, `test/`, `src/` or `deploy/` inside it.
2. Resolve `<PROJECT_ROOT>` in this order:
   1. `~/.gemini/config/project_root.txt` if it exists and points to an existing directory;
   2. the current working directory, if its name is not `agentic-dlc*`;
   3. the parent of the current working directory if cwd is a `agentic-dlc*` folder nested inside a project;
   4. otherwise **ask the user** before writing any file.
3. Pass `--project-root "<PROJECT_ROOT>"` to every helper script. Scripts call
   `dlc_common.resolve_project_root()` which implements the same order and refuses installer directories.
4. Write only inside `<PROJECT_ROOT>/{resources,specs,backlog,design,test,src,deploy}/`. Never write scratch files
   there; never use artifact-directory metadata for project files.
