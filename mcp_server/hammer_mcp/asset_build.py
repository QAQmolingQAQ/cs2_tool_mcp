"""Build one source asset with the installed CS2 resource compiler."""
from __future__ import annotations

from pathlib import Path
import subprocess
import os
import tempfile
import time
from uuid import uuid4

from .build_jobs import atomic_json, now
from .build_process import CompilerProcess
from .edit_preflight import file_evidence
from .build_artifact import VpkEntry, resource_blocks


_BUILDABLE = {".vmdl", ".vmat", ".vpcf"}


def _paths(path: str) -> tuple[Path, Path, Path]:
    source = Path(path).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in _BUILDABLE:
        raise ValueError("path must name an existing .vmdl, .vmat, or .vpcf")
    parts = source.parts
    lowered = [part.lower() for part in parts]
    for index in range(len(parts) - 3):
        if lowered[index:index + 2] == ["content", "csgo_addons"]:
            game_root = Path(*parts[:index])
            addon = parts[index + 2]
            relative = Path(*parts[index + 3:])
            compiler = game_root / "game" / "bin" / "win64" / "resourcecompiler.exe"
            compiled = game_root / "game" / "csgo_addons" / addon / relative
            compiled = compiled.with_suffix(source.suffix + "_c")
            if not compiler.is_file():
                raise FileNotFoundError(f"CS2 resource compiler not found: {compiler}")
            return source, compiler, compiled
    raise ValueError("source must be inside content/csgo_addons/<addon>")


def _compile(command, compiler, folder, record):
    process=None
    try:
        temporary=folder/'temp';temporary.mkdir()
        with (folder/'compiler.log').open('ab',buffering=0) as log:
            process=CompilerProcess(command,str(compiler.parent),
                dict(os.environ,TEMP=str(temporary),TMP=str(temporary)),log)
            record.update(status='running',compiler_pid=process.pid,compiler_created=process.identity,
                          process_tree_exited=False)
            atomic_json(folder/'record.json',record)
            deadline=time.monotonic()+120
            while True:
                code=process.poll()
                if code is not None and process.active_count()==0:
                    record['process_tree_exited']=True
                    return code
                if time.monotonic()>=deadline:raise TimeoutError('asset compilation timed out')
                time.sleep(0.1)
    finally:
        if process is not None:process.close()


def cs2_asset_compile(path: str, confirm: bool = False) -> dict:
    """Compile an isolated add-on model, material, or particle; validate fresh output.

    Preview by default. A UUID sibling source preserves relative references and
    produces a unique compiled path without replacing the original artifact.
    Records input/compiler hashes, process identity, log and resource block bounds.
    Synchronous, not a detached build job; dependency snapshot is not yet complete.
    """
    record=None;folder=None
    try:
        if not isinstance(confirm,bool):raise ValueError('confirm must be bool')
        source,compiler,original_output=_paths(path)
        source_before=file_evidence(source);compiler_before=file_evidence(compiler)
        if not confirm:
            return {'ok':True,'preview':True,'source':str(source),'output':None,
                    'original_output':str(original_output),'compiler':str(compiler),
                    'source_sha256':source_before['sha256'],
                    'output_policy':'unique UUID sibling; original artifact never replaced'}
        identifier=uuid4().hex
        folder=Path(tempfile.gettempdir())/'cs2_asset_jobs'/identifier
        folder.mkdir(parents=True,exist_ok=False)
        snapshot=source.with_name('mcp_asset_'+identifier+source.suffix)
        _,_,compiled=_paths(path)
        compiled=compiled.with_name(snapshot.name+'_c')
        record={'version':1,'job_id':identifier,'status':'snapshot','created_at':now(),
                'source':str(source),'source_evidence':source_before,'compiler_evidence':compiler_before,
                'snapshot':str(snapshot),'output':str(compiled),'original_output':str(original_output),
                'dependency_snapshot_complete':False,'release_ready':False,
                'record_path':str(folder/'record.json'),'process_tree_exited':None}
        atomic_json(folder/'record.json',record)
        if compiled.exists():raise ValueError('isolated output already exists')
        with source.open('rb') as reader,snapshot.open('xb') as writer:
            while chunk:=reader.read(1024*1024):writer.write(chunk)
        if file_evidence(source)!=source_before or file_evidence(snapshot)['sha256']!=source_before['sha256']:
            raise ValueError('source changed while snapshotting')
        command=[str(compiler),'-nop4','-i',str(snapshot),'-fshallow']
        record['command']=command
        atomic_json(folder/'record.json',record)
        code=_compile(command,compiler,folder,record)
        record.update(exit_code=code,status='validating')
        atomic_json(folder/'record.json',record)
        if code!=0:raise ValueError('resource compiler failed with exit code '+str(code))
        if (file_evidence(source)!=source_before or file_evidence(compiler)!=compiler_before or
                file_evidence(snapshot)['sha256']!=source_before['sha256']):
            raise ValueError('source/snapshot/compiler changed during compilation')
        output_before=file_evidence(compiled)
        entry=VpkEntry(compiled,0,compiled.stat().st_size,b'',0)
        blocks=resource_blocks(entry,nonempty=True)
        if 'DATA' not in blocks:raise ValueError('nonempty DATA resource block required')
        if file_evidence(compiled)!=output_before:raise ValueError('output changed during validation')
        record.update(ok=True,status='succeeded',output_exists=True,output_evidence=output_before,
                      resource_blocks=blocks,finished_at=now())
        atomic_json(folder/'record.json',record)
        return record
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        failure={'ok':False,'source':path,'error':f'{type(error).__name__}: {error}'}
        if record is not None:
            record.update(failure,status='failed',finished_at=now())
            atomic_json(folder/'record.json',record)
            return record
        return failure
