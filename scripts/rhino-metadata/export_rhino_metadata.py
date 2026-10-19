# -*- coding: utf-8 -*-
"""Export the active Rhino 7 document's metadata for a Codex request.

Run through Rhino.Interface.7 and RunPythonScript. The script reads a request
from the local Codex RhinoBlenderPipeline directory and never modifies the document.
"""

import datetime
import io
import json
import os
import traceback

import Rhino
import scriptcontext as sc


BRIDGE_DIRECTORY = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Codex",
    "RhinoBlenderPipeline",
)
REQUEST_PATH = os.path.join(BRIDGE_DIRECTORY, "request.json")


def utc_text():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def guid_text(value):
    return str(value) if value is not None else None


def point_data(point):
    return {"x": float(point.X), "y": float(point.Y), "z": float(point.Z)}


def vector_data(vector):
    return {"x": float(vector.X), "y": float(vector.Y), "z": float(vector.Z)}


def transform_data(xform):
    return {
        "matrix_row_major": [
            [float(xform.M00), float(xform.M01), float(xform.M02), float(xform.M03)],
            [float(xform.M10), float(xform.M11), float(xform.M12), float(xform.M13)],
            [float(xform.M20), float(xform.M21), float(xform.M22), float(xform.M23)],
            [float(xform.M30), float(xform.M31), float(xform.M32), float(xform.M33)],
        ]
    }


def bbox_data(bbox):
    if not bbox.IsValid:
        return None
    return {
        "min": point_data(bbox.Min),
        "max": point_data(bbox.Max),
        "center": point_data(bbox.Center),
        "size": vector_data(bbox.Diagonal),
    }


def color_data(color):
    if color is None:
        return None
    return {
        "r": int(color.R),
        "g": int(color.G),
        "b": int(color.B),
        "a": int(color.A),
    }


def safe_enum_name(value):
    try:
        return value.ToString()
    except Exception:
        return str(value)


def layer_path(doc, layer_index):
    try:
        layer = doc.Layers[layer_index]
        if layer is None:
            return None
        return layer.FullPath
    except Exception:
        return None


def user_strings(attributes):
    result = {}
    try:
        keys = attributes.GetUserStrings().AllKeys
        for key in keys:
            result[key] = attributes.GetUserString(key)
    except Exception:
        pass
    return result


def material_data(doc, obj):
    attributes = obj.Attributes
    result = {
        "source": safe_enum_name(attributes.MaterialSource),
        "index": int(attributes.MaterialIndex),
        "id": None,
        "name": None,
    }
    try:
        material = obj.GetRenderMaterial(True)
        if material is not None:
            result["id"] = guid_text(material.Id)
            result["name"] = material.Name
    except Exception:
        try:
            if attributes.MaterialIndex >= 0:
                material = doc.Materials[attributes.MaterialIndex]
                result["id"] = guid_text(material.Id)
                result["name"] = material.Name
        except Exception:
            pass
    return result


def display_color_data(doc, obj):
    attributes = obj.Attributes
    resolved = None
    try:
        resolved = attributes.DrawColor(doc)
    except Exception:
        pass
    return {
        "source": safe_enum_name(attributes.ColorSource),
        "object_color": color_data(attributes.ObjectColor),
        "resolved_color": color_data(resolved),
    }


def instance_definition_records(doc):
    definitions = []
    object_to_definition = {}
    for definition in doc.InstanceDefinitions:
        if definition is None or definition.IsDeleted:
            continue
        try:
            definition_objects = list(definition.GetObjects() or [])
        except Exception:
            definition_objects = []
        object_ids = []
        for definition_object in definition_objects:
            object_id = guid_text(definition_object.Id)
            object_ids.append(object_id)
            object_to_definition[object_id] = {
                "id": guid_text(definition.Id),
                "name": definition.Name,
            }
        definitions.append({
            "id": guid_text(definition.Id),
            "index": int(definition.Index),
            "name": definition.Name,
            "description": definition.Description,
            "object_ids": object_ids,
            "_rhino_objects": definition_objects,
        })
    return definitions, object_to_definition


def object_data(doc, obj, definition_lookup):
    attributes = obj.Attributes
    object_id = guid_text(obj.Id)
    parent_definition = definition_lookup.get(object_id)
    instance = None
    xform = Rhino.Geometry.Transform.Identity

    if isinstance(obj, Rhino.DocObjects.InstanceObject):
        xform = obj.InstanceXform
        definition = obj.InstanceDefinition
        instance = {
            "definition_id": guid_text(definition.Id) if definition else None,
            "definition_name": definition.Name if definition else None,
            "transform": transform_data(xform),
        }

    groups = []
    try:
        groups = [int(index) for index in (attributes.GetGroupList() or [])]
    except Exception:
        pass

    return {
        "id": object_id,
        "name": attributes.Name or "",
        "layer": layer_path(doc, attributes.LayerIndex),
        "layer_index": int(attributes.LayerIndex),
        "type": safe_enum_name(obj.ObjectType),
        "geometry_type": obj.Geometry.GetType().Name if obj.Geometry is not None else None,
        "bbox": bbox_data(obj.Geometry.GetBoundingBox(True)),
        "bbox_space": "parent_definition" if parent_definition is not None else "document_world",
        "transform": transform_data(xform),
        "block": {
            "is_instance_reference": bool(instance is not None),
            "instance": instance,
            "is_definition_object": bool(parent_definition is not None),
            "parent_definition": parent_definition,
        },
        "display": {
            "color": display_color_data(doc, obj),
            "material": material_data(doc, obj),
        },
        "metadata": {
            "user_strings": user_strings(attributes),
            "groups": groups,
            "visible": bool(attributes.Visible),
            "locked": bool(safe_enum_name(attributes.Mode) == "Locked"),
        },
    }


