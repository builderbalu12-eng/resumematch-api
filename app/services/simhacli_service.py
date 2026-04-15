"""
SimhaCLI subprocess service.

Runs `simhacli --approval yolo "<prompt>"` as an async subprocess and
streams each output line into an asyncio.Queue so SSE endpoints can relay
them to the browser in real time.

Usage pattern
─────────────
1.  job_id = str(uuid4())
2.  await simhacli_service.start(job_id, prompt, cwd=<tmp_dir>)
3.  GET /stream/<job_id>  → StreamingResponse(simhacli_service.sse_generator(job_id))
"""

import asyncio
import os
import re
import uuid
from typing import AsyncGenerator, Dict, Optional

# job_id → asyncio.Queue[str | None]   (None = sentinel = done)
_queues: Dict[str, asyncio.Queue] = {}
_results: Dict[str, str] = {}          # job_id → final full output
_errors: Dict[str, str] = {}           # job_id → error message (if failed)


async def start(job_id: str, prompt: str, cwd: Optional[str] = None) -> None:
    """
    Launch SimhaCLI in the background.  Output lines are pushed into the
    queue identified by job_id.  Call before opening the SSE stream.
    """
    q: asyncio.Queue = asyncio.Queue()
    _queues[job_id] = q

    async def _run():
        full_output: list[str] = []
        try:
            env = {**os.environ}
            proc = await asyncio.create_subprocess_exec(
                "simhacli", "--approval", "yolo", prompt,
                cwd=cwd or "/tmp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                full_output.append(line)
                await q.put(line)
            await proc.wait()
            _results[job_id] = "\n".join(full_output)
        except FileNotFoundError:
            err = "SimhaCLI not installed on server. Run: pip install simhacli"
            _errors[job_id] = err
            await q.put(f"ERROR: {err}")
        except Exception as exc:
            err = str(exc)
            _errors[job_id] = err
            await q.put(f"ERROR: {err}")
        finally:
            await q.put(None)   # sentinel

    asyncio.create_task(_run())


async def sse_generator(job_id: str) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted strings.
    Blocks until each line is available, then yields it.
    Sends a final `event: done` when the subprocess exits.
    """
    q = _queues.get(job_id)
    if q is None:
        yield "data: ERROR: unknown job_id\n\n"
        yield "event: done\ndata: \n\n"
        return

    while True:
        line = await q.get()
        if line is None:
            break
        # Escape newlines inside data field
        safe = line.replace("\n", " ")
        yield f"data: {safe}\n\n"

    # Extract any Vercel URL from the full output — send BEFORE done so client receives it
    full = _results.get(job_id, "")
    urls = re.findall(r"https://[^\s]+\.vercel\.app[^\s]*", full)
    if urls:
        yield f"event: url\ndata: {urls[-1]}\n\n"

    # Send final event so the client knows it's complete
    yield f"event: done\ndata: complete\n\n"

    # Cleanup (keep results for a bit; GC will clean the rest eventually)
    _queues.pop(job_id, None)


def get_result(job_id: str) -> Optional[str]:
    return _results.get(job_id)


def get_error(job_id: str) -> Optional[str]:
    return _errors.get(job_id)


def extract_vercel_url(output: str) -> Optional[str]:
    urls = re.findall(r"https://[^\s]+\.vercel\.app[^\s]*", output)
    return urls[-1] if urls else None


def new_job_id() -> str:
    return str(uuid.uuid4())
