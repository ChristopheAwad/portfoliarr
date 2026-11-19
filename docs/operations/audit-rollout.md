# Account security upgrade and recovery

## Before upgrading

Portfoliarr uses plain HTTP on the LAN. Do not forward its port to the internet or allow connections from untrusted networks. Finish first-run setup on a trusted connection before opening access to other devices.

Run the following commands from the directory with the server's `docker-compose.yml`. Use a private directory for the backup. The volume contains the portfolio data, password hashes, and session signing key.

```sh
umask 077
BACKUP="$PWD/portfoliarr-before-upgrade.tar"
test ! -e "$BACKUP" &&
  docker compose stop portfoliarr &&
  docker compose run -T --rm --no-deps --entrypoint tar portfoliarr \
    -C /app/instance -cf - . > "$BACKUP"
```

Wait for the backup command to succeed. Extract it into a new, private directory and check the SQLite file there, with any SQLite sidecar files next to it:

```sh
CHECK_DIR=$(mktemp -d)
tar -xf "$BACKUP" -C "$CHECK_DIR" &&
  sqlite3 "$CHECK_DIR/portfolio.db" 'PRAGMA integrity_check;'
```

The result must be `ok`. Keep the archive offline and record the previous image tag or digest. Once the verified new image is available, run `docker compose pull` and `docker compose up -d`. Do not run an old and a new app against the same volume.

## After upgrading

- Everyone signs in again once, including on Android. The upgrade replaces the session signing key because the old version could reuse account IDs. Later restarts keep the new key and sessions.
- Open signup is off after the upgrade. The owner can choose to turn it back on in Preferences.
- When the upgrade adds the role column, it makes account ID 1 the owner if that account still exists. It does not promote a different account automatically. If you can sign in but no one sees the People card, use local owner recovery below.
- If setup cannot claim legacy rows, the upgrade does not create a partial owner account. Keep the app off untrusted networks and inspect a copy of the backup before repairing the database.

## Recover an owner or reset a password

On the server, stop the service before running these commands. Compose uses the same database volume, and the normal entrypoint runs the command as the app user.

```sh
docker compose stop portfoliarr
docker compose run --rm --no-deps portfoliarr python app.py assign-owner YOUR_USERNAME
docker compose up -d
```

`assign-owner` works only when no owner exists. It assigns an existing account, does not transfer ownership, and does not turn signup on. Replace `YOUR_USERNAME` with the exact account name. Check that the account can sign in, see People, and manage signup.

For a forgotten password, use `docker compose run --rm --no-deps portfoliarr python app.py reset-password YOUR_USERNAME` instead. Enter the new password twice when prompted. Other sessions for that account stop working. Restart the service and check that the new password works.

## Restore a snapshot

If the upgrade cannot start or unexpectedly changes a ledger, stop the app. Preserve a separate, stopped-service copy of the current volume as above before replacing anything. A code revert does not undo the migration.

With the service still stopped, confirm that `BACKUP` points to the verified archive you intend to restore. The next command replaces the contents of the app's database volume, including any SQLite sidecars. It does not change any other volume.

```sh
docker compose run -T --rm --no-deps --entrypoint sh portfoliarr -ec '
  cd /app/instance
  find . -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  tar --numeric-owner -xf -
' < "$BACKUP"
```

If extraction fails, leave the app stopped and recover from a verified archive. On a successful restore, run the session rotation command using the updated image **before** restarting. A restored database can contain an older key and older account or password state.

```sh
docker compose run --rm --no-deps portfoliarr python app.py rotate-session-secret
docker compose up -d
```

Verify sign-in, owner controls, and the restored portfolios. Prefer fixing the updated app over reverting it. If a code revert is necessary, use a normal revert PR against the squash commit and restrict network access while running an older image. It restores the old permissions and session behavior.
