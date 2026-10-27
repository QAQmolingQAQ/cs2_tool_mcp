"""Conservative add-on source-tree change guard; not an immutable dependency copy."""
import os
from pathlib import Path
from .project import sha256


def source_manifest(root,excluded=()):
    root=Path(root).resolve(strict=True)
    ignored={Path(path).resolve() for path in excluded}
    files={};pending=[root];entries=0;total=0
    while pending:
        directory=pending.pop()
        with os.scandir(directory) as listing:
            for entry in listing:
                entries+=1
                if entries>20000:raise ValueError('source manifest entry budget exceeded')
                path=Path(entry.path)
                if path.is_symlink() or path.is_junction():raise ValueError('source manifest rejects links/junctions')
                resolved=path.resolve(strict=True)
                if not resolved.is_relative_to(root):raise ValueError('source manifest path escaped root')
                if entry.is_dir(follow_symlinks=False):pending.append(path);continue
                if resolved in ignored:continue
                if not entry.is_file(follow_symlinks=False):raise ValueError('unsupported source file kind')
                before=path.stat();total+=before.st_size
                if total>1024*1024*1024:raise ValueError('source manifest byte budget exceeded')
                def identity(stat):return [stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
                digest=sha256(path)
                if identity(path.stat())!=identity(before):raise ValueError('source changed while hashing: '+str(path))
                files[path.relative_to(root).as_posix()]={'sha256':digest,'identity':identity(before)}
    return {'version':1,'root':str(root),'files':dict(sorted(files.items())),
            'file_count':len(files),'bytes_hashed':total,'scope':'configured_addon_source_tree',
            'immutable_snapshot':False,'external_dependency_coverage_complete':False}


def manifest_changes(before,after):
    if before['root']!=after['root']:raise ValueError('source manifest root changed')
    old,new=before['files'],after['files']
    return {'added':sorted(new.keys()-old.keys()),'removed':sorted(old.keys()-new.keys()),
            'changed':sorted(name for name in old.keys()&new.keys() if old[name]!=new[name])}
