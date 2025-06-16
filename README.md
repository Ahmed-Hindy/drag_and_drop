# Houdini External Drag & Drop Plugin

A small Houdini Python module that lets you drag and drop files from your operating system directly into Houdini’s Network Editor. It automatically creates the appropriate SOP, OBJ, LOP or MAT nodes based on the file type and current network context.

## Features
- Supports common formats:  
  • Alembic (`.abc`)  
  • USD (`.usd`, `.usda`, `.usdc`)  
  • Redshift proxies (`.rs`)  
  • Image textures and generic files  
- Auto–detects network type (OBJ, SOP, COP, MAT, LOP, etc.)  
- Creates the correct node and sets its file parameter  
- Converts absolute paths under `$HIP` to use the HIP variable  
- Renderer choice dialog for material networks (MaterialX or Principled)

## Installation
1. Copy `scripts` folder to "C:/Users/`<USERNAME>`/Documents/houdini20.5/" or whatever Houdini version you are using.
2. Restart Houdini.

## Usage
1. Open any Network Editor pane in Houdini.  
2. Drag files from the file browser onto any Network Editor.
3. Depending on the file extension and the current network context, a new node is created at the drop position and its file parameter is set.
