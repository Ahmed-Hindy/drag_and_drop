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

# Mapping for material networks, keyed by material type
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
    except ValueError:
        return fullpath


def detect_material_type(network_node):
    """
    Detect material type based on existing children or prompt user.

    Args:
        network_node: Houdini network node whose children indicate material type.

    Returns:
        A string: 'mtlx', 'arnold', or 'principled', or None if cancelled.
    """
    child_types = [child.type().name() for child in network_node.children()]
    if any("mtlx" in t for t in child_types):
        return "mtlx"
    if any("principled" in t or "texture::2.0" in t for t in child_types):
        return "principled"
    if any("arnold::" in t for t in child_types):
        return "arnold"

    options = ["mtlx", "arnold", "principled"]
    choice = hou.ui.selectFromList(choices=options, exclusive=True,
                                   title="Choose Render Engine")
    if not choice:
        return None
    return options[choice[0]]


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
    node = network_node.createNode(node_type, name) if name else network_node.createNode(node_type)
    node.setPosition(position)
    node.setParms({parm_name: file_path})
    return node

# --------------------------------------------------
# Helper Import Functions
# --------------------------------------------------

def _import_geo(network_node, file_path, safe_name, file_ext, position):
    """
    Handle geometry/SOP imports.
    """
    handler = GEO_HANDLERS.get(file_ext)
    if handler:
        node_type, parm = handler
        create_new_node(network_node, file_path, node_type, parm, position, name=safe_name)
        return True
    logger.warning("Unsupported geometry extension '%s'", file_ext)
    return False


def _import_material(network_node, file_path, safe_name, file_ext, position):
    """
    Handle material network imports.
    """
    material = detect_material_type(network_node)
    if material is None:
        return True  # canceled by user
    handlers = MAT_HANDLERS.get(material, {})
    node_info = handlers.get(file_ext)
    if node_info:
        node_type, parm = node_info
        create_new_node(network_node, file_path, node_type, parm, position, name=safe_name)
        return True
    logger.warning("Unsupported material extension '%s' for '%s'", file_ext, material)
    return False


def _import_redshift(network_node, file_path, safe_name, position):
    """
    Handle Redshift VOPNET imports.
    """
    create_new_node(network_node, file_path, "redshift::TextureSampler", "tex0", position, name=safe_name)
    return True


def _import_chop(network_node, file_path, safe_name, position):
    """
    Handle CHOP network imports.
    """
    create_new_node(network_node, file_path, "file", "file", position, name=safe_name)
    return True


def _import_arnold(network_node, file_path, safe_name, position):
    """
    Handle Arnold material/vopnet imports.
    """
    create_new_node(network_node, file_path, "arnold::image", "filename", position, name=safe_name)
    return True


def _import_cop2(network_node, file_path, safe_name, position):
    """
    Handle COP2/img network imports.
    """
    create_new_node(network_node, file_path, "file", "filename1", position, name=safe_name)
    return True


def _import_lop(network_node, file_path, safe_name, position):
    """
    Handle LOP/STAGE network imports.
    """
    create_new_node(network_node, file_path, "assetreference", "filepath", position, name=safe_name)
    return True

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

    # Unwrap nested subnets
    while net_type == "subnet":
        network_node = network_node.parent()
        net_type = network_node.type().name()

    logger.info("Importing '%s' into '%s' network", file_path, net_type)

    # Handle scene loads
    if file_ext == ".hip":
        hou.hipFile.load(file_path)
        return True

    # Auto-create geo container in OBJ context
    if net_type == "obj":
        network_node = network_node.createNode("geo", f"GEO_{safe_name}")
        network_node.setPosition(cursor_position)
        net_type = "geo"

    # Dispatch by network type
    if net_type in ("geo", "sopnet"):
        return _import_geo(network_node, file_path, safe_name, file_ext, cursor_position)

    if net_type in ("mat", "matnet", "materialbuilder", "materiallibrary", "assignmaterial"):
        return _import_material(network_node, file_path, safe_name, file_ext, cursor_position)

    if net_type == "redshift_vopnet":
        return _import_redshift(network_node, file_path, safe_name, cursor_position)

    if net_type == "chopnet":
        return _import_chop(network_node, file_path, safe_name, cursor_position)

    if net_type in ("arnold_materialbuilder", "arnold_vopnet"):
        return _import_arnold(network_node, file_path, safe_name, cursor_position)

    if net_type in ("cop2net", "img"):
        return _import_cop2(network_node, file_path, safe_name, cursor_position)

    if net_type in ("lopnet", "stage"):
        return _import_lop(network_node, file_path, safe_name, cursor_position)

    logger.error("No handler for network type '%s' and extension '%s'", net_type, file_ext)
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

    logger.info("Dropping %s into %s", filepaths_list, pane.type().name())

    for idx, filepath in enumerate(filepaths_list):
        path = Path(filepath)
        stem = path.stem
        ext = get_full_extension(filepath)
        rel = rel_path(str(path))
        pos = pane.cursorPosition() + hou.Vector2(idx * 3, 0)

        try:
            if not import_file(pane.pwd(), rel, stem, ext, pos):
                return False
        except hou.Error as e:
            logger.exception("Houdini error importing %s: %s", rel, e)
            return False
        except Exception as e:
            logger.exception("Unexpected error importing %s: %s", rel, e)
            return False

    return True
