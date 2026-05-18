# kellerkompanie-ts3bot

Automated TeamSpeak 3 bot that bridges the Kellerkompanie TS3 server with the
[kellerkompanie-webpage](https://github.com/kellerkompanie/kellerkompanie-webpage)
backend.

## What does the bot do?

The bot connects to the TeamSpeak 3 ServerQuery interface and reacts to server events:

- **Client joins**: greets guest users with the admin-configured welcome message
  fetched from the webpage. For registered users whose TS identity is not yet
  linked to the website, it asks the webpage to mint a one-time authkey and PMs
  the resulting link.
- **Account linking**: users can request a fresh link via `!link` in a PM. The
  bot does not generate authkeys itself; the webpage owns the
  `keko_teamspeak.teamspeak_authkeys` table and returns a ready-to-use URL.
- **Squad XML**: on join, asks the webpage to add a `squad_xml_entries` row for
  the linked user. The webpage resolves the display name and regenerates the
  on-disk `squad.xml` as a background task.
- **Stammspieler status**: queries the webpage for each linked user's
  Stammspieler status and adds or removes the corresponding TS server group.
- **Chat commands**: `!hi` and `!link` in private messages.

## Architecture

The bot is a thin TS3 client. **It has no database connection.** All persistent
state (account links, authkeys, welcome messages, squad.xml roster) lives in
the webpage's `keko_teamspeak` database and is reached only through
`/teamspeak/*` HTTP endpoints documented in the webpage repo.

```
TeamSpeak 3 server ─── ServerQuery ───┐
                                      │
                                  keko-ts3bot ──── HTTP (Bearer token) ───→ kellerkompanie-webpage
                                                                                   │
                                                                                   ▼
                                                                            keko_teamspeak DB
                                                                            keko_webpage DB
```

All API calls are best-effort: network errors are logged at WARNING and the
affected action is skipped. The bot never crashes on a webpage outage.

## Chat commands

| Command | Description                                                                                                                |
|---------|----------------------------------------------------------------------------------------------------------------------------|
| `!hi`   | Bot replies with a greeting                                                                                                |
| `!link` | Asks the webpage to mint a fresh authkey and PMs the user the link to connect their TS identity with their website account |

## Configuration

YAML. On deployed systems the default path is:

```
/etc/keko-ts3bot/keko-ts3bot.yaml
```

For local development it is loaded from `configs/keko-ts3bot.yaml`.

### `ts3` - TeamSpeak 3 ServerQuery connection

| Key               | Default              | Description                               |
|-------------------|----------------------|-------------------------------------------|
| `host`            | `127.0.0.1`          | Hostname or IP of the TS3 server          |
| `port`            | `10011`              | ServerQuery port                          |
| `user`            | `serveradmin`        | ServerQuery login username                |
| `password`        | `password`           | ServerQuery login password                |
| `nickname`        | `Kellerkompanie Bot` | Bot display name in TeamSpeak             |
| `default_channel` | `Botchannel`         | Channel the bot moves to after connecting |
| `server_id`       | `1`                  | Virtual server ID                         |

### `api` - Webpage API

| Key                           | Default                 | Description                                                                          |
|-------------------------------|-------------------------|--------------------------------------------------------------------------------------|
| `base_url`                    | `http://localhost:8000` | Base URL of the kellerkompanie-webpage instance                                      |
| `token`                       | `change-me`             | Bearer token. **Must match** `ts3bot_api_token` in the webpage's `keko-webpage.yaml` |
| `timeout`                     | `10.0`                  | Request timeout in seconds for every API call                                        |
| `guest_welcome_cache_seconds` | `300.0`                 | How long to cache the guest-welcome message between fetches                          |

Generate a fresh token with:

```
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

and paste the same value into both YAML files.

### Environment variable overrides

All settings can be overridden via environment variables using prefix `KEKO_`
and double underscores for nesting:

```
KEKO_TS3__HOST=192.168.1.10
KEKO_API__BASE_URL=https://kellerkompanie.com
KEKO_API__TOKEN=...
```

## Development

### Prerequisites

* [uv](https://docs.astral.sh/uv/)
* Python 3.14 or higher (uv installs it automatically)

No native dependencies. The bot is pure Python over HTTP.

### Setup

```
git clone <repo-url>
cd kellerkompanie-ts3bot
uv sync
```

### Running

```
uv run keko-bot --config configs/keko-ts3bot.yaml
```

### Managing dependencies

```
uv add <package>        # add a new dependency
uv remove <package>     # remove a dependency
uv sync                 # re-sync environment from lockfile
uv lock --upgrade       # upgrade all dependencies
```

### Building

To build a `.deb` package for deployment:

```
python scripts/build_deb.py
```

Requires Docker. Output is written to `dist/keko-ts3bot_<version>-1_amd64.deb`.

## Deployment

On the target Debian/Ubuntu host:

```
sudo dpkg -i dist/keko-ts3bot_*.deb
sudo apt install -f      # resolve any leftover deps
sudo nano /etc/keko-ts3bot/keko-ts3bot.yaml   # set ts3 + api.token
sudo systemctl start keko-ts3bot
journalctl -u keko-ts3bot -f
```

The bot needs network reach to:

- the TS3 ServerQuery port (`ts3.host:ts3.port`)
- the webpage instance (`api.base_url`)

It does **not** need MariaDB credentials anymore; remove them from any older
config you migrate from.
