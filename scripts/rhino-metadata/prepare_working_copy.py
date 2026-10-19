# -*- coding: utf-8 -*-
"""Rhino 7 IronPython: flatten occurrences into a separate Rhino 5 File3dm."""
import imp
import io
import json
import os
import traceback

import Rhino
import System
import scriptcontext as sc

BRIDGE = os.path.join(os.environ['LOCALAPPDATA'], 'Codex', 'RhinoBlenderPipeline')


def publish(path, value):
    text = json.dumps(value, ensure_ascii=True, indent=2)
    temporary = path + '.tmp'
    with io.open(temporary, 'w', encoding='ascii') as stream:
        stream.write(unicode(text))
    if os.path.exists(path):
        raise RuntimeError('Refuse to replace existing output: ' + path)
    os.rename(temporary, path)


def main(request):
    helper = imp.load_source('rhino_blender_metadata', os.path.join(os.path.dirname(__file__), 'export_rhino_metadata.py'))
    doc = sc.doc
    with io.open(request['metadata_path'], 'r', encoding='utf-8') as stream:
        baseline = json.load(stream)
    assert baseline['automation']['request_id'] == request['metadata_request_id']
    current = helper.build_metadata(doc, request['metadata_request_id'])
    for field in ('document', 'objects', 'layers', 'instance_definitions'):
        assert current[field] == baseline[field], 'Source changed: ' + field
    identity = (int(doc.RuntimeSerialNumber), doc.Path, bool(doc.Modified))
    output = request['output_path']
    sidecar = request['occurrences_path']
    assert not os.path.exists(output) and not os.path.exists(sidecar), 'Outputs already exist; inspect before retry'
    model = Rhino.FileIO.File3dm()
    model.Settings.ModelUnitSystem = doc.ModelUnitSystem
    model.Settings.ModelAbsoluteTolerance = doc.ModelAbsoluteTolerance
    layer_map = {}
    for layer in doc.Layers:
        if layer is None or layer.IsDeleted:
            continue
        target = Rhino.DocObjects.Layer()
        target.Name = 'L{0:04d}'.format(int(layer.Index))
        target.Color = layer.Color
        model.Layers.Add(target)
        added = list(model.Layers)[-1]
        assert added.Name == target.Name
        layer_map[int(layer.Index)] = int(added.Index)
    material_map = {}
    for material in doc.Materials:
        if material is None or material.IsDeleted:
            continue
        copied = Rhino.DocObjects.Material(material)
        model.Materials.Add(copied)
        material_map[int(material.Index)] = int(list(model.Materials)[-1].Index)
    occurrences, blocks, omitted = [], [], []
    source_records = {item['id']: item for item in baseline['objects']}
    for definition in baseline['instance_definitions']:
        source_records.update({item['id']: item for item in definition['objects']})

    def visit(obj, transform, parent, chain, stack, parent_visible=True, parent_locked=False):
        source_id = str(obj.Id)
        key = '/'.join(chain + [source_id])
        record = source_records[source_id]
        metadata = dict(record['metadata'])
        path_parts = record['layer'].split('::')
        path_prefixes = ['::'.join(path_parts[:i+1]) for i in range(len(path_parts))]
        source_layers = {layer['full_path']: layer for layer in baseline['layers']}
        assert all(path in source_layers for path in path_prefixes), 'Missing source Layer ancestry'
        metadata['effective_visible'] = bool(parent_visible and metadata['visible'] and all(source_layers[path]['visible'] for path in path_prefixes))
        metadata['effective_locked'] = bool(parent_locked or metadata['locked'] or any(source_layers[path]['locked'] for path in path_prefixes))
        if isinstance(obj, Rhino.DocObjects.InstanceObject):
            definition = obj.InstanceDefinition
            assert definition is not None, 'Missing instance definition'
            definition_id = str(definition.Id)
            assert definition_id not in stack, 'Cyclic Block definitions'
            accumulated = transform * obj.InstanceXform
            blocks.append({'key': key, 'parent': parent, 'source_id': source_id,
                           'definition_id': definition_id, 'name': obj.Attributes.Name or definition.Name,
                           'definition_name': definition.Name, 'layer': record['layer'],
                           'source_metadata': metadata,
                           'world_matrix': helper.transform_data(accumulated)['matrix_row_major']})
            for member in definition.GetObjects():
                visit(member, accumulated, key, chain + [source_id], stack + [definition_id], metadata['effective_visible'], metadata['effective_locked'])
            return
        geometry = obj.Geometry.Duplicate()
        if isinstance(geometry, Rhino.Geometry.Extrusion):
            geometry = geometry.ToBrep()
        elif isinstance(geometry, Rhino.Geometry.Surface):
            geometry = geometry.ToBrep()
        if isinstance(geometry, (Rhino.Geometry.Curve, Rhino.Geometry.Point)):
            omitted.append({'key': key, 'source_id': source_id, 'type': record['type'], 'layer': record['layer']})
            return
        if not isinstance(geometry, Rhino.Geometry.Brep):
            raise RuntimeError('Unsupported geometry requires a dedicated adapter: ' + record['geometry_type'])
        assert geometry.Transform(transform), 'Geometry transform failed'
        assert geometry.IsValid, 'Invalid transformed Brep'
        attributes = obj.Attributes.Duplicate()
        attributes.ObjectId = System.Guid.NewGuid()
        attributes.Mode = Rhino.DocObjects.ObjectMode.Normal
        attributes.Visible = True
        attributes.LayerIndex = layer_map[int(obj.Attributes.LayerIndex)]
        if int(attributes.MaterialIndex) >= 0:
            assert int(attributes.MaterialIndex) in material_map, 'Missing material mapping'
            attributes.MaterialIndex = material_map[int(attributes.MaterialIndex)]
        token = 'RB_{0:05d}_{1}'.format(len(occurrences), source_id.replace('-', '')[:8])
        attributes.Name = token
        identifier = model.Objects.AddBrep(geometry, attributes)
        assert identifier != System.Guid.Empty, 'AddBrep failed'
        occurrences.append({'key': key, 'parent': parent, 'source_id': source_id,
                            'transport_name': token, 'name': record['name'], 'layer': record['layer'],
                            'type': record['type'], 'bbox': helper.bbox_data(geometry.GetBoundingBox(True)),
                            'display': record['display'], 'source_metadata': metadata})

    for item in baseline['objects']:
        obj = doc.Objects.FindId(System.Guid(item['id']))
        assert obj is not None
        visit(obj, Rhino.Geometry.Transform.Identity, None, [], [])
    assert occurrences, 'No supported Brep geometry to export'
    assert identity == (int(doc.RuntimeSerialNumber), doc.Path, bool(doc.Modified))
    assert model.Write(output, 5), 'Rhino 5 write failed'
    check = Rhino.FileIO.File3dm.Read(output)
    check_objects = list(check.Objects)
    assert len(check_objects) == len(occurrences)
    assert all(o.Geometry.IsValid and o.Attributes.Mode == Rhino.DocObjects.ObjectMode.Normal for o in check_objects)
    assert set(o.Attributes.Name for o in check_objects) == set(o['transport_name'] for o in occurrences)
    assert identity == (int(doc.RuntimeSerialNumber), doc.Path, bool(doc.Modified))
    data = {'schema_version': 2, 'metadata_request_id': request['metadata_request_id'],
            'document': baseline['document'], 'layers': baseline['layers'],
            'mode': 'blocks' if blocks else 'layers', 'blocks': blocks,
            'occurrences': occurrences, 'omitted': omitted,
            'transport_path': output, 'geometry_count': len(occurrences)}
    publish(sidecar, data)
    return {'ok': True, 'request_id': request['request_id'], 'output_path': output,
            'occurrences_path': sidecar, 'geometry_count': len(occurrences),
            'block_occurrences': len(blocks), 'omitted_count': len(omitted), 'source_unchanged': True}


if __name__ == '__main__':
    request = None
    try:
        with io.open(os.path.join(BRIDGE, 'copy_request.json'), 'r', encoding='utf-8-sig') as stream:
            request = json.load(stream)
        response = main(request)
    except Exception as error:
        response = {'ok': False, 'request_id': request.get('request_id') if request else None,
                    'message': str(error), 'traceback': traceback.format_exc()}
    if request:
        publish(request['response_path'], response)
    print(json.dumps(response, ensure_ascii=True))
