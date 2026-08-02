#!/usr/bin/env python
"""CLI entry point for Board Host AI v0.1.

Designed for single-shot invocation from a scheduler (Windows Task
Scheduler, cron, systemd timer — see docs/Board_Host_AI_v0.1.md §18).
`--loop` is provided only for local interactive testing; production
deployments should prefer scheduling a single run over a long-lived
process.
"""

import argparse
import os
import time

import yaml

from src.state import HostState
from src.board_client import BoardClient
from src.vertex_client import VertexClient
from src.watcher import run_once
from src.responder import load_system_prompt

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def build_components(config):
    board_client = BoardClient(
        config["board"]["base_url"], timeout_seconds=config["board"]["timeout_seconds"]
    )
    credentials_path = os.path.normpath(os.path.join(ROOT, config["vertex_ai"]["credentials_path"]))
    vertex_client = VertexClient(
        project_id=config["vertex_ai"]["project_id"],
        credentials_path=credentials_path,
        primary=config["vertex_ai"]["primary"],
        fallback=config["vertex_ai"]["fallback"],
    )
    state = HostState.load(os.path.join(ROOT, config["state"]["path"]))
    system_prompt = load_system_prompt(os.path.join(ROOT, "prompts"))
    return board_client, vertex_client, state, system_prompt


def main():
    parser = argparse.ArgumentParser(description="Board Host AI v0.1 runner")
    parser.add_argument("--config", default=os.path.join(ROOT, "config", "host.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Log decisions without posting")
    parser.add_argument("--loop", action="store_true", help="Keep running locally (for testing only)")
    args = parser.parse_args()

    config = load_config(args.config)
    board_client, vertex_client, state, system_prompt = build_components(config)

    def run():
        now_ts = int(time.time() * 1000)
        summary = run_once(config, state, board_client, vertex_client, system_prompt, now_ts, dry_run=args.dry_run)
        if not args.dry_run:
            state.save()
        print(f"[run_host] {summary}")
        return summary

    if not args.loop:
        run()
        return

    interval_seconds = config["board_host"]["scan_interval_minutes"] * 60
    while True:
        run()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
