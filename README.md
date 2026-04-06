# kellerkompanie-ts3bot

This project is an automated bot for TeamSpeak 3 that connects the Kellerkompanie backend with TeamSpeak.

## What does the bot do?

The bot connects to the TeamSpeak 3 ServerQuery interface and reacts to server events:

- **Client joins**: Greets guest users with a configurable welcome message. For registered users whose TeamSpeak
  identity is not yet linked to the website, it generates a one-time auth key and sends a link to connect the accounts.
- **Account linking**: Users can request a new link via the `!link` command in a private message to the bot.
- **Squad XML**: Automatically creates Squad XML roster entries for linked users by looking up their username from the
  backend API.
- **Stammspieler status**: Checks the backend API for each linked user's "Stammspieler" (regular player) status and adds
  or removes the corresponding TeamSpeak server group.
- **Chat commands**: Responds to `!hi`, `!edit`, and `!link` in private messages.

The bot uses two MariaDB databases - one for TeamSpeak account data (links, auth keys, messages) and one for the
website (Squad XML entries).

## Chat commands

Users can send the following commands to the bot via private message:

| Command | Description                                                                                               |
|---------|-----------------------------------------------------------------------------------------------------------|
| `!hi`   | Bot replies with a greeting                                                                               |
| `!link` | Generates a one-time auth key and sends a link to connect the TeamSpeak identity with the website account |
| `!edit` | Responds with a confirmation message                                                                      |

## Configuration

The configuration file is in YAML format. On deployed systems the default location is:

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

### `database` - MariaDB connections

Two databases are configured under `database.teamspeak` and `database.webpage`, each with:

| Key        | Default                           | Description       |
|------------|-----------------------------------|-------------------|
| `host`     | `localhost`                       | Database host     |
| `name`     | `keko_teamspeak` / `keko_webpage` | Database name     |
| `username` | `username`                        | Database user     |
| `password` | `password`                        | Database password |

### `api` - Backend API

| Key        | Default                 | Description                                |
|------------|-------------------------|--------------------------------------------|
| `base_url` | `http://localhost:5000` | Base URL of the Kellerkompanie backend API |

### `messages` - Message templates

| Key             | Default    | Description                                    |
|-----------------|------------|------------------------------------------------|
| `guest_welcome` | `Welcome!` | Welcome message sent to guest users on connect |

### Environment variable overrides

All settings can be overridden via environment variables using the prefix `KEKO_` and double underscores for nesting.
For example:

```
KEKO_TS3__HOST=192.168.1.10
KEKO_DATABASE__TEAMSPEAK__PASSWORD=secret
KEKO_API__BASE_URL=http://10.0.0.5:5000
```

## Development

### Prerequisites

* [uv](https://docs.astral.sh/uv/) (Python package manager)
* Python 3.14 or higher (uv will install it automatically if missing)
* MariaDB client libraries (`libmariadb-dev` on Debian/Ubuntu, `mariadb-connector-c` on macOS via Homebrew)

### Setup

Clone the repository and install all dependencies:

```
git clone <repo-url>
cd kellerkompanie-teamspeak3-bot
uv sync
```

This creates a virtual environment in `.venv/` and installs the project in editable mode with all dependencies locked
via `uv.lock`.

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
uv run scripts/build_deb.py
```
