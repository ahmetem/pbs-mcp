# pbs-mcp

MCP server for **Proxmox Backup Server**. Exposes datastore status, snapshot
inventory, garbage collection, verify, and prune over the PBS REST API as
13 LLM-callable tools. Designed for the
[Model Context Protocol](https://modelcontextprotocol.io).

Türkçe için → [README.tr.md](README.tr.md)

## Why

PBS already has a polished web UI. This server is for the cases where the UI
isn't where you are — answering "is anything broken?" from a chat assistant,
or wiring PBS state into a homelab agent that schedules verifies and prunes
based on real conditions.

## Tools (13)

| # | Tool | Mode | Notes |
|---|------|------|-------|
| 1 | `pbs_list_datastores` | read | Configured datastores + schedules |
| 2 | `pbs_datastore_status` | read | total / used / available bytes |
| 3 | `pbs_list_groups` | read | Per-group snapshot count, owner, corruption flag |
| 4 | `pbs_list_snapshots` | read | Size, files, last verify state, protected flag |
| 5 | `pbs_get_task_status` | read | UPID → running / OK / error |
| 6 | `pbs_get_task_log` | read | Tail or paginate a task log |
| 7 | `pbs_list_tasks` | read | Recent tasks, optional filters |
| 8 | `pbs_gc_status` | read | Last GC stats: bytes referenced, pending, removed |
| 9 | `pbs_run_gc` | **write** | Trigger GC, returns UPID (async) |
| 10 | `pbs_run_verify` | **write** | Trigger verify, optional snapshot scope |
| 11 | `pbs_prune_dry_run` | read | Preview which snapshots a retention policy would drop |
| 12 | `pbs_prune` | **write** | Apply retention policy |
| 13 | `pbs_forget_snapshot` | **write** | Delete one snapshot (corrupt cleanup) |

Write tools require both `PBS_ALLOW_WRITE=true` in the environment **and**
`confirm=true` in the call itself. Restore is intentionally out of scope —
the standard `proxmox-mcp` already handles restore from PBS via `archive=`
on the Proxmox VE side.

## Setup

### 1. Create an API token in PBS

In a shell on the PBS host (`pct enter 205` from Proxmox if PBS lives in
an LXC, otherwise just SSH):

```bash
# Generate a token under root@pam
proxmox-backup-manager user generate-token root@pam mcp

# Grant it admin on your datastore
proxmox-backup-manager acl update /datastore/<your-datastore> \
  DatastoreAdmin --auth-id 'root@pam!mcp'
```

The `generate-token` output includes a `value` field — that's the secret,
shown only once. Save it.

> Why DatastoreAdmin? PBS performs an owner check on prune. Either you give
> the token DatastoreAdmin (this), or you keep moving backup ownership with
> `change-owner` after every push. Admin scope is simpler and stays inside
> one datastore.

### 2. Configure the MCP server

```bash
git clone https://github.com/ahmetem/pbs-mcp.git
cd pbs-mcp
cp .env.example .env
# Edit .env: fill in PBS_HOST, PBS_TOKEN_ID, PBS_TOKEN_SECRET
pip install -e .
```

### 3. Register with your MCP client

For Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pbs": {
      "command": "python",
      "args": ["/absolute/path/to/pbs-mcp/pbs_mcp.py"]
    }
  }
}
```

Restart the client. The `pbs_*` tools should appear.

## Safety model

* **Read-only by default.** Out of the box `PBS_ALLOW_WRITE=false`, so every
  state-changing tool refuses regardless of `confirm`.
* **Two-key requirement on writes.** `PBS_ALLOW_WRITE=true` opens the door;
  each call still needs `confirm=true`. Two independent toggles, two
  intentional actions.
* **Async tasks return UPIDs, not results.** `run_gc` and `run_verify` kick
  off work and hand back a UPID immediately. Poll with `get_task_status`.
  This prevents the MCP request from blocking for hours.
* **Token scoped to one datastore.** ACLs live at `/datastore/<name>`, not
  at `/`. A leaked token can't read PBS user lists or remote sync configs.

## Notes / gotchas

* **First-call cache lag**: PBS caches ACLs for a few seconds. If you just
  granted permissions and the next call returns "permission check failed",
  wait 3 seconds and retry.
* **Token vs user permissions**: PBS API tokens get the intersection of the
  parent user's ACLs and the token's ACLs. With `root@pam!mcp` the parent
  is unrestricted, so only the token's ACL matters in practice.
* **Self-signed cert**: PBS ships with a self-signed cert. The default
  `PBS_VERIFY_TLS=false` is fine for a LAN setup. For real CAs, set
  `PBS_VERIFY_TLS=true` and `PBS_CA_BUNDLE` to a PEM file.
* **UPIDs are tied to their creator**: a UPID created by a now-deleted user
  becomes unreadable. Don't recycle PBS users while there are pending tasks.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
