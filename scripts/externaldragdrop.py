"""
copyright Ahmed Hindy. Please mention the original author if you used any part of this code
This module handles drag and drops from outside of Houdini.
"""
import re
import os
import sys
import traceback
import platform
# from urllib.parse import unquote

import hou




def dropAccept(files):
    pane = hou.ui.paneTabUnderCursor()
    if pane.type().name() != "NetworkEditor":
        return False

    print(f'externaldragdrop.py ---dropping new file: {files} into {pane.type().name()}')

    for i, file in enumerate(files):
        file_path = file
        file_basename = os.path.splitext(os.path.basename(file_path))
        file_ext = file_basename[1].lower()
        
        #convert to relative path
        file_path = rel_path(file_path)
        # print(f'{file_basename=}\n{file_path=}')
        
        cursor_position = pane.cursorPosition() + hou.Vector2(i *3, 0)

        network_node = pane.pwd()

        #opening hip
        if re.match(".hip", file_ext) != None:
            hou.hipFile.load(file_path)
            return True

        #adding nodes
        try:
            import_file(network_node, file_path, file_basename, file_ext, cursor_position)
        except:
            print(sys.exc_info()[1])
            traceback.print_exc()
            return False

    return True


def rel_path(fullpath):
    """
    Generates a relative file path based on the full path provided. The function checks
    if the full path starts with the value of the 'HIP' environment variable and,
    if so, replaces the matching part with the variable placeholder "$HIP".

    :param fullpath: The absolute path to be converted into a relative path.
    :type fullpath: str
    :return: The relative path with "$HIP" prefix if applicable; otherwise,
             the original full path.
    :rtype: str
    """
    hippath = hou.getenv("HIP")
    if re.match(hippath, fullpath):
        fullpath = "$HIP" +  re.sub(hippath, "", fullpath)
    return fullpath


def get_subnet_type(network_node):
    """
    Determine the subnet type for a given network node based on its child nodes' types or user selection.

    Examines the types of child nodes under the provided network node. If the type matches specific
    criteria, such as containing 'mtlx' or certain 'principled' identifiers, the subnet type is
    determined automatically. If no match is found, prompts the user to select a render engine
    from a displayed list.

    :param network_node: Houdini network node whose subnet type is being determined.
    :type network_node: object
    :return: The determined subnet type, either 'mtlx' or 'principled'.
    :rtype: str
    """
    network_node_children_types = [child.type().name() for child in network_node.children()]
    if any('mtlx' in s for s in network_node_children_types):
        return 'mtlx'
    elif any('principled' in s or 'texture::2.0' in s for s in network_node_children_types):
        return 'principled'
    else:
        renderer_choice = hou.ui.selectFromList(['mtlx', 'principled'], default_choices=[0], exclusive=True,
                                                title='Choose Render Engine', height=3)
        if renderer_choice[0] == 0:
            return 'mtlx'
        elif renderer_choice[0] == 1:
            return 'principled'
        else:
            raise ValueError(f"Wrong choice from popup! '{renderer_choice}'")



def create_new_node(network_node, file_path, node_name, parm_path_name, cursor_position, **kwargs):
    """
    Creates a new node within a specified network, sets its parameters, and positions it according
    to the provided coordinates. If a name for the node is not supplied via the 'kwargs' parameter,
    a default name will be assigned. The function also sets a given parameter path to a specific
    file path.

    :param network_node: Represents the network in which the new node will be created.
    :type network_node: any
    :param file_path: The file path to be assigned to the parameter specified by `parm_path_name`.
    :type file_path: str
    :param node_name: The type of node to create.
    :type node_name: str
    :param parm_path_name: The parameter path that will receive the `file_path` value.
    :type parm_path_name: str
    :param cursor_position: A tuple specifying the (x, y) coordinates for the position of
                             the new node in the network editor.
    :type cursor_position: tuple
    :param kwargs: Additional keyword arguments. Includes the optional 'name' parameter
                   which represents the name to explicitly assign to the created node.
    :type kwargs: dict, optional
    :return: The newly created node.
    :rtype: object
    """
    name = kwargs.get('name', None)

    print(f"DEBUG: {name=}")
    print(f"DEBUG: {node_name=}")
    print(f"DEBUG: {network_node=}")
    if name:
        new_node = network_node.createNode(node_name, name)
    else:
        new_node = network_node.createNode(node_name)

    new_node.setPosition(cursor_position)
    new_node.setParms({parm_path_name:file_path})
    return new_node



