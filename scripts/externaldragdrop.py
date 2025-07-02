"""
copyright Ahmed Hindy. Please mention the original author if you used any part of this code
This module handles drag and drops from outside of Houdini.
"""
import os
import logging
from pathlib import Path
import re
from typing import Optional

import hou



# --------------------------------------------------
# Configuration and Supported File Extensions
# --------------------------------------------------

# Supported image extensions for material networks
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".exr", ".hdr", ".tga", ".pic", ".tx", ".tex", ".rat"}
# Supported USD extensions
USD_EXTS = {".usd", ".usda", ".usdc"}

# Mapping for geometry-based networks (geo/sopnet)
GEO_HANDLERS: dict[str, tuple[str, str]] = {
    ".abc": ("alembic", "fileName"),
    ".rs": ("redshift_packedProxySOP", "RS_proxy_file"),
    ".bgeo.sc": ("file", "file"),
    **{ext: ("usdimport", "filepath1") for ext in USD_EXTS},
}

# Mapping for material networks, keyed by subnet type (mtlx/principled)
MAT_HANDLERS: dict[str, dict[str, tuple[str, str]]] = {
    "mtlx": {ext: ("mtlximage", "file") for ext in IMAGE_EXTS},
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
    path = Path(filename)
    # This handles multiple dots correctly
    return ''.join(path.suffixes)


def rel_path(fullpath: str) -> str:
    """
    Convert absolute path to relative $HIP path if applicable.
    """
    hip = Path(hou.getenv("HIP", ""))
    path = Path(fullpath)
    try:
        rel = path.relative_to(hip)
        return f"$HIP/{rel.as_posix()}"
    except Exception:
        return fullpath


def detect_subnet_type(network_node: hou.Node) -> str:
    """
    Detect material subnet type based on existing children or prompt user.

    Returns:
        'mtlx' or 'principled'
    """
    child_types = [child.type().name() for child in network_node.children()]
    if any("mtlx" in t for t in child_types):
        return "mtlx"
    if any("principled" in t or "texture::2.0" in t for t in child_types):
        return "principled"

    choice = hou.ui.selectFromList(["mtlx", "principled"], exclusive=True,
                                    title="Choose Render Engine", default_choices=[0])
    if not choice:
        raise RuntimeError("No render engine selected.")
    return ["mtlx", "principled"][choice[0]]


def create_new_node( network_node: hou.Node, file_path: str, node_type: str, parm_name: str, position: hou.Vector2,
                     name: Optional[str] = None) -> hou.Node:
    """
    Create a new Houdini node, set its file parameter, and position it.
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

def import_file(network_node: hou.Node, file_path: str, file_stem: str, file_ext: str, cursor_position: hou.Vector2) -> bool:
    """
    Import a file into the given Houdini network based on file extension and network type.
    """
    # Clean up name for new nodes
    safe_name = re.sub(r"\W+", "_", file_stem)

    net_type = network_node.type().name()
    # Unwrap nested subnets
    while net_type == "subnet":
        network_node = network_node.parent()
        net_type = network_node.type().name()

    logger.info("Importing '%s' into network '%s'", file_path, net_type)

    # Handle dropping a .hip file to load a scene
    if file_ext == ".hip":
        hou.hipFile.load(file_path)
        return True

    # OBJ context: auto-create geo container
    if net_type == "obj":
        network_node = network_node.createNode("geo", f"GEO_{safe_name}")
        network_node.setPosition(cursor_position)
        net_type = "geo"

    # Geometry-based networks
    if net_type in ("geo", "sopnet"):
        handler = GEO_HANDLERS.get(file_ext)
        if handler:
            node_type, parm = handler
            create_new_node(network_node, file_path, node_type, parm, cursor_position, name=safe_name)
            return True
        logger.warning("Unsupported geometry extension '%s'", file_ext)
        return False

    # Material networks
    if net_type in ("mat", "matnet", "materialbuilder", "materiallibrary", "assignmaterial"):
        subnet = detect_subnet_type(network_node)
        handlers = MAT_HANDLERS.get(subnet, {})
        node_info = handlers.get(file_ext)
        if node_info:
            node_type, parm = node_info
            create_new_node(network_node, file_path, node_type, parm, cursor_position, name=safe_name)
            return True
        logger.warning("Unsupported material extension '%s' for subnet '%s'", file_ext, subnet)
        return False

    # Other specialized networks
    if net_type == "redshift_vopnet":
        create_new_node(network_node, file_path, "redshift::TextureSampler", "tex0", cursor_position, name=safe_name)
        return True

    if net_type == "chopnet":
        create_new_node(network_node, file_path, "file", "file", cursor_position, name=safe_name)
        return True

    if net_type in ("arnold_materialbuilder", "arnold_vopnet"):
        create_new_node(network_node, file_path, "arnold::image", "filename", cursor_position, name=safe_name)
        return True

    if net_type in ("cop2net", "img"):
        create_new_node(network_node, file_path, "file", "filename1", cursor_position, name=safe_name)
        return True

    if net_type in ("lopnet", "stage"):
        create_new_node(network_node, file_path, "reference", "filepath1", cursor_position, name=safe_name)
        return True

    logger.error("No handler for network type '%s' and extension '%s'", net_type, file_ext)
    return False


def dropAccept(filepaths_list):
    """
    Main entrypoint for external drag-and-drop. Only accepts drops into NetworkEditor panes.
    """
    pane = hou.ui.paneTabUnderCursor()
    if pane.type().name() != "NetworkEditor":
        return False

    logger.info("Dropping filepaths_list %s into pane %s", filepaths_list, pane.type().name())

    for idx, filepath in enumerate(filepaths_list):
        path = Path(filepath)
        stem = path.stem
        ext = get_full_extension(filepath)
        rel = rel_path(str(path))
        pos = pane.cursorPosition() + hou.Vector2(idx * 3, 0)

        try:
            success = import_file(pane.pwd(), rel, stem, ext, pos)
            if not success:
                return False
        except hou.Error as e:
            logger.exception("Houdini error importing %s: %s", rel, e)
            return False
        except Exception as e:
            logger.exception("Unexpected error importing %s: %s", rel, e)
            return False

    return True
