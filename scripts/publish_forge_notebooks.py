"""Publish through the native Forge record and Marimo runtime/editor APIs.

Runtime launch requires the authenticated browser. Import into the existing
native source collection, then open, execute and save in the runtime/editor.
Receipts contain IDs and hashes only; signed URLs and credentials are omitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import wandb

ENTITY = "wandb"
PROJECT = "tradingagents-election-lab"
FIELDS = "id name viewerPermissions currentVersion { artifactTypeName artifactCollectionName versionIndex sourceFileName } lastSourceEditedAt lastStaticOutputAt staticOutputUrl"
TITLES = ["Meet the investment committee.", "Confident, expensive, and wrong?", "Did it beat doing nothing?"]


class Publisher:
    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.api = wandb.Api(timeout=120)

    def gql(self, query, variables):
        return self.api._service_api.execute_graphql(query, variables)

    def record(self, notebook_id):
        return self.gql("query($id: ID!) { notebook(id:$id) { " + FIELDS + " } }", {"id": notebook_id})["notebook"]

    def records(self):
        result = self.gql("query($e:String!,$p:String!){project(entityName:$e,name:$p){notebooks(first:50){edges{node{" + FIELDS + "}}}}}", {"e": ENTITY, "p": PROJECT})
        return [e["node"] for e in result["project"]["notebooks"]["edges"]]

    def ensure(self):
        records = self.records()
        by_name = {r["name"]: r for r in records}
        result = []
        for index, title in enumerate(TITLES):
            if title in by_name:
                result.append(by_name[title])
                continue
            # Adopt only the exact initial record created for this campaign.
            record = next((r for r in records if index == 0 and r["id"] == "Tm90ZWJvb2s6MTUyNjA="), None)
            if record is None:
                record = self.gql("mutation($e:String!,$p:String!){createNotebook(input:{entityName:$e,projectName:$p,template:BASIC}){notebook{id name}}}", {"e": ENTITY, "p": PROJECT})["createNotebook"]["notebook"]
            record = self.gql("mutation($id:ID!,$name:String!){renameNotebook(input:{id:$id,name:$name}){notebook{" + FIELDS + "}}}", {"id": record["id"], "name": title})["renameNotebook"]["notebook"]
            result.append(record)
        (self.output / "notebook-records.json").write_text(json.dumps(result, indent=2))
        return result

    def import_source(self, record, source_path):
        """Import into this native record's existing source collection.

        Open the record in the authenticated browser, execute, and save in its
        editor next. API-key authentication cannot launch notebook runtimes.
        """
        current = self.record(record["id"])
        collection = current["currentVersion"]["artifactCollectionName"]
        with wandb.init(entity=ENTITY, project=PROJECT, job_type="notebook-publication",
                        name="Native source import: " + record["name"],
                        settings=wandb.Settings(console="off")) as run:
            artifact = wandb.Artifact(collection, type="notebook", metadata={
                "kind": "source-import", "source": "ash0ts/TradingAgents",
                "requires_hosted_execution": True})
            artifact.add_file(str(source_path), name="notebook.py")
            saved = run.log_artifact(artifact)
            saved.wait(timeout=120)
            return {"notebook_id": record["id"], "version": saved.version,
                    "source_sha256": hashlib.sha256(Path(source_path).read_bytes()).hexdigest()}

    def verify(self, record, destination):
        """Read exact committed head, never assume the latest alias is current."""
        current = self.record(record["id"])
        version = current["currentVersion"]
        artifact = self.api.artifact(f"{ENTITY}/{PROJECT}/{version['artifactCollectionName']}:v{version['versionIndex']}")
        path = artifact.get_entry(version["sourceFileName"]).download(root=str(destination))
        receipt = {"notebook_id": record["id"], "name": record["name"], "version": version,
                   "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                   "last_source_edited_at": current["lastSourceEditedAt"],
                   "last_static_output_at": current["lastStaticOutputAt"],
                   "has_static_output": bool(current["staticOutputUrl"]),
                   "url": "https://forge.coreweave.com/notebooks/" + record["id"]}
        if receipt["has_static_output"]:
            html = Path(artifact.get_entry("__marimo__/notebook.html").download(root=str(destination)))
            receipt.update(static_sha256=hashlib.sha256(html.read_bytes()).hexdigest(),
                           static_bytes=html.stat().st_size)
        (Path(destination) / "receipt.json").write_text(json.dumps(receipt, indent=2))
        return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="lab-runs/election-v1")
    parser.add_argument("--index", type=int, choices=[1, 2, 3])
    parser.add_argument("--import-source", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    publisher = Publisher(args.output)
    records = publisher.ensure()
    print(json.dumps([{"id": r["id"], "name": r["name"]} for r in records]), flush=True)
    if args.import_source or args.verify:
        for index, (record, path) in enumerate(zip(records, sorted(Path("notebooks").glob("0*.py")), strict=True), 1):
            if args.index is None or index == args.index:
                result = publisher.import_source(record, path) if args.import_source else publisher.verify(record, publisher.output / (path.stem + "-readback"))
                print(json.dumps(result), flush=True)