def import_file(network_node, file_path, file_basename, file_ext, cursor_position):
    """
    Imports a file into the specified Houdini network node based on the file type and network type. The function adjusts
    its behavior and creates the appropriate nodes to ensure compatibility with the given Houdini network context. The function
    handles multiple file types (e.g., .abc, .rs, .usd) and various network contexts (e.g., obj, geo, mat).

    :param network_node: Houdini network node in which the file will be imported.
    :param file_path: Full path to the file to be imported.
    :param file_basename: Base name of the file to be imported.
    :param file_ext: Extension of the file to be imported.
    :param cursor_position: Desired cursor position in the Houdini network editor for the created node.
    :return: Whether the file was successfully imported into the desired Houdini network node.
    :rtype: bool
    """
    # validate node name
    file_name = re.sub(r"[^0-9a-zA-Z\.]+", "_", file_basename[0])
    # create new geo node in obj network if none exists

    net_type_name = network_node.type().name()
    print(f"Network: '{net_type_name}'")


    # if target network is a subnet, get the real network type by looking up to parents
    if net_type_name == "subnet":
        parent = network_node.parent()
        while parent.type().name() == "subnet":
            parent = parent.parent()
        net_type_name = parent.type().name()

    # now we have the real network type (if it was a subnetwork) now we can create the correct node in the correct place:
    if net_type_name in ("obj",):
        network_node = network_node.createNode("geo", f"GEO_{file_name}")
        net_type_name = network_node.type().name()
        network_node.setPosition(cursor_position)

    if net_type_name in ("geo", "sopnet"):
        if file_ext == ".abc":
            create_new_node(network_node, file_path, "alembic", "fileName", cursor_position,
                            name=file_name)
            return True
        elif file_ext == ".rs":
            create_new_node(network_node, file_path, "redshift_packedProxySOP", "RS_proxy_file",
                            cursor_position, name=file_name)
            return True
        elif file_ext in (".usd", ".usda", ".usdc"):
            create_new_node(network_node, file_path, "usdimport", "filepath1", cursor_position,
                            name=file_name)
        else:
            print(f"File Extension not supported: '{file_ext}'")
            return False

    elif net_type_name in ("mat", "matnet", "materialbuilder", "materiallibrary", "assignmaterial"):
        # get if it's a 'mtlx' subnet or 'principled'
        subnet_type = get_subnet_type(network_node)

        if file_ext not in ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.exr', '.hdr', '.tga', '.pic', '.tx',
                            '.tex', '.rat'):
            print(f"File Extension not supported: '{file_ext}'")
            return False

        if subnet_type == 'mtlx':
            create_new_node(network_node, file_path, "mtlximage", "file", cursor_position, name = file_name)
            return True
        elif subnet_type == 'principled':
            create_new_node(network_node, file_path, "texture::2.0", "map", cursor_position, name = file_name)
            return True
        else:
            print(f"Subnet type not supported: '{subnet_type}'")

    elif net_type_name == "redshift_vopnet":
        create_new_node(network_node, file_path, "redshift::TextureSampler", "tex0",
                        cursor_position, name=file_name)
        return True

    elif net_type_name == "chopnet":
        create_new_node(network_node, file_path, "file", "file", cursor_position,
                        name=file_name)
        return True

    elif net_type_name in ("arnold_materialbuilder", "arnold_vopnet"):
        create_new_node(network_node, file_path, "arnold::image", "filename", cursor_position,
                        name=file_name)
        return True

    elif net_type_name in ("cop2net", "img"):
        create_new_node(network_node, file_path, "file", "filename1", cursor_position,
                        name=file_name)
        return True

    elif net_type_name in ("lopnet", "stage"):
        create_new_node(network_node, file_path, "reference", "filepath1", cursor_position,
                        name=file_name)
        return True

    return False
