---
title: Upgrade and back up ParseHawk
description: Preserve local data, apply migrations, and recover safely during source upgrades.
sidebar:
  order: 7
---

ParseHawk keeps its local database, uploaded files, provider-secret key, runtime
state, logs, and traces under the configured data directory. Back up that
directory as one unit.

## Back up a local installation

Stop services before copying SQLite and file storage:

```console
parsehawk stop
cp -a data "data.backup.$(date +%Y%m%d-%H%M%S)"
```

If `data.dir` points elsewhere, use the path shown by `parsehawk config list`.
Protect the backup like the source documents it contains.

## Upgrade a source checkout

```console
git pull --ff-only
uv tool install --editable . --force
parsehawk start
```

`parsehawk start` applies pending ordered migrations before serving traffic. To
inspect them first:

```console
parsehawk migrate status
```

## Control migration timing

Operators who need a maintenance window can opt out of startup migrations:

```console
parsehawk start -x migrate
parsehawk migrate status
parsehawk migrate
parsehawk restart
```

The equivalent environment override is `PARSEHAWK_SKIP_MIGRATIONS=1`.

## Restore

```console
parsehawk stop
mv data data.failed
cp -a data.backup.YYYYMMDD-HHMMSS data
parsehawk start
parsehawk doctor
```

Provider API keys depend on the encryption key stored with the data directory,
or on the same `PARSEHAWK_SECRET_KEY` override. Restoring only the database can
make stored credentials unreadable.

Do not remove a live data directory. Existing processes can keep open SQLite
handles and continue serving unexpected state.
