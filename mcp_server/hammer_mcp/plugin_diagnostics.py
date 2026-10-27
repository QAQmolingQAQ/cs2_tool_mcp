"""Bounded parsing of fixed, independently marked plugin/cvar query responses."""
import math,re

CVAR_TYPES={'cs2f_commands_enable':bool,'cs2f_admin_commands_enable':bool,
            'cs2f_weapons_enable':bool,'snd_musicvolume':float}
QUERIES=('meta version','meta list','css_plugins list',*CVAR_TYPES)


def summarize_queries(responses):
    queries={};versions={};cvars={};version_evidence={}
    for command in QUERIES:
        lines=responses.get(command,[])
        base=command.split()[0]
        unavailable=any(re.fullmatch(r'\s*Unknown command:\s*'+re.escape(base)+r'\s*',line) for line in lines)
        queries[command]={'status':'command_unavailable' if unavailable else 'response_unparsed' if lines else 'no_response_observed',
                          'response_lines':len(lines)}
    for command,plugin,pattern in (
        ('meta version','metamod',r'\s*Metamod:Source version ([0-9][A-Za-z0-9.+_-]{0,95})\s*'),
        ('meta list','cs2fixes',r'\s*\[\s*\d+\]\s+"?CS2Fixes"?\s+\(([0-9][A-Za-z0-9.+_-]{0,95})\)\s+by [^\r\n]*\s*')):
        values=set()
        for line in responses.get(command,[]):
            match=re.fullmatch(pattern,line)
            if match:values.add(match[1])
        if len(values)==1 and queries[command]['status']!='command_unavailable':
            versions[plugin]=values.pop();queries[command]['status']='version_observed'
            version_evidence[plugin]={'query':command,'scope':'console_response_not_module_binary_identity'}
        elif len(values)>1:queries[command]['status']='conflicting_versions'
    for name,kind in CVAR_TYPES.items():
        values=set()
        for line in responses.get(name,[]):
            match=re.fullmatch(r'\s*'+re.escape(name)+r'\s*=\s*([^\s]+)\s*',line)
            if not match:continue
            token=match[1]
            if len(token)>96:continue
            if kind is bool:
                if token not in ('true','false','0','1'):continue
                value=token in ('true','1')
            else:
                try:value=float(token)
                except ValueError:continue
                if not math.isfinite(value):continue
            values.add(value)
        unavailable=queries[name]['status']=='command_unavailable'
        cvars[name]=next(iter(values)) if len(values)==1 and not unavailable else None
        if len(values)==1 and not unavailable:queries[name]['status']='value_observed'
        elif len(values)>1:queries[name]['status']='conflicting_values'
    return {'plugin_versions':versions,'plugin_version_evidence':version_evidence,
            'plugin_query_observations':queries,'queried_cvars':cvars,
            'plugin_presence_verified':False,
            'cvar_scope':'console_command_context_not_per_player_effective_gain'}
