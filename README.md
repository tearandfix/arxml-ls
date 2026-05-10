# arxml-ls

A Language Server Protocol (LSP) server for AUTOSAR ARXML files, providing editor intelligence for `.arxml` workspaces.

## Features

- **Diagnostics** — three-pass validation: XML syntax → XSD schema → cross-file reference integrity
- **Hover** — shows the AUTOSAR element tag name under the cursor
- **Document symbols** — lists all XML elements in the file
- **Go to definition** — cursor on any segment of a `/Path/To/Element` reference jumps to that segment's element, not just the leaf
- **Find references** — cursor on a `<SHORT-NAME>` finds every `-REF`/`-TREF` pointing to that element or any of its children
- **Rename** — renames a `<SHORT-NAME>` and updates all references across the workspace

## Requirements

- Python 3.12+
- [`pygls`](https://github.com/openlawlibrary/pygls)
- [`lxml`](https://lxml.de/)
- [`lsprotocol`](https://github.com/microsoft/lsprotocol)

```bash
pip install pygls lxml lsprotocol
```

## Usage

The server communicates over stdio, which is the standard mode for LSP clients.

```bash
python arxml_ls.py
```

### Neovim (via `nvim-lspconfig`)

```lua
vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile" }, {
  pattern = "*.arxml",
  callback = function()
    vim.lsp.start({
      name = "arxml-ls",
      cmd = { "python", "/path/to/arxml_ls.py" },
      root_dir = vim.fs.dirname(vim.fs.find(".git", { upward = true })[1]),
    })
  end,
})
```

### VS Code

Add a custom LSP entry via the [custom LSP extension](https://marketplace.visualstudio.com/items?itemName=llllvvuu.llllvvuu-lsp) or any extension that lets you configure arbitrary LSP servers.

### Schema validation

XSD schema validation uses the AUTOSAR schema file. Set the path via environment variable:

```bash
export ARXML_SCHEMA_PATH=/path/to/AUTOSAR_00049_COMPACT.xsd
python arxml_ls.py
```

If the file is absent, schema validation is silently skipped and only XML syntax and cross-reference checks run.

## Project layout

```
arxml_ls/
├── models.py      # ArxmlNode, ProjectDocument, ProjectIndex data classes
├── analysis.py    # Cursor/position and reference analysis utilities
├── indexing.py    # Tree building, workspace discovery, project index caching
├── validation.py  # XML syntax and XSD schema validation
└── handlers.py    # LSP server instance and all feature handlers
arxml_ls.py        # Entry point
```

## Development

```bash
# Lint
ruff check arxml_ls/ arxml_ls.py

# Format
ruff format arxml_ls/ arxml_ls.py
```

There are no automated tests. Manual testing is done by opening `.arxml` files in an editor with the server configured as an LSP provider.