def layer_records(doc):
    layers = []
    for layer in doc.Layers:
        if layer is None or layer.IsDeleted:
            continue
        layers.append({
            "id": guid_text(layer.Id),
            "index": int(layer.Index),
            "name": layer.Name,
            "full_path": layer.FullPath,
            "parent_layer_id": guid_text(layer.ParentLayerId),
            "color": color_data(layer.Color),
            "visible": bool(layer.IsVisible),
            "locked": bool(layer.IsLocked),
        })
    return layers


def read_request():
    with io.open(REQUEST_PATH, "r", encoding="utf-8-sig") as stream:
        request = json.load(stream)
    required = ("request_id", "output_path", "response_path")
    for key in required:
        if not request.get(key):
            raise ValueError("Request is missing required field: {0}".format(key))
    return request


def atomic_write_json(path, value, request_id):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    temporary_path = "{0}.{1}.tmp".format(path, request_id)
    with io.open(temporary_path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    if os.path.exists(path):
        os.remove(path)
    os.rename(temporary_path, path)


def build_metadata(doc, request_id):
    definitions, definition_lookup = instance_definition_records(doc)
    objects = []
    for obj in doc.Objects:
        if obj is None or obj.IsDeleted:
            continue
        objects.append(object_data(doc, obj, definition_lookup))

    definition_object_count = 0
    definition_instance_count = 0
    for definition in definitions:
        rhino_objects = definition.pop("_rhino_objects")
        serialized_objects = []
        for obj in rhino_objects:
            if obj is None or obj.IsDeleted:
                continue
            item = object_data(doc, obj, definition_lookup)
            serialized_objects.append(item)
            definition_object_count += 1
            if item["block"]["is_instance_reference"]:
                definition_instance_count += 1
        definition["objects"] = serialized_objects

    return {
        "schema_version": 2,
        "automation": {
            "request_id": request_id,
            "exported_utc": utc_text(),
            "transport": "Rhino.Interface.7 COM plus request-response files",
        },
        "document": {
            "name": doc.Name,
            "path": doc.Path,
            "runtime_serial_number": int(doc.RuntimeSerialNumber),
            "modified": bool(doc.Modified),
            "model_units": safe_enum_name(doc.ModelUnitSystem),
            "absolute_tolerance": float(doc.ModelAbsoluteTolerance),
        },
        "coordinate_system": {
            "handedness": "right-handed",
            "up_axis": "+Z",
            "top_level_object_space": "Rhino document/world coordinates",
            "definition_object_space": "parent block-definition coordinates",
            "matrix_convention": "4x4 row-major values; point transform follows RhinoCommon",
            "instance_rule": "Multiply transforms from the outer instance toward the nested instance to place nested content in world space.",
            "notes": "Non-instance objects have identity transform. Instance references carry InstanceXform relative to their containing document or definition.",
        },
        "counts": {
            "top_level_objects": len(objects),
            "instance_definitions": len(definitions),
            "top_level_instance_references": sum(
                1 for item in objects if item["block"]["is_instance_reference"]
            ),
            "definition_objects": definition_object_count,
            "definition_instance_references": definition_instance_count,
        },
        "layers": layer_records(doc),
        "instance_definitions": definitions,
        "objects": objects,
    }


def main():
    request = None
    try:
        request = read_request()
        metadata = build_metadata(sc.doc, request["request_id"])
        atomic_write_json(request["output_path"], metadata, request["request_id"])
        response = {
            "schema_version": 1,
            "request_id": request["request_id"],
            "ok": True,
            "output_path": request["output_path"],
            "output_bytes": int(os.path.getsize(request["output_path"])),
            "document": metadata["document"],
            "counts": metadata["counts"],
            "exported_utc": metadata["automation"]["exported_utc"],
        }
        atomic_write_json(request["response_path"], response, request["request_id"])
        print("Rhino metadata exported: {0}".format(request["output_path"]))
        print("Request: {0}; top-level objects: {1}; block definitions: {2}".format(
            request["request_id"],
            metadata["counts"]["top_level_objects"],
            metadata["counts"]["instance_definitions"],
        ))
    except Exception as error:
        details = traceback.format_exc()
        if request is not None and request.get("response_path"):
            response = {
                "schema_version": 1,
                "request_id": request.get("request_id"),
                "ok": False,
                "message": str(error),
                "traceback": details,
                "exported_utc": utc_text(),
            }
            try:
                atomic_write_json(
                    request["response_path"], response, request.get("request_id", "unknown")
                )
            except Exception:
                pass
        print("Rhino metadata export failed: {0}".format(error))
        print(details)


if __name__ == "__main__":
    main()
