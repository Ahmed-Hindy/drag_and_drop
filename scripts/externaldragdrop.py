"""
copyright Ahmed Hindy. Please mention the original author if you used any part of this code
This module handles drag and drops from outside of Houdini.
"""
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
    ".vdb": ("file", "file"),
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
    Get the file extension, treating '.bgeo' specially by including the next suffix.

    Args:
        filename: Name or path of the file.

    Returns:
        - '.bgeo.sc' if the last suffix is '.bgeo' and another suffix exists.
        - Otherwise, just the last suffix (e.g., '.vdb', '.usd').
    """
    path = Path(filename)
    suffixes = path.suffixes  # List of all suffixes (e.g., ['.bgeo', '.sc'], ['.0001', '.vdb'])

    if not suffixes:
        return ""  # No extension

    # Special case: If last suffix is '.bgeo' and there's at least one more suffix
    if suffixes[-1].lower() == '.bgeo' and len(suffixes) > 1:
        return suffixes[-1] + suffixes[-2]  # '.bgeo' + '.sc' → '.bgeo.sc'

    # Default case: Return the last suffix
    return suffixes[-1]


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


def substitute_sequence_path(pathstr):
    """
    Detect file sequences and replace frame digits with $F<digits>.

    Args:
        pathstr: Original file path string.

    Returns:
        Path string with Houdini frame expression if sequence detected.
    """
    match = re.match(r"^(.*?)(\d+)(\.[^.]+)$", pathstr)
    if match:
        prefix, digits, ext = match.groups()
        width = len(digits)
        return f"{prefix}$F{width}{ext}"
    return pathstr


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
    logger.warning(f"Unsupported geometry extension '{file_ext}'")
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
    logger.warning(f"Unsupported material extension '{file_ext}' for '{material}'")
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


def _import_lop(network_node, file_path, safe_name, file_ext, position):
    """
    Handle LOP/STAGE network imports, including FBX, VDB, and default asset references.
    """
    # FBX: wrap in SOP Create with embedded File SOP
    if file_ext.lower() == ".fbx":
        sopcreate_node = network_node.createNode("sopcreate", node_name=f"SOP_{safe_name}")
        sopcreate_node.setPosition(position)
        file_sop = sopcreate_node.node("sopnet/create").createNode("file", node_name=safe_name)
        file_sop.setParms({"file": file_path})
        return True
    # VDBs: use Volume LOP
    if file_ext.lower().endswith(".vdb"):
        create_new_node(network_node, file_path, "volume", "filepath", position, name=safe_name)
        return True
    # Default: asset reference
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

    logger.info(f"Importing '{file_path}' into '{net_type}' network")

    # Scene load
    if file_ext.lower() == ".hip":
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
        return _import_lop(network_node, file_path, safe_name, file_ext, cursor_position)

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

    logger.info(f"Dropping {filepaths_list} into {pane.type().name()}")

    for idx, filepath in enumerate(filepaths_list):
        path = Path(filepath)
        stem = path.stem
        ext = get_full_extension(filepath)
        rel = rel_path(str(path))
        rel = substitute_sequence_path(rel)
        pos = pane.cursorPosition() + hou.Vector2(idx * 3, 0)

        try:
            if not import_file(pane.pwd(), rel, stem, ext, pos):
                return False
        except hou.Error as e:
            logger.exception(f"Houdini error importing {rel}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error importing {rel}: {e}")
            return False

    return True
