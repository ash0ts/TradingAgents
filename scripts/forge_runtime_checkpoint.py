"""Run in the native Forge Marimo scratchpad after executing and saving cells.

Exports the active runtime's actual outputs. This supports runtime images that
save source automatically but do not yet save static HTML. No keys are copied
into source, output, or the checkpoint receipt.
"""
import hashlib
import importlib.metadata
import json
import os
import re
from pathlib import Path

import requests
import wandb


def checkpoint():
    base = "http://127.0.0.1:2719"
    sessions = requests.post(base + "/api/home/running_notebooks", json={}, timeout=30).json()["files"]
    if len(sessions) != 1:
        raise RuntimeError("Expected exactly one active notebook session")
    session_id = sessions[0].get("sessionId") or sessions[0].get("session_id")
    headers = {"Marimo-Session-Id": session_id}

    def export(files):
        response = requests.post(base + "/api/export/html", headers=headers,
                                 json={"download": False, "includeCode": True, "files": files}, timeout=60)
        response.raise_for_status()
        return response.content

    html = export([])
    files = sorted(set(re.findall(r"/@file/[^\\\s\"&'/]+\.[\dA-Za-z]+", html.decode())))
    if files:
        html = export(files)
    source = Path("/workspace/notebook.py").read_bytes()
    with wandb.init(id=os.environ["WANDB_NOTEBOOK_ANCHOR_RUN"], resume="allow",
                    entity=os.environ["WANDB_ENTITY"], project=os.environ["WANDB_PROJECT"],
                    settings=wandb.Settings(x_update_finish_state=False, console="off", silent=True)) as run:
        artifact = wandb.Artifact(os.environ["WANDB_NOTEBOOK_COLLECTION"],
                                  type=os.environ["WANDB_NOTEBOOK_ARTIFACT_TYPE"],
                                  metadata={"kind": "checkpoint", "session_id": os.environ["WANDB_NOTEBOOK_SESSION_ID"],
                                            "user_id": os.environ["WANDB_NOTEBOOK_USER_ID"],
                                            "publication_method": "native-runtime-export"})
        with artifact.new_file("notebook.py", mode="wb") as handle:
            handle.write(source)
        with artifact.new_file("__marimo__/notebook.html", mode="wb") as handle:
            handle.write(html)
        saved = run._log_artifact(artifact, aliases=["latest"], is_user_created=True)
        saved.wait(timeout=120)
        return {"version": saved.version, "source_sha256": hashlib.sha256(source).hexdigest(),
                "static_sha256": hashlib.sha256(html).hexdigest(), "static_bytes": len(html),
                "runtime_versions": {name: importlib.metadata.version(name) for name in ["marimo", "numpy", "pandas", "matplotlib", "wandb"]}}


if __name__ == "__main__":
    print(json.dumps(checkpoint()))
