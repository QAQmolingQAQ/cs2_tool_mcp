"""Source graph/schema checks must expose unsupported and runtime-only cases."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp.fgd import FgdCatalog
from hammer_mcp.source_parsing import map_entities
from hammer_mcp.map_io_check import check_entities, parameter_error


HEADER = '<!-- dmx encoding keyvalues2 4 format vmap 40 -->\n'


def entity(identifier, classname, name='', **properties):
    return {'id': identifier, 'properties': {'classname': classname, 'targetname': name, **properties}, 'connections': []}


class MapIoTests(unittest.TestCase):
    def catalog(self):
        catalog = FgdCatalog(Path('/unused'))
        for name, inputs, outputs, properties in (
            ('logic_relay', {'trigger': 'void'}, {'ontrigger': 'void'}, {}),
            ('func_door', {'setspeed': 'float'}, {}, {'filtername': 'filterclass'}),
            ('filter_activator_name', {}, {}, {}), ('info_target', {}, {}, {}),
            ('env_entity_maker', {'forcespawnatentityorigin': 'target_destination'}, {}, {'entitytemplate': 'target_destination'}),
            ('point_template', {}, {}, {'template01': 'target_destination'}),
        ):
            catalog.classes[name] = {'name': name, 'bases': [], 'inputs': inputs, 'outputs': outputs, 'properties': properties}
        return catalog

    def test_nested_and_flat_dmx_references_and_connections(self):
        text = HEADER + '''"CMapEntity" {
          "id" "elementid" "entity"
          "entity_properties" "element" "props"
          "connectionsData" "element_array" [ "element" "connection" ]
        }
        "EditGameClassProps" { "id" "elementid" "props" "classname" "string" "logic_relay" "targetname" "string" "relay" }
        "DmeConnectionData" { "id" "elementid" "connection" "targetName" "string" "!self" "inputName" "string" "Trigger" "outputName" "string" "OnTrigger" }
        '''
        entities = map_entities(text)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]['connections'][0]['targetName'], '!self')
        self.assertTrue(check_entities(entities, self.catalog())['passed'])
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            map_entities(text.replace('"element" "props"', '"element" "missing"'))
        with self.assertRaises(ValueError):
            map_entities(text[:text.rfind('}')])
        nested = HEADER + '''"CMapEntity" { "id" "elementid" "nested"
          "entity_properties" "EditGameClassProps" { "classname" "string" "logic_relay" }
          "connectionsData" "element_array" [] }'''
        self.assertEqual(map_entities(nested)[0]['properties']['classname'], 'logic_relay')

    def test_fgd_includes_inheritance_resource_types_and_cycles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = root / 'game/core'; core.mkdir(parents=True)
            game = root / 'game/csgo'; game.mkdir()
            (core / 'base.fgd').write_text('@BaseClass = Base [ input Kill(void) : "desc" output OnReady(void) : "desc" ]')
            entry = game / 'csgo.fgd'
            entry.write_text('@include "base.fgd"\n@PointClass base(Base) = test [ cs_script(resource:vjs) : "script" input SetValue(integer) : "x" ]')
            catalog = FgdCatalog(root); catalog.load(entry)
            schema = catalog.resolve('test')
            self.assertEqual(schema['inputs']['kill'], 'void')
            self.assertEqual(schema['properties']['cs_script'], 'resource:vjs')
            self.assertNotIn('kill', schema['properties'])
            self.assertEqual(len(catalog.files), 2)
            entry.write_text('@include "csgo.fgd"')
            with self.assertRaisesRegex(ValueError, 'cycle'):
                FgdCatalog(root).load(entry)

    def test_missing_filter_io_target_and_parameter_types(self):
        relay = entity('relay', 'logic_relay', 'relay')
        door = entity('door', 'func_door', 'door', filtername='missing_filter')
        relay['connections'] = [dict(outputName='OnTrigger', inputName='SetSpeed', targetName='door', overrideParam='NaN'),
                                dict(outputName='OnTrigger', inputName='Trigger', targetName='missing', overrideParam='')]
        result = check_entities([relay, door], self.catalog())
        self.assertFalse(result['passed'])
        codes = {issue['code'] for issue in result['issues']}
        self.assertTrue({'missing_filter', 'invalid_numeric_shape_or_value', 'missing_io_target'} <= codes)
        self.assertIsNone(parameter_error('integer', '08'))
        self.assertIsNone(parameter_error('vector', '1 2 3'))
        self.assertEqual(parameter_error('api', 'value'), 'unsupported_fgd_parameter_type')

    def test_missing_base_and_inheritance_cycle_are_not_silently_ignored(self):
        catalog = self.catalog()
        catalog.classes['logic_relay']['bases'] = ['missing']
        with self.assertRaisesRegex(ValueError, 'missing FGD base'):
            catalog.resolve('logic_relay')
        catalog.classes['logic_relay']['bases'] = ['logic_relay']
        with self.assertRaisesRegex(ValueError, 'inheritance cycle'):
            catalog.resolve('logic_relay')

    def test_runtime_targets_are_deferred_and_issue_limit_does_not_hide_failure(self):
        relay = entity('relay', 'logic_relay', 'relay')
        relay['connections'] = [dict(outputName='OnTrigger', inputName='Trigger', targetName='!activator', overrideParam=''),
                                dict(outputName='OnTrigger', inputName='Trigger', targetName='missing', overrideParam='')]
        result = check_entities([relay], self.catalog(), 1)
        self.assertFalse(result['passed'])
        self.assertTrue(result['issues_truncated'])
        self.assertEqual(result['severity_counts']['error'], 1)
        self.assertEqual(result['issues'][0]['code'], 'runtime_target_deferred')

    def test_requested_maker_spawn_info_target_template_policy(self):
        relay = entity('relay', 'logic_relay', 'relay')
        maker = entity('maker', 'env_entity_maker', 'maker', entitytemplate='template')
        template = entity('template', 'point_template', 'template', template01='door')
        spawn = entity('spawn', 'info_target', 'spawn')
        door = entity('door', 'func_door', 'door')
        relay['connections'] = [dict(outputName='OnTrigger', inputName='ForceSpawnAtEntityOrigin', targetName='maker', overrideParam='spawn')]
        result = check_entities([relay, maker, template, spawn, door], self.catalog())
        self.assertIn('maker_spawn_target_outside_template', [issue['code'] for issue in result['issues']])
        template['properties']['template02'] = 'spawn'
        result = check_entities([relay, maker, template, spawn, door], self.catalog())
        self.assertNotIn('maker_spawn_target_outside_template', [issue['code'] for issue in result['issues']])
        self.assertFalse(result['coverage_complete'])


if __name__ == '__main__':
    unittest.main()
