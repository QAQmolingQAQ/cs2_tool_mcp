"""Detached build worker. Durable state survives MCP server restarts."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sys
import time

if __package__ in (None, ''):
    # Independent desktop worker inherits no MCP stdio handles.
    sys.stdout = sys.stderr = (Path(sys.argv[1]) / 'worker.log').open('a', encoding='utf-8', buffering=1)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hammer_mcp.build_artifact import verify_map_artifact
from hammer_mcp.build_jobs import atomic_json, now, read_json
from hammer_mcp.build_process import CompilerProcess, process_identity
from hammer_mcp.project import sha256


def run(folder: Path):
    request = read_json(folder / 'request.json')
    state = read_json(folder / 'state.json')
    atomic_json(folder / 'worker.json', {'pid': os.getpid(), 'created': process_identity(os.getpid())})
    process = None

    def update(stage=None, **values):
        if stage and stage != state['stage']:
            state['events'].append({'stage': stage, 'at': now()})
            state['stage'] = stage
        state.update(values, updated_at=now())
        atomic_json(folder / 'state.json', state)

    def cancelled():
        return (folder / 'cancel.request').exists()

    try:
        update('snapshot', status='running', worker_pid=os.getpid(), source_basis=request['source_basis'],
               editor_dirty_state=request['editor_dirty_state'], command=request['command'],
               compiler_sha256=request['compiler_sha256'], config_sha256=request['project']['config_sha256'],
               installation_hashes=request['installation_hashes'])
        if cancelled():
            update('cancelled', status='cancelled', finished_at=now(), process_tree_exited=True)
            return
        source = Path(request['source'])
        if sha256(source) != request['source_sha256']:
            raise ValueError('source changed before snapshot')
        if sha256(Path(request['project']['compiler'])) != request['compiler_sha256']:
            raise ValueError('compiler changed after request')
        game = Path(request['project']['game_root'])
        if any(sha256(game / relative) != digest for relative, digest in request['installation_hashes'].items()):
            raise ValueError('game installation changed after request')
        snapshot = Path(request['snapshot'])
        snapshot.parent.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(source, snapshot)
        if sha256(snapshot) != request['source_sha256'] or sha256(source) != request['source_sha256']:
            raise ValueError('source changed while copying snapshot')
        artifact = Path(request['artifact'])
        if artifact.exists():
            raise ValueError('isolated output already exists; refusing stale artifact')
        temporary = folder / 'temp'
        temporary.mkdir()
        if cancelled():
            update('cancelled', status='cancelled', finished_at=now(), process_tree_exited=True)
            return
        env = dict(os.environ, TEMP=str(temporary), TMP=str(temporary))
        with (folder / 'compiler.log').open('ab', buffering=0) as log:
            process = CompilerProcess(request['command'], str(Path(request['project']['compiler']).parent), env, log)
            update('compile', compiler_pid=process.pid, compiler_created=process.identity,
                   temp_path=str(temporary), process_tree_exited=False)
            position = 0
            pending = b''
            cancel_sent = False
            diagnostics = set()
            while True:
                if cancelled() and not cancel_sent:
                    process.terminate()
                    cancel_sent = True
                    update('cancelling', cancel_requested=True)
                with (folder / 'compiler.log').open('rb') as reader:
                    reader.seek(position)
                    chunk = reader.read(1024 * 1024)
                    position += len(chunk)
                pending += chunk
                lines = pending.split(b'\n')
                pending = lines.pop()[-65536:]
                for line in lines:
                    if b'ray tracing not supported on your device' in line:
                        diagnostics.add('gpu_raytracing_unavailable')
                    match = re.search(rb"\.\.\. Building '([^']+)'", line)
                    if match:
                        state['observed_builder'] = match[1].decode('utf-8', errors='replace')
                        if not cancel_sent:
                            update('compile:' + state['observed_builder'])
                code = process.poll()
                if code is not None and process.active_count() == 0 and position >= (folder / 'compiler.log').stat().st_size:
                    break
                time.sleep(0.2)
            update(compiler_exit_code=code, process_tree_exited=True, log_bytes=position, diagnostics=sorted(diagnostics))
        if cancel_sent or cancelled():
            update('cancelled', status='cancelled', finished_at=now())
            return
        source_unchanged = source.exists() and sha256(source) == request['source_sha256']
        update('validate', source_unchanged=source_unchanged)
        validation = verify_map_artifact(str(artifact), request['map_name'], request['mode'], cancelled=cancelled) if artifact.exists() else {'ok': False, 'error': 'compiler did not produce isolated VPK'}
        if validation.get('cancelled') or cancelled():
            update('cancelled', status='cancelled', validation=validation, finished_at=now())
            return
        inputs_unchanged = (sha256(Path(request['project']['compiler'])) == request['compiler_sha256'] and
                            all((game / relative).is_file() and sha256(game / relative) == digest
                                for relative, digest in request['installation_hashes'].items()))
        status = 'failed' if code != 0 or not validation['ok'] else 'succeeded'
        if not inputs_unchanged:
            status = 'inputs_changed'
        if not source_unchanged:
            status = 'source_changed'
        if cancelled():
            status = 'cancelled'
        update(status, status=status, validation=validation, finished_at=now(), inputs_unchanged=inputs_unchanged,
               release_ready=False, dependency_snapshot_complete=False)
    except BaseException as exc:
        # Close the job first: no failure result may leave a compiler subtree alive.
        if process is not None:
            process.close()
            process = None
        update('failed', status='failed', error=f'{type(exc).__name__}: {exc}', finished_at=now())
    finally:
        if process is not None:
            process.close()


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve(strict=True))
