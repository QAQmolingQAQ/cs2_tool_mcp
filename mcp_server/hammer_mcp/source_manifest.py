"""Conservative add-on source-tree change guard; not an immutable dependency copy."""
import os
import stat
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


class SourceCopyCancelled(ValueError):
    pass


def copy_source_manifest(manifest,destination,cancelled=None):
    """Copy an exact recorded tree into a new private directory, retaining failure evidence."""
    source=Path(manifest['root']).resolve(strict=True)
    destination=Path(destination).resolve()
    if destination.is_relative_to(source):raise ValueError('private copy must be outside source tree')
    destination.mkdir(exist_ok=False)
    for name,expected in manifest['files'].items():
        if cancelled is not None and cancelled():raise SourceCopyCancelled('source copy cancelled')
        relative=Path(name)
        if relative.is_absolute() or relative.drive or '..' in relative.parts:
            raise ValueError('snapshot relative path invalid')
        original=source/relative;target=destination/relative
        if not original.resolve(strict=True).is_relative_to(source) or original.is_symlink() or original.is_junction():
            raise ValueError('snapshot source escaped or linked')
        before=original.stat()
        identity=lambda value:[value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns]
        if identity(before)!=expected['identity']:raise ValueError('source changed before snapshot copy')
        target.parent.mkdir(parents=True,exist_ok=True)
        with original.open('rb') as reader,target.open('xb') as writer:
            while chunk:=reader.read(1024*1024):
                if cancelled is not None and cancelled():raise SourceCopyCancelled('source copy cancelled')
                writer.write(chunk)
        if identity(original.stat())!=identity(before) or sha256(target)!=expected['sha256']:
            raise ValueError('source changed during snapshot copy')
        target.chmod(stat.S_IREAD)
    if any(manifest_changes(manifest,source_manifest(source)).values()):
        raise ValueError('source tree changed while taking private copy')
    copied=source_manifest(destination)
    if {name:item['sha256'] for name,item in copied['files'].items()}!={name:item['sha256'] for name,item in manifest['files'].items()}:
        raise ValueError('private copy content mismatch')
    return copied
