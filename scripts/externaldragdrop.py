"""
copyright Ahmed Hindy. Please mention the original author if you used any part of this code
This module handles drag and drops from outside of Houdini.
"""
import os
import logging
from pathlib import Path
import re

import hou

# --------------------------------------------------
# Configuration and Supported File Extensions
# --------------------------------------------------

# Supported image extensions for material networks
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".exr", ".hdr", ".tga", ".pic", ".tx", ".tex", ".rat")
# Supported USD extensions
USD_EXTS = (".usd", ".usda", ".usdc")

# Mapping for geometry-based networks (geo/sopnet)
GEO_HANDLERS = {
    ".abc": ("alembic", "fileName"),
    ".rs": ("redshift_packedProxySOP", "RS_proxy_file"),
    ".bgeo.sc": ("file", "file"),
    **{ext: ("usdimport", "filepath1") for ext in USD_EXTS},
}

# Mapping for material networks, keyed by subnet type (mtlx/principled)
MAT_HANDLERS = {
    "mtlx": {ext: ("mtlximage", "file") for ext in IMAGE_EXTS},
    "arnold": {ext: ("arnold::image", "filename") for ext in IMAGE_EXTS},
    "principled": {ext: ("texture::2.0", "map") for ext in IMAGE_EXTS},
}

# --------------------------------------------------
# Logger Setup
# --------------------------------------------------

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# --------------------------------------------------
# Utility Functions
# --------------------------------------------------

def get_full_extension(filename):
    """
    Get full extension (including multi-part) from filename.

    Args:
        filename: Name or path of the file.

    Returns:
        Combined suffixes as a single string (e.g., '.tar.gz').
    """
    path = Path(filename)
    return ''.join(path.suffixes)

def rel_path(fullpath):
    """
    Convert absolute path to relative $HIP path if applicable.

    Args:
        fullpath: Absolute filesystem path.

    Returns:
        A string with '$HIP/...' if under the HIP directory, else the original path.
    """
    hip = Path(hou.getenv("HIP", ""))
    path = Path(fullpath)
    try:
        rel = path.relative_to(hip)
        return f"$HIP/{rel.as_posix()}"
    except Exception:
        return fullpath

def detect_material_type(network_node):
    """
    Detect material subnet type based on existing children or prompt user.

    Args:
        network_node: Houdini network node whose children indicate subnet type.

    Returns:
        A string, either 'mtlx' or 'principled'.

    Raises:
        RuntimeError: If no render engine is selected by the user.
    """
    child_types = [child.type().name() for child in network_node.children()]
    if any("mtlx" in t for t in child_types):
        return "mtlx"
    if any("principled" in t or "texture::2.0" in t for t in child_types):
        return "principled"

    options_list = ["mtlx", "arnold", "principled"]
    choice = hou.ui.selectFromList(choices=options_list, exclusive=True,
                                   title="Choose Render Engine")
    print(f"DEBUG: {choice=}")
    if not choice:
        return None
    return options_list[choice[0]]

def create_new_node(network_node, file_path, node_type, parm_name, position, name=None):
    """
    Create a new Houdini node, set its file parameter, and position it.

    Args:
        network_node: The network in which to create the node.
        file_path: The file path to assign to the node parameter.
        node_type: The Houdini node type to create.
        parm_name: The parameter name to set the file path.
        position: Position vector for the new node.
        name: Optional name for the new node.

    Returns:
        The created Houdini node.
    """
    if name:
        node = network_node.createNode(node_type, name)
    else:
        node = network_node.createNode(node_type)
    node.setPosition(position)
    node.setParms({parm_name: file_path})
    return node

# --------------------------------------------------
# Main Import Logic
# --------------------------------------------------

def import_file(network_node, file_path, file_stem, file_ext, cursor_position):
    """
    Import a file into the given Houdini network based on file extension and network type.

    Args:
        network_node: The Houdini network node to import into.
        file_path: The file path to import.
        file_stem: The base filename without extension.
        file_ext: The file extension (including dot).
        cursor_position: Position vector for the new node.

    Returns:
        True if import succeeded, False otherwise.
    """
    safe_name = re.sub(r"\W+", "_", file_stem)

    net_type = network_node.type().name()
    while net_type == "subnet":
        network_node = network_node.parent()
        net_type = network_node.type().name()

    logger.info("Importing '%s' into network '%s'", file_path, net_type)

    if file_ext == ".hip":
        hou.hipFile.load(file_path)
        return True

    if net_type == "obj":
        network_node = network_node.createNode("geo", f"GEO_{safe_name}")
        network_node.setPosition(cursor_position)
        net_type = "geo"

    elif net_type in ("geo", "sopnet"):
        handler = GEO_HANDLERS.get(file_ext)
        if handler:
            node_type, parm = handler
            create_new_node(network_node, file_path, node_type, parm, cursor_position, name=safe_name)
            return True
        logger.warning("Unsupported geometry extension '%s'", file_ext)
        return False

    elif net_type in ("mat", "matnet", "materialbuilder", "materiallibrary", "assignmaterial"):
        material_type = detect_material_type(network_node)
        if not material_type:
            return True

        handlers = MAT_HANDLERS.get(material_type, {})
        node_info = handlers.get(file_ext)
        if node_info:
            node_type, parm = node_info
            create_new_node(network_node, file_path, node_type, parm, cursor_position, name=safe_name)
            return True
        logger.warning("Unsupported material extension '%s' for subnet '%s'", file_ext, material_type)
        return False

    elif net_type == "redshift_vopnet":
        create_new_node(network_node, file_path, "redshift::TextureSampler", "tex0", cursor_position, name=safe_name)
        return True

    elif net_type == "chopnet":
        create_new_node(network_node, file_path, "file", "file", cursor_position, name=safe_name)
        return True

    elif net_type in ("arnold_materialbuilder", "arnold_vopnet"):
        create_new_node(network_node, file_path, "arnold::image", "filename", cursor_position, name=safe_name)
        return True

    elif net_type in ("cop2net", "img"):
        create_new_node(network_node, file_path, "file", "filename1", cursor_position, name=safe_name)
        return True

    elif net_type in ("lopnet", "stage"):
        create_new_node(network_node, file_path, "assetreference", "filepath", cursor_position, name=safe_name)
        return True

    logger.error(f"No handler for network type '{net_type}' and extension '{file_ext}'")
    return False


def dropAccept(filepaths_list):
    """
    Main entrypoint for external drag-and-drop. Only accepts drops into NetworkEditor panes.

    Args:
        filepaths_list: List of file paths being dropped.

    Returns:
        True if all files imported successfully, False otherwise.
    """
    pane = hou.ui.paneTabUnderCursor()
    if pane.type().name() != "NetworkEditor":
        return False

    logger.info(f"Dropping filepaths_list {filepaths_list} into pane {pane.type().name()}")

    for idx, filepath in enumerate(filepaths_list):
        path = Path(filepath)
        stem = path.stem
        ext = get_full_extension(filepath)
        rel = rel_path(str(path))
        pos = pane.cursorPosition() + hou.Vector2(idx * 3, 0)

        try:
            success = import_file(pane.pwd(), rel, stem, ext, pos)
            if not success:
                logger.error(f"Couldn't import {rel}")
        except hou.Error as e:
            logger.exception(f"Houdini error importing {rel}: {e}", rel, e)
        except Exception as e:
            logger.exception(f"Unexpected error importing {rel}: {e}", rel, e)

    return True
